"""`/import_sales` Telegram handler — monthly sales → Airtable Top-15.

End-of-month workflow (founder side):
  1. Open Telegram, send `/import_sales`.
  2. Bot prompts: "send me the month folder as a ZIP".
  3. Founder right-clicks the month folder on their Mac → Compress →
     drags the resulting `.zip` into Telegram.
  4. Bot parses the ZIP, detects the period, shows preview with
     ✅ confirm / ❌ cancel buttons.
  5. On ✅: rows go into `sales` table (with wipe-period for idempotency)
     and Top-15 lands in the Airtable "Monthly Top Sellers" table tagged
     with `Period=YYYY-MM`. Bot replies with summary + Airtable link.

Idempotent: re-uploading the same month wipes existing DB rows in that
month range and existing Airtable rows with the same Period, then writes
fresh. Safe to re-run after a correction.
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src import config, demand_analysis, sales_importer
from src.airtable_client import AirtableError, from_config as airtable_from_config
from src.logging_setup import get_logger
from src.telegram_bot import messages

log = get_logger(__name__)
router = Router()


# ─── FSM ─────────────────────────────────────────────────────────────────────


class Importing(StatesGroup):
    waiting_for_zip = State()
    confirming = State()


# ─── Helpers ─────────────────────────────────────────────────────────────────


_TMP_ROOT = Path("/tmp/uygun_sales_import")


def _new_session_dir(chat_id: int) -> Path:
    """Each /import_sales invocation gets its own scratch dir so re-runs
    don't collide. Cleaned up after the flow ends."""
    p = _TMP_ROOT / str(chat_id) / uuid.uuid4().hex
    p.mkdir(parents=True, exist_ok=True)
    return p


def _build_confirm_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=messages.IMPORT_BTN_CONFIRM,
                             callback_data="import_sales:confirm"),
        InlineKeyboardButton(text=messages.IMPORT_BTN_CANCEL,
                             callback_data="import_sales:cancel"),
    )
    return kb


def _period_label(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _build_airtable_records(
    top: list[demand_analysis.TopSeller],
    *,
    period: str,
    imported_at_iso: str,
    field_id: dict[str, str],
) -> list[dict]:
    """Translate TopSeller dataclasses into Airtable {fieldId: value} dicts."""
    out: list[dict] = []
    for t in top:
        fields = {
            field_id["code"]: t.code,
            field_id["period"]: period,
            field_id["rank"]: t.rank,
            field_id["name"]: t.name,
            field_id["qty"]: int(t.qty),
            field_id["revenue"]: t.revenue,
            field_id["avg_unit"]: t.avg_unit_price,
            field_id["days"]: t.days_sold,
            field_id["tx"]: t.tx_count,
            field_id["co"]: t.unique_companies,
            field_id["last"]: t.last_sold.isoformat(),
            field_id["trend"]: t.trend_tag,
            field_id["insight"]: t.insight,
            field_id["imported_at"]: imported_at_iso,
        }
        if t.stock_qty is not None:
            fields[field_id["stock"]] = int(t.stock_qty)
        if t.catalog_price is not None:
            fields[field_id["price"]] = float(t.catalog_price)
        out.append(fields)
    return out


# Field IDs for `Monthly Top Sellers` (tblptYd9f06LUdRMp). Captured at table
# creation time — see scripts/_setup_airtable_monthly_table for context.
# If the table is recreated, regenerate from list_tables_for_base.
_FIELD_ID = {
    "code":         "fldpxBkuBaEpm4kvh",
    "period":       "fldFx8f56LiVO7g9i",
    "rank":         "fldQSqdh26nm7zX6w",
    "name":         "fld9pOuapLNI7FyP8",
    "qty":          "fldvD6JlsthuFs1kc",
    "revenue":      "fldsx8hymunj6ldh7",
    "avg_unit":     "fldIsh9Yn2YVldXTm",
    "days":         "fldVSNgEHf3J6tlnL",
    "tx":           "fldUfIVSlgbruBUX1",
    "co":           "fldCmm7G60U0txV7q",
    "stock":        "fldYTIaeN93eRC6Zj",
    "price":        "fld3X2yvQFB40VFQ6",
    "last":         "flds1xDObrmED4Wks",
    "trend":        "fldWwfKrhi1qii0Km",
    "insight":      "fldHfbpctWXBudEda",
    "imported_at":  "fldBrozzEd28axTxT",
}


# ─── Commands ───────────────────────────────────────────────────────────────


@router.message(Command("import_sales"))
async def cmd_import_sales(message: Message, state: FSMContext) -> None:
    """Kick off the import flow. Resets any prior state."""
    await state.clear()
    await state.set_state(Importing.waiting_for_zip)
    await message.answer(messages.IMPORT_SALES_PROMPT)


@router.message(Command("cancel"), Importing.waiting_for_zip)
@router.message(Command("cancel"), Importing.confirming)
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await _cleanup_state(state)
    await message.answer(messages.IMPORT_SALES_CANCELLED)


# ─── ZIP reception ──────────────────────────────────────────────────────────


@router.message(Importing.waiting_for_zip, F.document)
async def receive_zip(message: Message, state: FSMContext) -> None:
    doc = message.document
    fname = (doc.file_name or "").lower()
    if not fname.endswith(".zip"):
        await message.answer(messages.IMPORT_SALES_NEED_ZIP)
        return

    placeholder = await message.answer(messages.IMPORT_SALES_DOWNLOADING)
    session_dir = _new_session_dir(message.chat.id)
    zip_path = session_dir / "upload.zip"

    try:
        file_info = await message.bot.get_file(doc.file_id)
        await message.bot.download_file(file_info.file_path, destination=zip_path)
    except Exception as e:
        log.exception("import_sales_download_failed")
        await placeholder.edit_text(
            messages.IMPORT_SALES_DOWNLOAD_FAILED.format(error=str(e))
        )
        shutil.rmtree(session_dir, ignore_errors=True)
        await state.clear()
        return

    try:
        await placeholder.edit_text(messages.IMPORT_SALES_PARSING)
    except Exception:
        pass

    # Heavy CPU work in a thread so the event loop stays responsive.
    extract_dir = session_dir / "extracted"
    parsed = await asyncio.to_thread(
        lambda: list(sales_importer.parse_zip(zip_path, extract_to=extract_dir))
    )

    if not parsed:
        await placeholder.edit_text(messages.IMPORT_SALES_NO_DATA)
        shutil.rmtree(session_dir, ignore_errors=True)
        await state.clear()
        return

    months = sorted({(r.sold_at.year, r.sold_at.month) for r in parsed})
    if len(months) > 1:
        # Mixed-month ZIP — let the founder pick the dominant one (the one
        # with the most rows). Other rows still go into the DB on commit
        # but won't be aggregated into the Top-15 push.
        month_counts = {}
        for r in parsed:
            key = (r.sold_at.year, r.sold_at.month)
            month_counts[key] = month_counts.get(key, 0) + 1
        dominant = max(month_counts.items(), key=lambda kv: kv[1])[0]
        warning = messages.IMPORT_SALES_MIXED_MONTHS.format(
            count=len(months),
            dominant=_period_label(*dominant),
        )
    else:
        dominant = months[0]
        warning = ""

    summary = sales_importer.summarize(parsed)
    preview = messages.IMPORT_SALES_PREVIEW.format(
        period=_period_label(*dominant),
        files=summary["files"],
        rows=summary["row_count"],
        revenue=summary["revenue"],
        unique=summary["unique_codes"],
        unknown=(f"⚠️ უცნობი კოდი: {len(summary['unknown_codes'])}"
                 if summary["unknown_codes"] else "✅ ყველა კოდი ცნობილია"),
        date_range=f"{summary['date_min']} → {summary['date_max']}",
        warning=warning,
    )

    await state.update_data(
        session_dir=str(session_dir),
        year=dominant[0],
        month=dominant[1],
    )
    await state.set_state(Importing.confirming)
    try:
        await placeholder.edit_text(
            preview, reply_markup=_build_confirm_kb().as_markup()
        )
    except Exception:
        await message.answer(
            preview, reply_markup=_build_confirm_kb().as_markup()
        )


@router.message(Importing.waiting_for_zip)
async def handle_non_doc(message: Message) -> None:
    """If the founder sends text or a non-document while we're waiting."""
    await message.answer(messages.IMPORT_SALES_NEED_ZIP)


# ─── Confirmation flow ──────────────────────────────────────────────────────


@router.callback_query(Importing.confirming, F.data == "import_sales:cancel")
async def confirm_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await _cleanup_state(state)
    await callback.answer()
    if callback.message:
        try:
            await callback.message.edit_text(messages.IMPORT_SALES_CANCELLED)
        except Exception:
            pass


@router.callback_query(Importing.confirming, F.data == "import_sales:confirm")
async def confirm_import(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    session_dir = Path(data["session_dir"])
    year = int(data["year"])
    month = int(data["month"])

    msg = callback.message
    try:
        await msg.edit_text(messages.IMPORT_SALES_WORKING)
    except Exception:
        pass

    try:
        result = await asyncio.to_thread(
            _do_import_and_push, session_dir, year, month
        )
    except Exception as e:
        log.exception("import_sales_commit_failed")
        await msg.answer(messages.IMPORT_SALES_COMMIT_FAILED.format(error=str(e)))
        await _cleanup_state(state)
        return

    text = messages.IMPORT_SALES_DONE.format(
        period=_period_label(year, month),
        inserted=result["inserted"],
        deleted=result["deleted"],
        airtable_status=result["airtable_status"],
        airtable_url=result["airtable_url"],
        top_summary=result["top_summary"],
    )
    try:
        await msg.edit_text(text, disable_web_page_preview=True)
    except Exception:
        await msg.answer(text, disable_web_page_preview=True)
    await _cleanup_state(state)


# ─── Core commit + push (runs in a thread) ──────────────────────────────────


def _do_import_and_push(
    session_dir: Path, year: int, month: int
) -> dict:
    """Re-parse from the extracted dir, write DB, push Airtable. Pure sync."""
    extract_dir = session_dir / "extracted"
    parsed_all = list(sales_importer.parse_directory(extract_dir))
    parsed_month = sales_importer.filter_by_period(parsed_all, year, month)

    # Idempotent commit: wipe + insert only the rows for THIS month range.
    start, end = sales_importer.month_bounds(year, month)
    inserted, deleted = sales_importer.commit_sales(
        parsed_month, wipe_period=(start, end),
    )

    # Aggregate top-15 for the month.
    top = demand_analysis.analyze_month(year, month, top_n=15)

    # Build Airtable summary text whether or not we manage to push.
    top_summary_lines = []
    for t in top[:5]:
        top_summary_lines.append(
            f"  {t.rank}. `{t.code}` qty={int(t.qty)} rev={t.revenue:.0f}₾  {t.trend_tag}"
        )
    top_summary = "\n".join(top_summary_lines) or "(ცარიელია)"

    airtable_status = "—"
    airtable_url = ""

    try:
        client = airtable_from_config()
    except RuntimeError as e:
        airtable_status = f"⚠️ Airtable არ გადაიგზავნა: {e}"
        return {
            "inserted": inserted, "deleted": deleted,
            "airtable_status": airtable_status, "airtable_url": "",
            "top_summary": top_summary,
        }

    cfg = config.load()
    period = _period_label(year, month)

    try:
        # Idempotent: remove any prior rows for this Period first.
        existing = client.list_records(
            cfg.airtable_monthly_table_id,
            filter_by_formula=f"{{Period}}='{period}'",
            max_records=200,
        )
        if existing:
            client.delete_records(
                cfg.airtable_monthly_table_id,
                [r["id"] for r in existing],
            )

        records = _build_airtable_records(
            top,
            period=period,
            imported_at_iso=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            field_id=_FIELD_ID,
        )
        created = client.create_records(
            cfg.airtable_monthly_table_id, records,
        )
        airtable_status = f"✅ Airtable: {len(created)} row ჩაიწერა"
        airtable_url = (
            f"https://airtable.com/{cfg.airtable_base_id}/"
            f"{cfg.airtable_monthly_table_id}"
        )
    except AirtableError as e:
        log.exception("airtable_push_failed")
        airtable_status = f"⚠️ Airtable შეცდომა ({e.status_code}): {e.body}"
    except Exception as e:
        log.exception("airtable_push_failed_other")
        airtable_status = f"⚠️ Airtable შეცდომა: {e}"

    return {
        "inserted": inserted, "deleted": deleted,
        "airtable_status": airtable_status, "airtable_url": airtable_url,
        "top_summary": top_summary,
    }


# ─── Cleanup ────────────────────────────────────────────────────────────────


async def _cleanup_state(state: FSMContext) -> None:
    data = await state.get_data()
    session_dir = data.get("session_dir")
    if session_dir:
        shutil.rmtree(Path(session_dir), ignore_errors=True)
    await state.clear()
