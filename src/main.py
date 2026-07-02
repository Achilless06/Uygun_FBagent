"""Combined entrypoint — runs the Telegram bot and brand website together.

Single Python process, single event loop, single Railway service. The bot
long-polls (no listening port), the FastAPI web server binds to `$PORT`
(8000 locally). Both share the SQLite database and `data/` directory.

Procfile points here:

    worker: python -m src.main

For dev:
    python -m src.main             # both bot + web
    python -m src.telegram_bot.bot # bot only (no web, faster restart while iterating prompts)
    uvicorn src.web.app:app --reload --port 8000 # web only (no Telegram noise while iterating UI)
"""

from __future__ import annotations

import asyncio
import os
import sys

import uvicorn

from src import config, db
from src import scheduler as scheduler_module
from src.logging_setup import configure as configure_logging
from src.logging_setup import get_logger
from src.telegram_bot.bot import build_bot, build_dispatcher

log = get_logger(__name__)


async def _run_bot(cfg: config.Config) -> None:
    bot = build_bot(cfg.telegram_bot_token)
    dp = build_dispatcher(cfg.telegram_admin_chat_id)

    scheduler = scheduler_module.init(
        bot=bot, admin_chat_id=cfg.telegram_admin_chat_id, timezone=cfg.timezone
    )
    scheduler.start()

    log.info(
        "telegram_bot_starting",
        admin_chat_id=cfg.telegram_admin_chat_id,
        dry_run=cfg.dry_run,
    )

    await bot.delete_webhook(drop_pending_updates=True)

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await bot.session.close()


async def _run_web() -> None:
    # Lazy import so config/db are guaranteed initialized before FastAPI app loads.
    from src.web.app import app as web_app

    port = int(os.getenv("PORT", "8000"))
    log.info("web_server_starting", host="0.0.0.0", port=port)

    server = uvicorn.Server(
        uvicorn.Config(
            web_app,
            host="0.0.0.0",
            port=port,
            log_config=None,  # use structlog setup, not uvicorn's default
            access_log=False,
        )
    )
    await server.serve()


async def _main() -> None:
    cfg = config.load()
    db.init_engine(cfg.database_url)
    db.create_all()
    db.seed_default_settings()
    db.apply_name_ka_seed()

    await asyncio.gather(_run_bot(cfg), _run_web())


def main() -> int:
    configure_logging("INFO")
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        log.info("main_stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
