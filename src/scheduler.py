"""Daily generation scheduler.

The bot starts this scheduler on startup. It runs ONE recurring cron job:

  daily_generation — fires at `post_gen_time` (default 11:30 Asia/Tbilisi) every day.

When the job fires:
  1. Check `agent_active` setting — skip if "false" (the founder paused us).
  2. Run the post generator (same pipeline as `/generate`).
  3. Send the preview to the admin chat with ✅/✏️/❌ buttons.

From there, the founder taps approve / edit / reject as usual. Publishing
happens on ✅ tap, not on a separate timer — human-in-the-loop is the rule.

`post_publish_time` is kept as a runtime setting for future enhancements
(e.g. "auto-publish if approved before X") but isn't enforced today.

Settings reload: when the founder runs /set_gen_time or /set_active, those
handlers call `get().reload_settings()` to refresh the cron schedule without
restarting the bot.

Why a module-level singleton instead of DI: aiogram v3 supports DI via the
dispatcher, but for one scheduler instance that everything reads, a simple
`get()` accessor keeps callsites small. The singleton is created once in
bot.py's startup.
"""

from __future__ import annotations

from typing import Optional

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src import db
from src.logging_setup import get_logger

log = get_logger(__name__)

_GENERATION_JOB_ID = "daily_generation"
_BUDGET_CHECK_JOB_ID = "budget_threshold_check"
_BACKUP_JOB_ID = "daily_db_backup"

# Keep N most recent backups; older ones are deleted to bound disk use.
_BACKUP_RETENTION = 14


class BotScheduler:
    def __init__(self, bot: Bot, admin_chat_id: int, timezone: str) -> None:
        self._bot = bot
        self._admin_chat_id = admin_chat_id
        self._scheduler = AsyncIOScheduler(timezone=timezone)
        self._tz_name = timezone

    def start(self) -> None:
        """Load the job from current settings and start the scheduler."""
        self._reload()
        self._scheduler.start()
        next_run = self._next_run_time_str()
        log.info("scheduler_started", timezone=self._tz_name, next_run=next_run)

    def shutdown(self) -> None:
        """Stop the scheduler. Called when the bot is shutting down."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def reload_settings(self) -> None:
        """Re-read post_gen_time from DB and reschedule the cron.

        Called by admin handlers when the founder changes a relevant setting.
        Safe to call repeatedly — `replace_existing=True` makes it idempotent.
        """
        self._reload()
        log.info(
            "scheduler_reloaded",
            next_run=self._next_run_time_str(),
            agent_active=db.get_setting("agent_active", "true"),
        )

    def _reload(self) -> None:
        gen_time = db.get_setting("post_gen_time", "11:30")
        hour, minute = self._parse_time(gen_time)
        self._scheduler.add_job(
            self._daily_generation,
            CronTrigger(hour=hour, minute=minute, timezone=self._tz_name),
            id=_GENERATION_JOB_ID,
            replace_existing=True,
            # If the bot was offline at the firing time, run when it comes back
            # up — but only if we missed by less than 10 minutes (a longer delay
            # means a stale post that no longer makes sense for "today").
            misfire_grace_time=600,
        )
        # Budget check every 30 minutes: detects threshold crossings caused by
        # ad-hoc operations (chat, /generate, /test_schedule) and fires the
        # 80%/100% Telegram alerts.
        self._scheduler.add_job(
            self._budget_check,
            CronTrigger(minute="*/30", timezone=self._tz_name),
            id=_BUDGET_CHECK_JOB_ID,
            replace_existing=True,
            misfire_grace_time=300,
        )
        # Daily DB backup at 03:30 local time — the cheapest moment.
        self._scheduler.add_job(
            self._daily_backup,
            CronTrigger(hour=3, minute=30, timezone=self._tz_name),
            id=_BACKUP_JOB_ID,
            replace_existing=True,
            misfire_grace_time=3600,
        )

    def _next_run_time_str(self) -> str:
        job = self._scheduler.get_job(_GENERATION_JOB_ID)
        if job is None or job.next_run_time is None:
            return "(not scheduled)"
        return job.next_run_time.strftime("%Y-%m-%d %H:%M %Z")

    @staticmethod
    def _parse_time(value: str) -> tuple[int, int]:
        """Parse HH:MM from a settings value, fall back to 11:30 on error."""
        try:
            parts = value.split(":")
            return int(parts[0]), int(parts[1])
        except (AttributeError, ValueError, IndexError):
            log.error("scheduler_invalid_time", value=value)
            return 11, 30

    async def _daily_generation(self) -> None:
        """The cron job body. Runs in the AsyncIO event loop."""
        if db.get_setting("agent_active", "true") != "true":
            log.info("scheduler_skip_paused")
            return

        log.info("scheduler_daily_generation_start")

        # Deferred import: scheduler.py is imported BY bot.py, and admin.py is
        # imported BY bot.py too — importing admin at module level would create
        # a circular dependency in some scenarios. Local import avoids it.
        from src.telegram_bot.admin import _run_generate_and_preview

        try:
            await _run_generate_and_preview(
                chat_id=self._admin_chat_id,
                bot=self._bot,
                slot=None,
                placeholder_msg=None,
            )
        except Exception:
            log.exception("scheduler_daily_generation_failed")
            try:
                await self._bot.send_message(
                    self._admin_chat_id,
                    "⚠️ ავტომატური გენერაცია ჩავარდა. დეტალები ლოგებში.",
                )
            except Exception:
                # If even the error notification can't go through, give up
                # silently — bot logging captured it.
                pass

    async def run_now(self) -> None:
        """Manually trigger the daily generation job — used by /test_schedule."""
        await self._daily_generation()

    async def _budget_check(self) -> None:
        """Periodic budget threshold check (80% warn / 100% auto-pause).

        Runs every 30 minutes. Stateful per-month dedup is in `budget.py`,
        so this can fire as often as we like without spamming alerts.
        """
        from src import budget as _budget
        try:
            await _budget.check_thresholds(self._bot, self._admin_chat_id)
        except Exception:
            log.exception("budget_check_failed")

    async def _daily_backup(self) -> None:
        """Daily SQLite backup at 03:30 local. Uses sqlite3 .backup for
        a consistent snapshot (safe even while WAL writers are active).
        """
        import sqlite3
        from datetime import datetime

        from src import config

        src_path = config.DATA_DIR / "uygun.db"
        if not src_path.exists():
            log.warning("backup_skip_no_db", path=str(src_path))
            return

        backup_dir = config.DATA_DIR / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y-%m-%d")
        dst_path = backup_dir / f"uygun-{stamp}.db"

        try:
            # SQLite's online backup API: atomic, safe, doesn't block reads.
            with sqlite3.connect(str(src_path)) as src_con:
                with sqlite3.connect(str(dst_path)) as dst_con:
                    src_con.backup(dst_con)
            size_kb = dst_path.stat().st_size // 1024
            log.info("db_backup_done", path=str(dst_path), size_kb=size_kb)
        except Exception:
            log.exception("db_backup_failed")
            return

        # Rotation — keep newest N backups, delete the rest.
        backups = sorted(backup_dir.glob("uygun-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[_BACKUP_RETENTION:]:
            try:
                old.unlink()
                log.info("db_backup_rotated", removed=str(old))
            except Exception:
                log.warning("db_backup_rotate_failed", path=str(old))


# ─── Module-level singleton ──────────────────────────────────────────────────

_singleton: Optional[BotScheduler] = None


def init(bot: Bot, admin_chat_id: int, timezone: str) -> BotScheduler:
    """Initialize the singleton. Called once from bot.py at startup."""
    global _singleton
    _singleton = BotScheduler(bot, admin_chat_id, timezone)
    return _singleton


def get() -> Optional[BotScheduler]:
    """Get the singleton, or None if not yet initialized."""
    return _singleton
