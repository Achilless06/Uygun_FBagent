"""Monthly budget circuit breaker.

Tracks every API call via `api_spend` table (Claude/Gemini/Meta usage)
and enforces the founder's `monthly_budget_usd` ceiling:

  - At  80% spent → send a Telegram warning (once per month per threshold)
  - At 100% spent → auto-pause the agent (`agent_active=false`) + alert

Called from two places:

  1. `is_blocked()` — before any expensive operation (chat, post generator,
     advisor tips). Returns True if budget exhausted; caller skips the call.
  2. `check_thresholds(bot)` — after each API call. Sends Telegram alerts
     once when a threshold is first crossed.

Threshold state is tracked in `settings` table so it survives bot restarts:

  - `budget_warn_80_sent_for_month` = "2026-05" (the YYYY-MM we last warned)
  - `budget_block_100_sent_for_month` = "2026-05"

When a new month starts, the `_current_month_tag()` differs from the saved
value → alerts can fire again. Clean automatic monthly reset.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from aiogram import Bot

from src import db
from src.logging_setup import get_logger

log = get_logger(__name__)

WARN_THRESHOLD = 0.80
BLOCK_THRESHOLD = 1.00


def _current_month_tag() -> str:
    """e.g. '2026-05' — used as a per-month flag for warn-once semantics."""
    return datetime.utcnow().strftime("%Y-%m")


def _start_of_month() -> datetime:
    now = datetime.utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def spent_this_month() -> float:
    """Sum of api_spend.cost_usd for the current calendar month (UTC)."""
    with db.session_scope() as s:
        rows = (
            s.query(db.ApiSpend)
            .filter(db.ApiSpend.occurred_at >= _start_of_month())
            .all()
        )
        return sum(r.cost_usd for r in rows)


def cap() -> float:
    """Founder's configured monthly cap, in USD."""
    raw = db.get_setting("monthly_budget_usd", "20")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 20.0


def status() -> dict:
    """Snapshot for /spend and /scheduler views."""
    spent = spent_this_month()
    c = cap()
    pct = (spent / c * 100) if c > 0 else 0
    return {
        "spent_usd": spent,
        "cap_usd": c,
        "pct": pct,
        "warn_threshold_pct": WARN_THRESHOLD * 100,
        "block_threshold_pct": BLOCK_THRESHOLD * 100,
        "month": _current_month_tag(),
    }


def is_blocked() -> bool:
    """True if budget exhausted AND we've already auto-paused.

    Callers (chat handler, generator, advisor) should check this *before*
    making a costly API call. We still allow the call if agent_active=true,
    so the founder can choose to override by raising the cap or re-enabling.
    """
    s = status()
    if s["pct"] < s["block_threshold_pct"]:
        return False
    # Only block if we auto-paused (don't punish the founder if they manually re-enabled).
    return db.get_setting("agent_active", "true") != "true"


async def check_thresholds(bot: Optional[Bot], admin_chat_id: Optional[int]) -> None:
    """Send alerts when thresholds are crossed (once per month per threshold).

    `bot` may be None for cases where we can't reach Telegram (smoke tests).
    In that case alerts log only.
    """
    s = status()
    month = s["month"]

    # ─── 80% warn ──
    if s["pct"] >= s["warn_threshold_pct"] and db.get_setting("budget_warn_80_sent_for_month") != month:
        log.warning("budget_80pct_crossed", spent=s["spent_usd"], cap=s["cap_usd"])
        db.set_setting("budget_warn_80_sent_for_month", month)
        if bot and admin_chat_id:
            from src.telegram_bot import messages
            try:
                await bot.send_message(
                    admin_chat_id,
                    messages.BUDGET_WARN_80.format(
                        spent=s["spent_usd"],
                        cap=s["cap_usd"],
                        pct=s["pct"],
                        remaining=s["cap_usd"] - s["spent_usd"],
                    ),
                )
            except Exception:
                log.exception("budget_warn_send_failed")

    # ─── 100% block ──
    if s["pct"] >= s["block_threshold_pct"] and db.get_setting("budget_block_100_sent_for_month") != month:
        log.error("budget_100pct_crossed_pausing_agent", spent=s["spent_usd"], cap=s["cap_usd"])
        db.set_setting("budget_block_100_sent_for_month", month)
        db.set_setting("agent_active", "false")
        if bot and admin_chat_id:
            from src.telegram_bot import messages
            try:
                await bot.send_message(
                    admin_chat_id,
                    messages.BUDGET_BLOCK_100.format(
                        spent=s["spent_usd"],
                        cap=s["cap_usd"],
                    ),
                )
            except Exception:
                log.exception("budget_block_send_failed")
