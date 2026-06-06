"""Telegram bot bootstrap.

Initializes the aiogram 3.x Bot + Dispatcher, attaches the admin-only
middleware, registers the admin router, and runs long polling.

Can be run standalone for smoke-testing Phase 2:

    python -m src.telegram_bot.bot

In production (Phase 9), main.py starts both the scheduler and this bot
concurrently.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from src import config, db
from src import scheduler as scheduler_module
from src.logging_setup import configure as configure_logging
from src.logging_setup import get_logger
from src.telegram_bot import admin, approval, chat, import_sales, messages

log = get_logger(__name__)


# ─── Auth middleware ─────────────────────────────────────────────────────────


class AdminOnlyMiddleware(BaseMiddleware):
    """Drop every update that isn't from the configured admin chat ID.

    Security: the bot's username is technically guessable, so anyone could
    /start it. This middleware ensures the bot does nothing for non-admin
    chats — no menus, no errors, just silence + a logged warning.
    """

    def __init__(self, admin_chat_id: int) -> None:
        self.admin_chat_id = admin_chat_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        chat_id = _extract_chat_id(event)
        log.info(
            "update_received",
            chat_id=chat_id,
            expected_admin_chat_id=self.admin_chat_id,
            event_type=type(event).__name__,
        )
        if chat_id is None:
            # Non-chat update type (e.g. inline query) — drop.
            return None
        if chat_id != self.admin_chat_id:
            log.warning(
                "unauthorized_telegram_chat",
                chat_id=chat_id,
                event_type=type(event).__name__,
            )
            # Politely tell unknown chats this isn't for them.
            msg = event.message if isinstance(event, Update) else (
                event if isinstance(event, Message) else None
            )
            if msg is not None:
                try:
                    await msg.answer(messages.UNAUTHORIZED)
                except Exception:
                    pass
            return None
        return await handler(event, data)


def _extract_chat_id(event: TelegramObject) -> int | None:
    """Pull chat_id from whichever event type we got.

    Outer middleware receives raw `Update` objects; inner-middleware paths get
    the sub-event (Message, CallbackQuery, etc.). We unwrap both.
    """
    if isinstance(event, Update):
        if event.message:
            return event.message.chat.id
        if event.edited_message:
            return event.edited_message.chat.id
        if event.callback_query and event.callback_query.message:
            return event.callback_query.message.chat.id
        if event.my_chat_member:
            return event.my_chat_member.chat.id
        return None
    if isinstance(event, Message):
        return event.chat.id
    if isinstance(event, CallbackQuery) and event.message:
        return event.message.chat.id
    return None


# ─── Dispatcher factory ──────────────────────────────────────────────────────


def build_dispatcher(admin_chat_id: int) -> Dispatcher:
    """Create a Dispatcher with the admin middleware + all routers.

    Order matters: admin first (commands + menu callbacks), then approval
    (FSM for edit feedback + draft callbacks), then chat (catch-all plain text).
    Each router is checked in order; chat catches anything not matched above.
    """
    dp = Dispatcher()
    dp.update.outer_middleware(AdminOnlyMiddleware(admin_chat_id))
    dp.include_router(admin.router)
    dp.include_router(approval.router)
    # import_sales BEFORE chat so its FSM message handlers (waiting_for_zip,
    # confirming) win over the catch-all chat handler when active.
    dp.include_router(import_sales.router)
    dp.include_router(chat.router)
    return dp


def build_bot(token: str) -> Bot:
    """Create a Bot with Markdown parse mode as the default (matches our templates)."""
    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )


# ─── Runner ──────────────────────────────────────────────────────────────────


async def _run() -> None:
    cfg = config.load()
    db.init_engine(cfg.database_url)
    db.create_all()
    db.seed_default_settings()

    bot = build_bot(cfg.telegram_bot_token)
    dp = build_dispatcher(cfg.telegram_admin_chat_id)

    # Start the daily-generation scheduler. It runs in the same event loop as
    # the bot and shares the Bot instance for sending Telegram messages.
    scheduler = scheduler_module.init(
        bot=bot, admin_chat_id=cfg.telegram_admin_chat_id, timezone=cfg.timezone
    )
    scheduler.start()

    log.info(
        "telegram_bot_starting",
        admin_chat_id=cfg.telegram_admin_chat_id,
        dry_run=cfg.dry_run,
    )

    # Drop any updates that piled up while the bot was offline — we don't want
    # to replay yesterday's button clicks.
    await bot.delete_webhook(drop_pending_updates=True)

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await bot.session.close()


def main() -> int:
    configure_logging("INFO")
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        log.info("telegram_bot_stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
