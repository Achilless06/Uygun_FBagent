"""Telegram admin handlers — all founder-facing commands and interactions.

Layout mirrors the brandbook's admin-panel sections (p. 18) and adds modern
interactive elements:

  /menu       · main inline-keyboard menu (also: tap any "🏠 მთავარი მენიუ" button)
  /dashboard  · stats overview with visual progress bars
  /products   · paginated list; tap any product → full detail card
  /inventory  · out-of-stock list with quick-toggle buttons
  /categories · grouped browser; tap a category → paginated products
  /search Q   · case-insensitive substring search on name + code
  /settings   · view + edit runtime settings (gen/publish time, budget, active)
  /spend      · API spend with progress bar (real impl in Phase 8)
  /toggle_stock CODE  · flip a product between in/out of stock
  /reimport   · re-run catalog importer

Inline keyboards use callback_data with a 2- or 3-segment scheme:
  "menu:dashboard"       → router to dashboard
  "products:page:5"      → products list, page 5
  "prod:view:42"         → product detail card for code 42
  "prod:toggle:42"       → flip stock, then refresh detail card
  "inv:page:3"           → inventory list, page 3
  "inv:toggle:42"        → flip stock, then refresh inventory list
  "cat:list"             → categories index
  "cat:view:საბურავის:2" → category drilldown, page 2
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func as sqlfunc
from sqlalchemy import or_

from src import config, db
from src.ai.advisor import Advisor
from src.ai.claude_client import ClaudeClient
from src.catalog import importer as catalog_importer
from src.logging_setup import get_logger
from src.telegram_bot import messages

# Advisor is initialized lazily on first /tips request so that startup doesn't
# require Anthropic credentials to be valid.
_advisor: Advisor | None = None


def _get_advisor() -> Advisor:
    global _advisor
    if _advisor is None:
        cfg = config.load()
        _advisor = Advisor(ClaudeClient(cfg))
    return _advisor

log = get_logger(__name__)
router = Router()

PRODUCTS_PER_PAGE = 10
INVENTORY_PER_PAGE = 10
SEARCH_RESULTS_LIMIT = 25
CATEGORIES_LIMIT = 30
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

# Search synonyms: Georgian root → list of equivalents that may appear in the
# product names (which are mostly in English/Turkish for imported brands).
# Matched by substring on the query (lowercased), so "ცემენტი" hits "ცემენტ"
# in this map and we OR-search for all its synonyms.
SEARCH_SYNONYMS: dict[str, list[str]] = {
    "ცემენტ": ["cement", "valcarn", "solusyon"],
    "ლატკ": ["yama"],
    "წებო": ["cement", "valcarn", "solusyon", "yapistirici", "glue"],
    "ფურცელ": ["tabaka"],
    "ფირფიტ": ["yama", "plate"],
    "კომპრესორ": ["aero", "compressor"],
    "დომკრატ": ["lift", "jack", "column"],
    "სარქველ": ["valve", "supap"],
    "ქანჩ": ["nut", "somun"],
    "რეზინ": ["rubber"],
    "ჰაერ": ["air", "hava"],
    "ზეთ": ["oil", "yag"],
    "ცომი": ["dough", "lehim"],
}


def _expand_search_terms(query: str) -> list[str]:
    """Return a list of terms to search for, given a Georgian or Latin query.

    Always includes the original query. If the query (lowercased) contains any
    of the Georgian roots in SEARCH_SYNONYMS, the synonyms are added too.
    """
    terms = [query.strip()]
    q_lower = query.lower()
    for root, synonyms in SEARCH_SYNONYMS.items():
        if root in q_lower or q_lower in root:
            terms.extend(synonyms)
    # De-dupe while preserving order.
    seen, out = set(), []
    for t in terms:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out

# Visual bar: 10 segments. Unicode blocks render the same width in monospace
# on every platform Telegram targets.
BAR_SEGMENTS = 10
BAR_FILLED = "▓"
BAR_EMPTY = "░"


# ─── Generic helpers ─────────────────────────────────────────────────────────


def _md_escape(text: str | None) -> str:
    """Escape characters that Telegram's Markdown mode treats as formatting."""
    if text is None:
        return ""
    return (
        text.replace("\\", "\\\\")
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("`", "\\`")
        .replace("[", "\\[")
    )


def _stock_icon(stock_qty: int) -> str:
    return messages.STOCK_IN if stock_qty > 0 else messages.STOCK_OUT


def _format_price(price: float | None) -> str:
    if price is None or price == 0:
        return "—"
    if price == int(price):
        return f"{int(price)} ლარი"
    return f"{price:g} ლარი"


def _progress_bar(pct: float) -> str:
    """Render a 10-segment progress bar for a 0-100% value."""
    pct = max(0.0, min(100.0, pct))
    filled = round(pct / 100 * BAR_SEGMENTS)
    return f"`{BAR_FILLED * filled}{BAR_EMPTY * (BAR_SEGMENTS - filled)}`"


def _pct(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return round(numerator / denominator * 100)


async def _send_or_edit(
    event: Message | CallbackQuery, text: str, reply_markup=None
) -> None:
    """Edit the message in place for callback updates; send fresh for commands."""
    if isinstance(event, CallbackQuery):
        if event.message:
            try:
                await event.message.edit_text(text, reply_markup=reply_markup)
            except Exception:
                # edit_text fails if the new content is identical or older than 48h;
                # fall back to sending a new message.
                await event.message.answer(text, reply_markup=reply_markup)
        await event.answer()
    else:
        await event.answer(text, reply_markup=reply_markup)


# ─── Main menu ───────────────────────────────────────────────────────────────


def _main_menu_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    # Generate first now — it's the daily workhorse.
    kb.button(text=messages.BTN_MENU_GENERATE, callback_data="menu:generate")
    kb.button(text=messages.BTN_MENU_CHAT, callback_data="menu:chat")
    kb.button(text=messages.BTN_MENU_TIPS, callback_data="menu:tips")
    kb.button(text=messages.BTN_MENU_SALES, callback_data="menu:sales")
    kb.button(text=messages.BTN_MENU_MEMORIES, callback_data="menu:memories")
    kb.button(text=messages.BTN_MENU_DASHBOARD, callback_data="menu:dashboard")
    kb.button(text=messages.BTN_MENU_PRODUCTS, callback_data="menu:products")
    kb.button(text=messages.BTN_MENU_INVENTORY, callback_data="menu:inventory")
    kb.button(text=messages.BTN_MENU_SEARCH, callback_data="menu:search")
    kb.button(text=messages.BTN_MENU_CATEGORIES, callback_data="menu:categories")
    kb.button(text=messages.BTN_MENU_SETTINGS, callback_data="menu:settings")
    kb.button(text=messages.BTN_MENU_SPEND, callback_data="menu:spend")
    kb.button(text=messages.BTN_MENU_HELP, callback_data="menu:help")
    kb.adjust(2)
    return kb


def _build_main_menu_text() -> str:
    """Beautified main menu with live stats inline.

    Reads from DB on every call (cheap — a few aggregate queries).
    """
    with db.session_scope() as s:
        total_products = s.query(db.Product).count()
        in_stock = s.query(db.Product).filter(db.Product.stock_qty > 0).count()
        posts_published = s.query(db.Post).count()
        pending_drafts = s.query(db.PostDraft).filter(db.PostDraft.status == "pending").count()
        first_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        spend_rows = s.query(db.ApiSpend).filter(db.ApiSpend.occurred_at >= first_of_month).all()
        spent = sum(r.cost_usd for r in spend_rows)
        agent_active = db.get_setting("agent_active", "true") == "true"
        gen_time = db.get_setting("post_gen_time", "11:30")
        publish_time = db.get_setting("post_publish_time", "12:00")
        budget = float(db.get_setting("monthly_budget_usd", "20"))

    budget_pct = _pct(int(spent * 100), int(budget * 100)) if budget > 0 else 0
    status_icon = "🟢" if agent_active else "🔴"
    status_label = "აქტიური" if agent_active else "პაუზაში"
    agent_status_line = (
        f"{status_icon} *{status_label}* · გენ. `{gen_time}` · პუბ. `{publish_time}`"
    )
    return messages.MAIN_MENU.format(
        agent_status_line=agent_status_line,
        total_products=total_products,
        in_stock=in_stock,
        posts_published=posts_published,
        pending_drafts=pending_drafts,
        spent=spent,
        budget=budget,
        budget_pct=budget_pct,
    )


def _back_to_menu_kb(extra_buttons: list[InlineKeyboardButton] | None = None) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    if extra_buttons:
        for b in extra_buttons:
            kb.add(b)
    kb.button(text=messages.BTN_BACK_TO_MENU, callback_data="menu:home")
    if extra_buttons:
        # extra buttons on one row, menu button on its own
        kb.adjust(*([len(extra_buttons), 1]))
    return kb


@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    kb = _main_menu_keyboard()
    await message.answer(messages.WELCOME, reply_markup=kb.as_markup())


@router.message(Command("menu"))
async def handle_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    kb = _main_menu_keyboard()
    await message.answer(_build_main_menu_text(), reply_markup=kb.as_markup())


@router.callback_query(F.data == "menu:home")
async def handle_menu_home(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    kb = _main_menu_keyboard()
    await _send_or_edit(callback, _build_main_menu_text(), kb.as_markup())


@router.callback_query(F.data == "menu:help")
async def handle_menu_help(callback: CallbackQuery) -> None:
    kb = _back_to_menu_kb()
    await _send_or_edit(callback, messages.HELP, kb.as_markup())


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    kb = _back_to_menu_kb()
    await message.answer(messages.HELP, reply_markup=kb.as_markup())


# ─── Tips / Advisor ──────────────────────────────────────────────────────────


def _build_tips_message(force_refresh: bool = False) -> tuple[str, InlineKeyboardBuilder, bool]:
    """Returns (text, keyboard, was_fresh). was_fresh=True if we just hit Claude."""
    from datetime import date

    from src.ai.advisor import MONTHS_KA, WEEKDAYS_KA

    today = date.today()
    cached = db.get_setting(f"tips:{today.isoformat()}") is not None

    try:
        tips = _get_advisor().get_tips_for_today(force_refresh=force_refresh)
    except Exception:
        log.exception("advisor_failed")
        tips = []

    if not tips:
        kb = _back_to_menu_kb([
            InlineKeyboardButton(text=messages.BTN_TIPS_REFRESH, callback_data="tips:refresh")
        ])
        return messages.TIPS_EMPTY, kb, False

    header = messages.TIPS_HEADER.format(
        date_human=f"{today.day} {MONTHS_KA[today.month - 1]} {today.year}",
        weekday=WEEKDAYS_KA[today.weekday()],
    )
    body = header
    for tip in tips:
        body += messages.TIPS_TIP_TEMPLATE.format(
            icon=tip.icon,
            title=_md_escape(tip.title),
            body=_md_escape(tip.body),
        )

    if cached and not force_refresh:
        body += messages.TIPS_CACHED_NOTE
    body += messages.TIPS_FOOTER

    kb = _back_to_menu_kb([
        InlineKeyboardButton(text=messages.BTN_TIPS_REFRESH, callback_data="tips:refresh")
    ])
    return body, kb, force_refresh or not cached


@router.message(Command("tips"))
async def handle_tips(message: Message) -> None:
    # Send "thinking" placeholder if we'll actually hit Claude (no cache yet).
    cached = db.get_setting(f"tips:{date.today().isoformat()}") is not None
    placeholder: Message | None = None
    if not cached:
        placeholder = await message.answer(messages.TIPS_LOADING)
    text, kb, _ = _build_tips_message()
    if placeholder is not None:
        try:
            await placeholder.edit_text(text, reply_markup=kb.as_markup())
            return
        except Exception:
            pass
    await message.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data == "menu:tips")
async def handle_menu_tips(callback: CallbackQuery) -> None:
    cached = db.get_setting(f"tips:{date.today().isoformat()}") is not None
    if not cached and callback.message:
        # Edit current message to loading state while Claude churns.
        try:
            await callback.message.edit_text(messages.TIPS_LOADING)
        except Exception:
            pass
    text, kb, _ = _build_tips_message()
    await _send_or_edit(callback, text, kb.as_markup())


@router.callback_query(F.data == "tips:refresh")
async def handle_tips_refresh(callback: CallbackQuery) -> None:
    if callback.message:
        try:
            await callback.message.edit_text(messages.TIPS_LOADING)
        except Exception:
            pass
    text, kb, _ = _build_tips_message(force_refresh=True)
    await _send_or_edit(callback, text, kb.as_markup())


# ─── Draft cleanup ───────────────────────────────────────────────────────────


@router.message(Command("cleanup_drafts"))
async def handle_cleanup_drafts(message: Message) -> None:
    """Delete all drafts that never got published (pending/edited/rejected).

    Published drafts (status=published) are kept — they're the historical record
    paired with `posts` rows that point at real Facebook content.
    """
    with db.session_scope() as s:
        rows_to_delete = s.query(db.PostDraft).filter(
            db.PostDraft.status.in_(("pending", "edited", "rejected"))
        )
        count = rows_to_delete.count()
        if count == 0:
            await message.answer(messages.CLEANUP_DRAFTS_EMPTY)
            return
        rows_to_delete.delete(synchronize_session=False)
    log.info("cleanup_drafts", deleted=count)
    await message.answer(messages.CLEANUP_DRAFTS_DONE.format(count=count))


# ─── Photo cache refresh ─────────────────────────────────────────────────────


@router.message(Command("refind_photo"))
async def handle_refind_photo(message: Message, command: CommandObject) -> None:
    """Clear cached photo for a product code and search again.

    Useful when the auto-found photo was the wrong product (e.g. construction
    cement vs rubber cement). Forces a fresh search on the next /generate.
    """
    import asyncio

    from src import config as cfg_mod
    from src.ai import generator

    if not command.args:
        await message.answer(messages.REFIND_PHOTO_USAGE)
        return

    code = command.args.strip()
    with db.session_scope() as s:
        product = s.get(db.Product, code)
        if product is None:
            await message.answer(messages.REFIND_PHOTO_NOT_FOUND.format(code=_md_escape(code)))
            return
        name = product.name
        price = product.price

    # Clear both caches: raw download + overlaid output. Both regenerate.
    raw_path = cfg_mod.DATA_DIR / "found_photos" / f"{code}.jpg"
    overlay_path = cfg_mod.DATA_DIR / "overlaid_photos" / f"{code}.jpg"
    for p in (raw_path, overlay_path):
        if p.exists():
            p.unlink()

    placeholder = await message.answer(
        messages.REFIND_PHOTO_SEARCHING.format(code=_md_escape(code), name=_md_escape(name))
    )

    def _refind():
        return generator.find_and_overlay_photo(product_code=code, product_name=name, price=price)

    result = await asyncio.to_thread(_refind)
    if result:
        await placeholder.edit_text(messages.REFIND_PHOTO_SUCCESS.format(
            code=_md_escape(code), name=_md_escape(name)
        ))
    else:
        await placeholder.edit_text(messages.REFIND_PHOTO_FAILED.format(code=_md_escape(code)))


# ─── Scheduler controls ──────────────────────────────────────────────────────


@router.message(Command("scheduler"))
async def handle_scheduler_status(message: Message) -> None:
    """Show whether the auto-scheduler is wired + the next run time."""
    from src import scheduler as scheduler_module
    s = scheduler_module.get()
    if s is None:
        await message.answer("⚠️ Scheduler not initialized (bot in degraded mode).")
        return
    next_run = s._next_run_time_str()
    agent_active = db.get_setting("agent_active", "true")
    status_icon = "🟢" if agent_active == "true" else "🔴"
    text = (
        f"⏰ *ავტო-სქედულერი*\n\n"
        f"{status_icon} აგენტი: `{agent_active}`\n"
        f"🕐 გენერაცია: `{db.get_setting('post_gen_time', '11:30')}` ({db.get_setting('post_publish_time', '12:00')}-ზე ვაქვეყნებთ ✅-ის შემდეგ)\n"
        f"➡️ შემდეგი გაშვება: `{_md_escape(next_run)}`\n\n"
        f"_ცვლილებებისთვის: /set\\_gen\\_time HH:MM ან /set\\_active true|false_"
    )
    await message.answer(text)


@router.message(Command("test_schedule"))
async def handle_test_schedule(message: Message) -> None:
    """Manually trigger the daily-generation job right now — useful for testing."""
    from src import scheduler as scheduler_module
    s = scheduler_module.get()
    if s is None:
        await message.answer("⚠️ Scheduler not initialized.")
        return
    await message.answer("⏰ ვუშვებ ავტო-გენერაციის ჯობს ხელით…")
    await s.run_now()


# ─── Facebook credential test ────────────────────────────────────────────────


@router.message(Command("test_fb"))
async def handle_test_fb(message: Message) -> None:
    """Hit Meta /me with the configured token to confirm it works.

    Use this BEFORE you flip DRY_RUN=false and approve a real post — if the
    token is wrong/short-lived/missing scopes, this tells you exactly what's
    wrong without burning a draft.
    """
    import asyncio

    from src.facebook import publisher as fb_pub

    placeholder = await message.answer("🔎 _ვამოწმებ Meta token-ს…_")

    def _verify():
        return fb_pub.verify_credentials()

    try:
        info = await asyncio.to_thread(_verify)
    except fb_pub.FacebookCredentialsMissing:
        try:
            await placeholder.edit_text(messages.FB_TEST_NO_CREDS)
        except Exception:
            await message.answer(messages.FB_TEST_NO_CREDS)
        return
    except fb_pub.FacebookPublishError as e:
        try:
            await placeholder.edit_text(messages.FB_TEST_FAILED.format(error=_md_escape(str(e))))
        except Exception:
            await message.answer(messages.FB_TEST_FAILED.format(error=_md_escape(str(e))))
        return
    except Exception as e:
        try:
            await placeholder.edit_text(messages.FB_TEST_FAILED.format(error=_md_escape(str(e))))
        except Exception:
            pass
        return

    text = messages.FB_TEST_OK.format(
        name=_md_escape(info.get("name", "?")),
        id=_md_escape(info.get("id", "?")),
        category=_md_escape(info.get("category", "?")),
    )
    try:
        await placeholder.edit_text(text)
    except Exception:
        await message.answer(text)


# ─── Post Generation ─────────────────────────────────────────────────────────

VALID_SLOTS = {"B2B", "B2C", "EDU", "BTS", "LITE", "Promo"}


async def _run_generate_and_preview(
    chat_id: int, bot, slot: str | None, placeholder_msg=None
) -> None:
    """Generate a draft + send the preview. Used by /generate and menu:generate."""
    import asyncio

    from src.ai import generator as gen_module
    from src.telegram_bot import approval

    def _gen() -> gen_module.GeneratedPost:
        return gen_module.generate_draft_for_slot(slot=slot)

    try:
        post = await asyncio.to_thread(_gen)
    except Exception:
        log.exception("generate_failed")
        if placeholder_msg:
            try:
                await placeholder_msg.edit_text(messages.GENERATE_FAILED)
            except Exception:
                pass
        else:
            await bot.send_message(chat_id, messages.GENERATE_FAILED)
        return

    draft_id = approval._persist_draft(post)
    if placeholder_msg:
        try:
            await placeholder_msg.delete()
        except Exception:
            pass
    await approval.send_preview(bot, chat_id, post, draft_id)


@router.message(Command("generate"))
async def handle_generate(message: Message, command: CommandObject) -> None:
    slot: str | None = None
    if command.args:
        candidate = command.args.strip()
        if candidate not in VALID_SLOTS:
            await message.answer(messages.GENERATE_INVALID_SLOT)
            return
        slot = candidate
    placeholder = await message.answer(messages.GENERATE_LOADING)
    await _run_generate_and_preview(
        message.chat.id, message.bot, slot, placeholder_msg=placeholder
    )


@router.callback_query(F.data == "menu:generate")
async def handle_menu_generate(callback: CallbackQuery) -> None:
    if callback.message:
        try:
            placeholder = await callback.message.answer(messages.GENERATE_LOADING)
        except Exception:
            placeholder = None
    else:
        placeholder = None
    await callback.answer()
    await _run_generate_and_preview(
        callback.from_user.id, callback.bot, None, placeholder_msg=placeholder
    )


# ─── Chat intro / Memory commands ────────────────────────────────────────────


@router.callback_query(F.data == "menu:chat")
async def handle_menu_chat(callback: CallbackQuery) -> None:
    kb = _back_to_menu_kb()
    await _send_or_edit(callback, messages.CHAT_INTRO, kb.as_markup())


@router.message(Command("remember"))
async def handle_remember(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer(messages.MEMORY_USAGE)
        return
    content = command.args.strip()
    mem_id = db.add_memory(content)
    log.info("memory_added", memory_id=mem_id, content_preview=content[:80])
    await message.answer(
        messages.MEMORY_ADDED.format(id=mem_id, content=_md_escape(content))
    )


def _build_memories_view() -> tuple[str, InlineKeyboardBuilder]:
    rows = db.list_memories(limit=50)
    if not rows:
        kb = _back_to_menu_kb()
        return messages.MEMORY_EMPTY, kb

    body = messages.MEMORY_LIST_HEADER.format(count=len(rows))
    for m in rows:
        body += messages.MEMORY_LIST_ROW.format(
            id=m.id,
            category=_md_escape(m.category or "preference"),
            content=_md_escape(m.content),
        )
    body += "\n_წასაშლელად: `/forget id`_"

    kb = _back_to_menu_kb()
    return body, kb


@router.message(Command("memories"))
async def handle_memories(message: Message) -> None:
    body, kb = _build_memories_view()
    await message.answer(body, reply_markup=kb.as_markup())


@router.callback_query(F.data == "menu:memories")
async def handle_menu_memories(callback: CallbackQuery) -> None:
    body, kb = _build_memories_view()
    await _send_or_edit(callback, body, kb.as_markup())


@router.message(Command("forget"))
async def handle_forget(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer(messages.MEMORY_FORGET_USAGE)
        return
    try:
        mem_id = int(command.args.strip())
    except ValueError:
        await message.answer(messages.MEMORY_FORGET_USAGE)
        return
    ok = db.delete_memory(mem_id)
    if ok:
        log.info("memory_deleted", memory_id=mem_id)
        await message.answer(messages.MEMORY_FORGET_OK.format(id=mem_id))
    else:
        await message.answer(messages.MEMORY_FORGET_NOT_FOUND.format(id=mem_id))


@router.message(Command("forget_chat"))
async def handle_forget_chat(message: Message) -> None:
    count = db.clear_conversation()
    log.info("conversation_cleared", count=count)
    await message.answer(messages.CHAT_CLEARED.format(count=count))


# ─── Sales / Bookkeeping ─────────────────────────────────────────────────────


class NewSale(StatesGroup):
    """3-step FSM for guided new-sale entry from the menu."""
    code = State()
    qty = State()
    price = State()


class EditSale(StatesGroup):
    """Single-state FSM for editing one field of an existing sale.

    State data carries: sale_id (int), field ("qty"|"price"|"notes").
    """
    waiting_value = State()


def _start_of_today() -> datetime:
    now = datetime.utcnow()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_month() -> datetime:
    now = datetime.utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _format_when(dt: datetime) -> str:
    """Compact relative timestamp for the recent-sales list."""
    delta = datetime.utcnow() - dt
    if delta.days >= 1:
        return f"{delta.days} დღის წინ"
    hours = delta.seconds // 3600
    if hours >= 1:
        return f"{hours} სთ წინ"
    minutes = delta.seconds // 60
    if minutes >= 1:
        return f"{minutes} წთ წინ"
    return "ახლა"


def _build_sales_hub() -> tuple[str, InlineKeyboardBuilder]:
    today_summary = db.sales_summary(_start_of_today())
    month_summary = db.sales_summary(_start_of_month())
    text = messages.SALES_HUB.format(
        today_count=today_summary["count"],
        today_revenue=today_summary["total_revenue"],
        month_count=month_summary["count"],
        month_revenue=month_summary["total_revenue"],
    )
    kb = InlineKeyboardBuilder()
    kb.button(text=messages.BTN_SALES_NEW, callback_data="sales:new")
    kb.button(text=messages.BTN_SALES_RECENT, callback_data="sales:recent")
    kb.button(text=messages.BTN_SALES_SUMMARY, callback_data="sales:summary")
    kb.button(text=messages.BTN_BACK_TO_MENU, callback_data="menu:home")
    kb.adjust(2, 1, 1)
    return text, kb


@router.message(Command("sales"))
async def handle_sales(message: Message) -> None:
    text, kb = _build_sales_hub()
    await message.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data == "menu:sales")
async def handle_menu_sales(callback: CallbackQuery) -> None:
    text, kb = _build_sales_hub()
    await _send_or_edit(callback, text, kb.as_markup())


# ── /sale one-liner ──

def _parse_sale_args(raw: str) -> tuple[str, float, float, str] | None:
    """Parse '/sale CODE QTY PRICE [NOTES...]'. Returns (code, qty, price, notes) or None."""
    parts = raw.strip().split(maxsplit=3)
    if len(parts) < 3:
        return None
    code, qty_str, price_str = parts[0], parts[1], parts[2]
    notes = parts[3] if len(parts) > 3 else ""
    try:
        qty = float(qty_str.replace(",", "."))
        price = float(price_str.replace(",", "."))
    except ValueError:
        return None
    if qty <= 0 or price < 0:
        return None
    return code, qty, price, notes


def _format_sale_recorded(sale_id: int, code: str, name: str, qty: float, unit_price: float, total: float) -> str:
    return messages.SALE_RECORDED.format(
        id=sale_id,
        code=_md_escape(code),
        name=_md_escape(name),
        qty=qty,
        unit_price=unit_price,
        total=total,
    )


@router.message(Command("sale"))
async def handle_sale(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer(messages.SALE_USAGE)
        return
    parsed = _parse_sale_args(command.args)
    if parsed is None:
        await message.answer(messages.SALE_INVALID_FORMAT)
        return
    code, qty, price, notes = parsed
    try:
        sale_id, name, total = db.add_sale(code, qty, price, notes or None)
    except ValueError:
        await message.answer(messages.SALE_PRODUCT_NOT_FOUND.format(code=_md_escape(code)))
        return
    log.info("sale_recorded", sale_id=sale_id, code=code, qty=qty, total=total)
    await message.answer(_format_sale_recorded(sale_id, code, name, qty, price, total))


# ── /sales (recent list) ──

def _build_recent_sales(limit: int = 20) -> tuple[str, InlineKeyboardBuilder]:
    rows = db.list_sales(limit=limit)
    if not rows:
        return messages.SALES_EMPTY, _back_to_menu_kb()
    body = messages.SALES_LIST_HEADER.format(count=len(rows))
    for r in rows:
        body += messages.SALES_LIST_ROW.format(
            id=r.id,
            code=_md_escape(r.product_code),
            qty=r.quantity,
            total=r.total_price,
            when=_format_when(r.sold_at),
        )
    body += "\n_ტაპი ID-ზე → დეტალები, რედაქტირება, წაშლა_"

    kb = InlineKeyboardBuilder()
    # One "view" button per sale, labeled with the sale id.
    for r in rows:
        kb.button(text=f"#{r.id}", callback_data=f"sale:view:{r.id}")
    kb.adjust(5)
    kb.button(text=messages.BTN_BACK_TO_MENU, callback_data="menu:home")
    return body, kb


@router.callback_query(F.data == "sales:recent")
async def handle_sales_recent(callback: CallbackQuery) -> None:
    body, kb = _build_recent_sales()
    await _send_or_edit(callback, body, kb.as_markup())


# ── /sales_summary ──

def _build_sales_summary() -> tuple[str, InlineKeyboardBuilder]:
    today = db.sales_summary(_start_of_today())
    month = db.sales_summary(_start_of_month())

    if month["top_products"]:
        top_block = messages.SALES_SUMMARY_TOP_HEADER
        for i, (code, name, qty, revenue) in enumerate(month["top_products"], 1):
            top_block += messages.SALES_SUMMARY_TOP_ROW.format(
                n=i,
                code=_md_escape(code),
                name=_md_escape(name[:35]),  # one line per row
                revenue=revenue,
                qty=qty,
            )
    else:
        top_block = messages.SALES_SUMMARY_NO_DATA

    text = messages.SALES_SUMMARY.format(
        today_count=today["count"],
        today_units=today["total_units"],
        today_revenue=today["total_revenue"],
        month_count=month["count"],
        month_units=month["total_units"],
        month_revenue=month["total_revenue"],
        top_block=top_block,
    )
    return text, _back_to_menu_kb()


@router.message(Command("sales_summary"))
async def handle_sales_summary(message: Message) -> None:
    text, kb = _build_sales_summary()
    await message.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data == "sales:summary")
async def handle_sales_summary_cb(callback: CallbackQuery) -> None:
    text, kb = _build_sales_summary()
    await _send_or_edit(callback, text, kb.as_markup())


# ── /undo_sale ──

@router.message(Command("undo_sale"))
async def handle_undo_sale(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer(messages.SALE_UNDO_USAGE)
        return
    try:
        sale_id = int(command.args.strip())
    except ValueError:
        await message.answer(messages.SALE_UNDO_USAGE)
        return
    ok = db.delete_sale(sale_id)
    if ok:
        log.info("sale_deleted", sale_id=sale_id)
        await message.answer(messages.SALE_UNDO_OK.format(id=sale_id))
    else:
        await message.answer(messages.SALE_UNDO_NOT_FOUND.format(id=sale_id))


# ── FSM-guided new sale ──

@router.callback_query(F.data == "sales:new")
async def fsm_new_sale_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(NewSale.code)
    if callback.message:
        try:
            await callback.message.edit_text(messages.SALE_FSM_ASK_CODE)
        except Exception:
            await callback.message.answer(messages.SALE_FSM_ASK_CODE)
    await callback.answer()


@router.message(Command("cancel"), NewSale.code)
@router.message(Command("cancel"), NewSale.qty)
@router.message(Command("cancel"), NewSale.price)
async def fsm_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(messages.SALE_FSM_CANCELLED)


@router.message(NewSale.code)
async def fsm_new_sale_code(message: Message, state: FSMContext) -> None:
    code = (message.text or "").strip()
    with db.session_scope() as s:
        product = s.get(db.Product, code)
        if product is None:
            await message.answer(messages.SALE_PRODUCT_NOT_FOUND.format(code=_md_escape(code)))
            return
        name = product.name
    await state.update_data(code=code, name=name)
    await state.set_state(NewSale.qty)
    await message.answer(
        messages.SALE_FSM_ASK_QTY.format(code=_md_escape(code), name=_md_escape(name))
    )


@router.message(NewSale.qty)
async def fsm_new_sale_qty(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip().replace(",", ".")
    try:
        qty = float(raw)
    except ValueError:
        await message.answer(messages.SALE_INVALID_NUMBER)
        return
    if qty <= 0:
        await message.answer(messages.SALE_INVALID_NUMBER)
        return
    data = await state.get_data()
    await state.update_data(qty=qty)
    await state.set_state(NewSale.price)
    await message.answer(
        messages.SALE_FSM_ASK_PRICE.format(
            code=_md_escape(data["code"]), name=_md_escape(data["name"]), qty=qty
        )
    )


@router.message(NewSale.price)
async def fsm_new_sale_price(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip().replace(",", ".")
    try:
        price = float(raw)
    except ValueError:
        await message.answer(messages.SALE_INVALID_NUMBER)
        return
    if price < 0:
        await message.answer(messages.SALE_INVALID_NUMBER)
        return
    data = await state.get_data()
    code, name, qty = data["code"], data["name"], data["qty"]
    try:
        sale_id, _, total = db.add_sale(code, qty, price)
    except ValueError:
        await message.answer(messages.SALE_PRODUCT_NOT_FOUND.format(code=_md_escape(code)))
        await state.clear()
        return
    log.info("sale_recorded_fsm", sale_id=sale_id, code=code, qty=qty, total=total)
    await state.clear()
    await message.answer(_format_sale_recorded(sale_id, code, name, qty, price, total))


# ── Sale detail view ──

def _build_sale_detail(sale_id: int) -> tuple[str, InlineKeyboardBuilder]:
    sale = db.get_sale(sale_id)
    if sale is None:
        kb = _back_to_menu_kb()
        return messages.SALE_UNDO_NOT_FOUND.format(id=sale_id), kb

    notes = (
        _md_escape(sale.notes) if sale.notes else messages.SALE_DETAIL_NO_NOTES
    )
    text = messages.SALE_DETAIL.format(
        id=sale.id,
        code=_md_escape(sale.product_code),
        name=_md_escape(sale.product_name),
        qty=sale.quantity,
        unit_price=sale.unit_price,
        total=sale.total_price,
        notes=notes,
        when=_format_when(sale.sold_at),
        timestamp=sale.sold_at.strftime("%Y-%m-%d %H:%M"),
    )
    kb = InlineKeyboardBuilder()
    kb.button(text=messages.BTN_SALE_EDIT, callback_data=f"sale:edit:{sale_id}")
    kb.button(text=messages.BTN_SALE_DELETE, callback_data=f"sale:delete:{sale_id}")
    kb.button(text=messages.BTN_BACK, callback_data="sales:recent")
    kb.button(text=messages.BTN_BACK_TO_MENU, callback_data="menu:home")
    kb.adjust(2, 2)
    return text, kb


@router.callback_query(F.data.startswith("sale:view:"))
async def handle_sale_view(callback: CallbackQuery) -> None:
    sale_id = int(callback.data.split(":")[-1])
    text, kb = _build_sale_detail(sale_id)
    await _send_or_edit(callback, text, kb.as_markup())


# ── Edit menu (which field?) ──

def _build_sale_edit_menu(sale_id: int) -> tuple[str, InlineKeyboardBuilder]:
    sale = db.get_sale(sale_id)
    if sale is None:
        kb = _back_to_menu_kb()
        return messages.SALE_UNDO_NOT_FOUND.format(id=sale_id), kb
    text = messages.SALE_EDIT_MENU.format(
        id=sale.id,
        code=_md_escape(sale.product_code),
        name=_md_escape(sale.product_name),
        qty=sale.quantity,
        unit_price=sale.unit_price,
        total=sale.total_price,
    )
    kb = InlineKeyboardBuilder()
    kb.button(text=messages.BTN_SALE_EDIT_QTY, callback_data=f"sale:edit_field:{sale_id}:qty")
    kb.button(text=messages.BTN_SALE_EDIT_PRICE, callback_data=f"sale:edit_field:{sale_id}:price")
    kb.button(text=messages.BTN_SALE_EDIT_NOTES, callback_data=f"sale:edit_field:{sale_id}:notes")
    kb.button(text=messages.BTN_BACK, callback_data=f"sale:view:{sale_id}")
    kb.adjust(2, 1, 1)
    return text, kb


@router.callback_query(F.data.startswith("sale:edit:"))
async def handle_sale_edit(callback: CallbackQuery) -> None:
    sale_id = int(callback.data.split(":")[-1])
    text, kb = _build_sale_edit_menu(sale_id)
    await _send_or_edit(callback, text, kb.as_markup())


# ── EditSale FSM: ask for the new value ──

@router.callback_query(F.data.startswith("sale:edit_field:"))
async def fsm_edit_sale_start(callback: CallbackQuery, state: FSMContext) -> None:
    # "sale:edit_field:{id}:{field}"
    parts = callback.data.split(":")
    sale_id = int(parts[2])
    field = parts[3]
    sale = db.get_sale(sale_id)
    if sale is None:
        await _send_or_edit(callback, messages.SALE_UNDO_NOT_FOUND.format(id=sale_id), _back_to_menu_kb().as_markup())
        return

    await state.set_state(EditSale.waiting_value)
    await state.update_data(sale_id=sale_id, field=field)

    if field == "qty":
        text = messages.SALE_EDIT_ASK_QTY.format(current=sale.quantity)
    elif field == "price":
        text = messages.SALE_EDIT_ASK_PRICE.format(current=sale.unit_price)
    else:  # notes
        current = _md_escape(sale.notes) if sale.notes else messages.SALE_DETAIL_NO_NOTES
        text = messages.SALE_EDIT_ASK_NOTES.format(current=current)

    if callback.message:
        try:
            await callback.message.edit_text(text)
        except Exception:
            await callback.message.answer(text)
    await callback.answer()


@router.message(Command("cancel"), EditSale.waiting_value)
async def fsm_edit_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(messages.SALE_FSM_CANCELLED)


@router.message(EditSale.waiting_value)
async def fsm_edit_sale_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    sale_id = data["sale_id"]
    field = data["field"]
    raw = (message.text or "").strip()

    kwargs: dict = {}
    if field == "qty":
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            await message.answer(messages.SALE_INVALID_NUMBER)
            return
        if value <= 0:
            await message.answer(messages.SALE_INVALID_NUMBER)
            return
        kwargs["quantity"] = value
    elif field == "price":
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            await message.answer(messages.SALE_INVALID_NUMBER)
            return
        if value < 0:
            await message.answer(messages.SALE_INVALID_NUMBER)
            return
        kwargs["unit_price"] = value
    else:  # notes
        kwargs["notes"] = "" if raw == "-" else raw

    updated = db.update_sale(sale_id, **kwargs)
    await state.clear()
    if updated is None:
        await message.answer(messages.SALE_UNDO_NOT_FOUND.format(id=sale_id))
        return
    log.info("sale_updated", sale_id=sale_id, field=field)
    text = messages.SALE_EDIT_DONE.format(
        id=updated.id,
        qty=updated.quantity,
        unit_price=updated.unit_price,
        total=updated.total_price,
    )
    # Also offer back navigation to the detail view.
    kb = InlineKeyboardBuilder()
    kb.button(text=messages.BTN_BACK, callback_data=f"sale:view:{sale_id}")
    kb.button(text=messages.BTN_BACK_TO_MENU, callback_data="menu:home")
    kb.adjust(2)
    await message.answer(text, reply_markup=kb.as_markup())


# ── Delete (with confirmation) ──

def _build_delete_confirm(sale_id: int) -> tuple[str, InlineKeyboardBuilder]:
    sale = db.get_sale(sale_id)
    if sale is None:
        kb = _back_to_menu_kb()
        return messages.SALE_UNDO_NOT_FOUND.format(id=sale_id), kb
    text = messages.SALE_DELETE_CONFIRM.format(
        id=sale.id,
        code=_md_escape(sale.product_code),
        name=_md_escape(sale.product_name),
        total=sale.total_price,
    )
    kb = InlineKeyboardBuilder()
    kb.button(text=messages.BTN_CONFIRM_DELETE, callback_data=f"sale:delete_yes:{sale_id}")
    kb.button(text=messages.BTN_CANCEL_DELETE, callback_data=f"sale:view:{sale_id}")
    kb.adjust(2)
    return text, kb


@router.callback_query(F.data.startswith("sale:delete:"))
async def handle_sale_delete(callback: CallbackQuery) -> None:
    sale_id = int(callback.data.split(":")[-1])
    text, kb = _build_delete_confirm(sale_id)
    await _send_or_edit(callback, text, kb.as_markup())


@router.callback_query(F.data.startswith("sale:delete_yes:"))
async def handle_sale_delete_confirm(callback: CallbackQuery) -> None:
    sale_id = int(callback.data.split(":")[-1])
    ok = db.delete_sale(sale_id)
    if ok:
        log.info("sale_deleted", sale_id=sale_id)
        text, kb = _build_recent_sales()
        # Prepend a success line so user sees what happened.
        text = messages.SALE_DELETED.format(id=sale_id) + "\n\n" + text
        await _send_or_edit(callback, text, kb.as_markup())
    else:
        await _send_or_edit(
            callback,
            messages.SALE_UNDO_NOT_FOUND.format(id=sale_id),
            _back_to_menu_kb().as_markup(),
        )


# ─── Dashboard ───────────────────────────────────────────────────────────────


def _build_dashboard() -> tuple[str, InlineKeyboardBuilder]:
    with db.session_scope() as s:
        total_products = s.query(db.Product).count()
        priced_products = s.query(db.Product).filter(db.Product.price.isnot(None)).count()
        with_photos = s.query(db.Product).filter(db.Product.has_photo.is_(True)).count()
        in_stock = s.query(db.Product).filter(db.Product.stock_qty > 0).count()

        posts_published = s.query(db.Post).count()
        week_ago = datetime.utcnow() - timedelta(days=7)
        posts_last_week = s.query(db.Post).filter(db.Post.published_at >= week_ago).count()
        pending_drafts = s.query(db.PostDraft).filter(db.PostDraft.status == "pending").count()

        first_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        spend_rows = s.query(db.ApiSpend).filter(db.ApiSpend.occurred_at >= first_of_month).all()
        spent = sum(r.cost_usd for r in spend_rows)

        agent_active = db.get_setting("agent_active", "true") == "true"
        gen_time = db.get_setting("post_gen_time", "11:30")
        publish_time = db.get_setting("post_publish_time", "12:00")
        budget = float(db.get_setting("monthly_budget_usd", "20"))

    priced_pct = _pct(priced_products, total_products)
    photos_pct = _pct(with_photos, total_products)
    stock_pct = _pct(in_stock, total_products)
    budget_pct = _pct(int(spent * 100), int(budget * 100)) if budget > 0 else 0

    text = messages.DASHBOARD.format(
        date=datetime.utcnow().strftime("%Y-%m-%d"),
        total_products=total_products,
        priced_bar=_progress_bar(priced_pct),
        priced_pct=priced_pct,
        photos_bar=_progress_bar(photos_pct),
        photos_pct=photos_pct,
        stock_bar=_progress_bar(stock_pct),
        stock_pct=stock_pct,
        posts_published=posts_published,
        posts_last_week=posts_last_week,
        pending_drafts=pending_drafts,
        agent_status="🟢" if agent_active else "🔴",
        gen_time=gen_time,
        publish_time=publish_time,
        budget_bar=_progress_bar(budget_pct),
        spent=spent,
        budget=budget,
        budget_pct=budget_pct,
    )
    kb = _back_to_menu_kb([InlineKeyboardButton(text=messages.BTN_REFRESH, callback_data="menu:dashboard")])
    return text, kb


@router.message(Command("dashboard"))
async def handle_dashboard(message: Message) -> None:
    text, kb = _build_dashboard()
    await message.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data == "menu:dashboard")
async def handle_menu_dashboard(callback: CallbackQuery) -> None:
    text, kb = _build_dashboard()
    await _send_or_edit(callback, text, kb.as_markup())


# ─── Products list (paginated) ───────────────────────────────────────────────


def _build_products_page(page: int) -> tuple[str, InlineKeyboardBuilder]:
    with db.session_scope() as s:
        total = s.query(db.Product).count()
        if total == 0:
            kb = _back_to_menu_kb()
            return messages.PRODUCTS_EMPTY, kb
        total_pages = max(1, math.ceil(total / PRODUCTS_PER_PAGE))
        page = max(1, min(page, total_pages))
        offset = (page - 1) * PRODUCTS_PER_PAGE
        rows = (
            s.query(db.Product)
            .order_by(db.Product.code_sort.asc().nullslast(), db.Product.code.asc())
            .offset(offset)
            .limit(PRODUCTS_PER_PAGE)
            .all()
        )
        body = messages.PRODUCTS_PAGE_HEADER.format(page=page, total_pages=total_pages, total=total) + "\n"
        for p in rows:
            body += messages.PRODUCTS_ROW.format(
                stock_icon=_stock_icon(p.stock_qty),
                code=_md_escape(p.code),
                name=_md_escape(p.name),
                price=_format_price(p.price),
            )
        body += messages.PRODUCTS_PAGE_FOOTER

    kb = InlineKeyboardBuilder()
    # One "view" button per product (compact: just the code).
    for p in rows:
        kb.button(text=p.code, callback_data=f"prod:view:{p.code}")
    kb.adjust(5)  # 5 product buttons per row

    # Navigation row.
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text=messages.BTN_PREV, callback_data=f"products:page:{page - 1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text=messages.BTN_NEXT, callback_data=f"products:page:{page + 1}"))
    if nav_row:
        for b in nav_row:
            kb.add(b)
        kb.adjust(5, len(nav_row), 1)

    kb.button(text=messages.BTN_BACK_TO_MENU, callback_data="menu:home")
    return body, kb


@router.message(Command("products"))
async def handle_products(message: Message) -> None:
    body, kb = _build_products_page(1)
    await message.answer(body, reply_markup=kb.as_markup())


@router.callback_query(F.data == "menu:products")
async def handle_menu_products(callback: CallbackQuery) -> None:
    body, kb = _build_products_page(1)
    await _send_or_edit(callback, body, kb.as_markup())


@router.callback_query(F.data.startswith("products:page:"))
async def handle_products_page(callback: CallbackQuery) -> None:
    page = int(callback.data.split(":")[-1])
    body, kb = _build_products_page(page)
    await _send_or_edit(callback, body, kb.as_markup())


# ─── Product detail card ─────────────────────────────────────────────────────


def _format_last_featured(dt: datetime | None) -> str:
    if dt is None:
        return messages.PRODUCT_LAST_FEATURED_NEVER
    days = (datetime.utcnow() - dt).days
    if days == 0:
        return "დღეს"
    if days == 1:
        return "გუშინ"
    return f"{days} დღის წინ"


def _build_product_detail(code: str, return_to: str = "menu:products") -> tuple[str, InlineKeyboardBuilder]:
    """Return the detail card + a keyboard. `return_to` is the back-target callback."""
    with db.session_scope() as s:
        product = s.get(db.Product, code)
        if product is None:
            kb = _back_to_menu_kb()
            return messages.PRODUCT_NOT_FOUND.format(code=_md_escape(code)), kb

        stock_label = (
            messages.PRODUCT_STOCK_IN_LABEL if product.stock_qty > 0 else messages.PRODUCT_STOCK_OUT_LABEL
        )
        photo_status = (
            messages.PRODUCT_PHOTO_YES.format(code=_md_escape(product.code))
            if product.has_photo
            else messages.PRODUCT_PHOTO_NO
        )
        text = messages.PRODUCT_DETAIL.format(
            code=_md_escape(product.code),
            name=_md_escape(product.name),
            price=_format_price(product.price),
            stock_label=stock_label,
            category=_md_escape(product.category) if product.category else "—",
            photo_status=photo_status,
            last_featured=_format_last_featured(product.last_featured_at),
        )

    kb = InlineKeyboardBuilder()
    kb.button(text=messages.BTN_TOGGLE_STOCK, callback_data=f"prod:toggle:{code}|{return_to}")
    kb.button(text=messages.BTN_BACK, callback_data=return_to)
    kb.button(text=messages.BTN_BACK_TO_MENU, callback_data="menu:home")
    kb.adjust(1, 2)
    return text, kb


@router.callback_query(F.data.startswith("prod:view:"))
async def handle_product_view(callback: CallbackQuery) -> None:
    code = callback.data.split(":", 2)[-1]
    text, kb = _build_product_detail(code)
    await _send_or_edit(callback, text, kb.as_markup())


@router.callback_query(F.data.startswith("prod:toggle:"))
async def handle_product_toggle(callback: CallbackQuery) -> None:
    # callback_data format: "prod:toggle:CODE|RETURN_TO"
    payload = callback.data.split(":", 2)[-1]
    if "|" in payload:
        code, return_to = payload.split("|", 1)
    else:
        code, return_to = payload, "menu:products"
    success, _ = _toggle_stock(code)
    text, kb = _build_product_detail(code, return_to=return_to)
    await _send_or_edit(callback, text, kb.as_markup())


# ─── Inventory ───────────────────────────────────────────────────────────────


def _build_inventory_page(page: int) -> tuple[str, InlineKeyboardBuilder]:
    with db.session_scope() as s:
        in_stock_count = s.query(db.Product).filter(db.Product.stock_qty > 0).count()
        oos_query = s.query(db.Product).filter(db.Product.stock_qty == 0).order_by(
            db.Product.code_sort.asc().nullslast(), db.Product.code.asc()
        )
        oos_total = oos_query.count()

        if oos_total == 0:
            header = (
                messages.INVENTORY_EMPTY
                + "\n\n"
                + messages.INVENTORY_HEADER_IN_STOCK.format(count=in_stock_count)
            )
            kb = _back_to_menu_kb()
            return header, kb

        total_pages = max(1, math.ceil(oos_total / INVENTORY_PER_PAGE))
        page = max(1, min(page, total_pages))
        offset = (page - 1) * INVENTORY_PER_PAGE
        rows = oos_query.offset(offset).limit(INVENTORY_PER_PAGE).all()

        body = messages.INVENTORY_HEADER_OUT.format(count=oos_total)
        body += messages.INVENTORY_HEADER_IN_STOCK.format(count=in_stock_count) + "\n"
        body += "*ამოწურული — გვერდი " + f"`{page}/{total_pages}`*\n\n"
        for p in rows:
            body += messages.INVENTORY_ROW.format(
                code=_md_escape(p.code), name=_md_escape(p.name)
            )

    kb = InlineKeyboardBuilder()
    # Quick-toggle buttons: tap a code to flip it back to in-stock.
    for p in rows:
        kb.button(text=f"🟢 {p.code}", callback_data=f"inv:toggle:{p.code}")
    kb.adjust(5)
    if page > 1:
        kb.button(text=messages.BTN_PREV, callback_data=f"inv:page:{page - 1}")
    if page < total_pages:
        kb.button(text=messages.BTN_NEXT, callback_data=f"inv:page:{page + 1}")
    kb.button(text=messages.BTN_BACK_TO_MENU, callback_data="menu:home")
    return body, kb


@router.message(Command("inventory"))
async def handle_inventory(message: Message) -> None:
    body, kb = _build_inventory_page(1)
    await message.answer(body, reply_markup=kb.as_markup())


@router.callback_query(F.data == "menu:inventory")
async def handle_menu_inventory(callback: CallbackQuery) -> None:
    body, kb = _build_inventory_page(1)
    await _send_or_edit(callback, body, kb.as_markup())


@router.callback_query(F.data.startswith("inv:page:"))
async def handle_inventory_page(callback: CallbackQuery) -> None:
    page = int(callback.data.split(":")[-1])
    body, kb = _build_inventory_page(page)
    await _send_or_edit(callback, body, kb.as_markup())


@router.callback_query(F.data.startswith("inv:toggle:"))
async def handle_inventory_toggle(callback: CallbackQuery) -> None:
    code = callback.data.split(":", 2)[-1]
    _toggle_stock(code)
    body, kb = _build_inventory_page(1)
    await _send_or_edit(callback, body, kb.as_markup())


# ─── Toggle stock (shared helper + command) ──────────────────────────────────


def _toggle_stock(code: str) -> tuple[bool, str]:
    """Flip stock_qty between 0 and 1. Returns (success, user_message)."""
    with db.session_scope() as s:
        product = s.get(db.Product, code)
        if product is None:
            return False, messages.TOGGLE_NOT_FOUND.format(code=_md_escape(code))
        if product.stock_qty > 0:
            product.stock_qty = 0
            template = messages.TOGGLE_NOW_OUT_OF_STOCK
        else:
            product.stock_qty = 1
            template = messages.TOGGLE_NOW_IN_STOCK
        msg = template.format(code=_md_escape(code), name=_md_escape(product.name))
        log.info("stock_toggled", code=code, new_qty=product.stock_qty, product_name=product.name)
        return True, msg


@router.message(Command("toggle_stock"))
async def handle_toggle_stock(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer(messages.TOGGLE_USAGE)
        return
    code = command.args.strip()
    _, response = _toggle_stock(code)
    await message.answer(response)


# ─── Search ──────────────────────────────────────────────────────────────────


def _build_search_results(query: str) -> tuple[str, InlineKeyboardBuilder]:
    terms = _expand_search_terms(query)
    with db.session_scope() as s:
        # OR-search across name + code for every expanded term.
        clauses = []
        for t in terms:
            needle = f"%{t}%"
            clauses.append(db.Product.name.ilike(needle))
            clauses.append(db.Product.code.ilike(needle))
        rows = (
            s.query(db.Product)
            .filter(or_(*clauses))
            .order_by(db.Product.code_sort.asc().nullslast(), db.Product.code.asc())
            .limit(SEARCH_RESULTS_LIMIT + 1)
            .all()
        )

    if not rows:
        kb = _back_to_menu_kb()
        return messages.SEARCH_EMPTY.format(query=_md_escape(query)), kb

    has_more = len(rows) > SEARCH_RESULTS_LIMIT
    visible = rows[:SEARCH_RESULTS_LIMIT]

    # Show synonyms used so the founder understands why these results appeared.
    if len(terms) > 1:
        synonym_note = f"_ასევე ვეძებთ: {', '.join(t for t in terms[1:])}_\n\n"
    else:
        synonym_note = ""

    body = messages.SEARCH_HEADER.format(query=_md_escape(query), count=len(visible)) + synonym_note
    for p in visible:
        body += messages.PRODUCTS_ROW.format(
            stock_icon=_stock_icon(p.stock_qty),
            code=_md_escape(p.code),
            name=_md_escape(p.name),
            price=_format_price(p.price),
        )
    if has_more:
        body += messages.SEARCH_TRUNCATED.format(hidden="ბევრი")

    kb = InlineKeyboardBuilder()
    for p in visible:
        kb.button(text=p.code, callback_data=f"prod:view:{p.code}")
    kb.adjust(5)
    kb.button(text=messages.BTN_BACK_TO_MENU, callback_data="menu:home")
    return body, kb


@router.message(Command("search"))
async def handle_search(message: Message, command: CommandObject) -> None:
    if not command.args:
        kb = _back_to_menu_kb()
        await message.answer(messages.SEARCH_USAGE, reply_markup=kb.as_markup())
        return
    body, kb = _build_search_results(command.args.strip())
    await message.answer(body, reply_markup=kb.as_markup())


@router.callback_query(F.data == "menu:search")
async def handle_menu_search(callback: CallbackQuery) -> None:
    kb = _back_to_menu_kb()
    await _send_or_edit(callback, messages.SEARCH_USAGE, kb.as_markup())


# ─── Categories ──────────────────────────────────────────────────────────────


def _build_categories_index() -> tuple[str, InlineKeyboardBuilder]:
    with db.session_scope() as s:
        rows = (
            s.query(db.Product.category, sqlfunc.count(db.Product.code).label("cnt"))
            .filter(db.Product.category.isnot(None))
            .group_by(db.Product.category)
            .order_by(sqlfunc.count(db.Product.code).desc())
            .limit(CATEGORIES_LIMIT)
            .all()
        )

    if not rows:
        kb = _back_to_menu_kb()
        return messages.CATEGORIES_EMPTY, kb

    body = messages.CATEGORIES_HEADER.format(count=len(rows)) + "\n"
    for category, cnt in rows:
        body += messages.CATEGORIES_ROW.format(count=cnt, name=_md_escape(category))

    kb = InlineKeyboardBuilder()
    for category, cnt in rows:
        # callback_data has a 64-byte limit; truncate aggressively if needed.
        cat_for_cb = category[:30]
        kb.button(text=f"{category} ({cnt})", callback_data=f"cat:view:{cat_for_cb}:1")
    kb.adjust(2)
    kb.button(text=messages.BTN_BACK_TO_MENU, callback_data="menu:home")
    return body, kb


def _build_category_page(category: str, page: int) -> tuple[str, InlineKeyboardBuilder]:
    needle = f"{category}%"  # prefix match in case category was truncated
    with db.session_scope() as s:
        q = s.query(db.Product).filter(db.Product.category.like(needle)).order_by(
            db.Product.code_sort.asc().nullslast(), db.Product.code.asc()
        )
        total = q.count()
        if total == 0:
            kb = _back_to_menu_kb()
            return messages.CATEGORIES_EMPTY, kb
        total_pages = max(1, math.ceil(total / PRODUCTS_PER_PAGE))
        page = max(1, min(page, total_pages))
        offset = (page - 1) * PRODUCTS_PER_PAGE
        rows = q.offset(offset).limit(PRODUCTS_PER_PAGE).all()

        body = messages.CATEGORY_HEADER.format(
            category=_md_escape(category), count=total, page=page, pages=total_pages
        )
        for p in rows:
            body += messages.PRODUCTS_ROW.format(
                stock_icon=_stock_icon(p.stock_qty),
                code=_md_escape(p.code),
                name=_md_escape(p.name),
                price=_format_price(p.price),
            )

    kb = InlineKeyboardBuilder()
    for p in rows:
        kb.button(text=p.code, callback_data=f"prod:view:{p.code}")
    kb.adjust(5)
    if page > 1:
        kb.button(text=messages.BTN_PREV, callback_data=f"cat:view:{category}:{page - 1}")
    if page < total_pages:
        kb.button(text=messages.BTN_NEXT, callback_data=f"cat:view:{category}:{page + 1}")
    kb.button(text=messages.BTN_BACK, callback_data="cat:list")
    kb.button(text=messages.BTN_BACK_TO_MENU, callback_data="menu:home")
    return body, kb


@router.message(Command("categories"))
async def handle_categories(message: Message) -> None:
    body, kb = _build_categories_index()
    await message.answer(body, reply_markup=kb.as_markup())


@router.callback_query(F.data == "menu:categories")
@router.callback_query(F.data == "cat:list")
async def handle_categories_index(callback: CallbackQuery) -> None:
    body, kb = _build_categories_index()
    await _send_or_edit(callback, body, kb.as_markup())


@router.callback_query(F.data.startswith("cat:view:"))
async def handle_category_view(callback: CallbackQuery) -> None:
    # "cat:view:CATEGORY:PAGE"
    parts = callback.data.split(":", 3)
    category = parts[2]
    page = int(parts[3]) if len(parts) > 3 else 1
    body, kb = _build_category_page(category, page)
    await _send_or_edit(callback, body, kb.as_markup())


# ─── Settings (view + edit) ──────────────────────────────────────────────────


def _build_settings_view() -> tuple[str, InlineKeyboardBuilder]:
    text = messages.SETTINGS_VIEW.format(
        agent_active=db.get_setting("agent_active", "true"),
        gen_time=db.get_setting("post_gen_time", "11:30"),
        publish_time=db.get_setting("post_publish_time", "12:00"),
        budget=db.get_setting("monthly_budget_usd", "20"),
        tone=db.get_setting("tone_mode", "default"),
    )
    kb = _back_to_menu_kb()
    return text, kb


@router.message(Command("settings"))
async def handle_settings(message: Message) -> None:
    text, kb = _build_settings_view()
    await message.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data == "menu:settings")
async def handle_menu_settings(callback: CallbackQuery) -> None:
    text, kb = _build_settings_view()
    await _send_or_edit(callback, text, kb.as_markup())


@router.message(Command("set_active"))
async def handle_set_active(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer(messages.SETTINGS_USAGE.format(command="/set_active"))
        return
    arg = command.args.strip().lower()
    if arg not in ("true", "false", "1", "0", "on", "off"):
        await message.answer(messages.SETTINGS_INVALID_BOOL)
        return
    value = "true" if arg in ("true", "1", "on") else "false"
    db.set_setting("agent_active", value)
    log.info("setting_changed", key="agent_active", value=value)
    # Reload scheduler so the change takes effect on the next firing.
    _reload_scheduler()
    await message.answer(messages.SETTINGS_UPDATED.format(key="agent\\_active", value=value))


def _reload_scheduler() -> None:
    """Tell the scheduler to re-read settings. Safe no-op if not initialized."""
    from src import scheduler as scheduler_module
    s = scheduler_module.get()
    if s is not None:
        s.reload_settings()


@router.message(Command("set_gen_time"))
async def handle_set_gen_time(message: Message, command: CommandObject) -> None:
    await _set_time(message, command, "post_gen_time", "/set_gen_time")


@router.message(Command("set_publish_time"))
async def handle_set_publish_time(message: Message, command: CommandObject) -> None:
    await _set_time(message, command, "post_publish_time", "/set_publish_time")


async def _set_time(message: Message, command: CommandObject, setting_key: str, cmd_name: str) -> None:
    if not command.args:
        await message.answer(messages.SETTINGS_USAGE.format(command=cmd_name))
        return
    arg = command.args.strip()
    if not TIME_RE.match(arg):
        await message.answer(messages.SETTINGS_INVALID_TIME)
        return
    db.set_setting(setting_key, arg)
    log.info("setting_changed", key=setting_key, value=arg)
    # Only post_gen_time affects the scheduler today (publish is on-tap).
    if setting_key == "post_gen_time":
        _reload_scheduler()
    await message.answer(
        messages.SETTINGS_UPDATED.format(key=setting_key.replace("_", "\\_"), value=arg)
    )


@router.message(Command("set_budget"))
async def handle_set_budget(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer(messages.SETTINGS_USAGE.format(command="/set_budget"))
        return
    try:
        value = float(command.args.strip())
    except ValueError:
        await message.answer(messages.SETTINGS_INVALID_NUMBER)
        return
    if value <= 0:
        await message.answer(messages.SETTINGS_INVALID_NUMBER)
        return
    db.set_setting("monthly_budget_usd", str(value))
    log.info("setting_changed", key="monthly_budget_usd", value=value)
    await message.answer(messages.SETTINGS_UPDATED.format(key="monthly\\_budget\\_usd", value=str(value)))


# ─── Spend ───────────────────────────────────────────────────────────────────


def _build_spend_view() -> tuple[str, InlineKeyboardBuilder]:
    with db.session_scope() as s:
        first_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        rows = s.query(db.ApiSpend).filter(db.ApiSpend.occurred_at >= first_of_month).all()
        spent = sum(r.cost_usd for r in rows)
        cap = float(db.get_setting("monthly_budget_usd", "20"))
    pct = (spent / cap * 100) if cap > 0 else 0
    text = messages.SPEND_VIEW.format(
        budget_bar=_progress_bar(pct), spent=spent, cap=cap, pct=pct
    )
    kb = _back_to_menu_kb()
    return text, kb


@router.message(Command("spend"))
async def handle_spend(message: Message) -> None:
    text, kb = _build_spend_view()
    await message.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data == "menu:spend")
async def handle_menu_spend(callback: CallbackQuery) -> None:
    text, kb = _build_spend_view()
    await _send_or_edit(callback, text, kb.as_markup())


# ─── Reimport ────────────────────────────────────────────────────────────────


@router.message(Command("reimport"))
async def handle_reimport(message: Message) -> None:
    await message.answer(messages.REIMPORT_STARTING)
    try:
        summary = catalog_importer.run_import()
    except Exception as e:
        log.exception("reimport_failed")
        await message.answer(messages.REIMPORT_ERROR.format(error=_md_escape(str(e))))
        return
    kb = _back_to_menu_kb()
    await message.answer(
        messages.REIMPORT_DONE.format(
            inserted=summary.inserted,
            updated=summary.updated,
            unchanged=summary.unchanged,
            skipped=summary.skipped,
        ),
        reply_markup=kb.as_markup(),
    )


# ─── Future-phase stubs ──────────────────────────────────────────────────────


@router.message(Command("orders"))
@router.message(Command("sales"))
@router.message(Command("expenses"))
async def handle_future_stubs(message: Message) -> None:
    kb = _back_to_menu_kb()
    await message.answer(messages.STUB_COMING_SOON, reply_markup=kb.as_markup())
