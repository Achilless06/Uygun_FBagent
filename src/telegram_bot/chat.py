"""Conversational chat router — handles natural-language messages.

This router has ONE handler: any text message that doesn't start with "/"
and isn't in a FSM state (e.g., search waiting-for-query) gets routed
through the chat engine.

The chat router MUST be included AFTER admin.router in the dispatcher,
because aiogram processes routers in order and admin.router holds all
the command handlers + callback handlers. If we put chat first, it would
swallow every message.

UX details:
  - Long Claude responses (~5-10s) — we send a "💭 ვფიქრობ…" placeholder
    that gets edited to the real reply when ready.
  - The placeholder also lets the founder see the bot is alive — no
    silent hang.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from src import config
from src.ai.conversation import ChatEngine
from src.ai.gemini_client import GeminiClient
from src.logging_setup import get_logger
from src.telegram_bot import messages

log = get_logger(__name__)
router = Router()

# Initialized lazily on first chat so startup doesn't fail without Claude key.
_engine: ChatEngine | None = None


def _get_engine() -> ChatEngine:
    global _engine
    if _engine is None:
        cfg = config.load()
        _engine = ChatEngine(GeminiClient(cfg))
    return _engine


@router.message(F.text & ~F.text.startswith("/"))
async def handle_chat(message: Message) -> None:
    user_text = message.text.strip() if message.text else ""
    if not user_text:
        return

    # Send a "thinking" placeholder so the founder sees the bot is alive.
    placeholder = await message.answer(messages.CHAT_THINKING)

    try:
        reply = _get_engine().respond(user_text)
    except Exception:
        log.exception("chat_engine_failed")
        try:
            await placeholder.edit_text(messages.CHAT_ERROR)
        except Exception:
            await message.answer(messages.CHAT_ERROR)
        return

    # Telegram has a 4096-char message limit; truncate long replies.
    if len(reply) > 4000:
        reply = reply[:3900] + "\n\n_…[დაჭრილია, ძალიან გრძელია]_"

    try:
        await placeholder.edit_text(reply)
    except Exception:
        # edit_text fails for content with conflicting Markdown — fall back to plain reply.
        try:
            await placeholder.edit_text(reply, parse_mode=None)
        except Exception:
            log.exception("chat_send_failed")
            await message.answer(reply, parse_mode=None)
