"""Telegram post-approval flow.

The generator (src/ai/generator.py) produces a draft and saves it to the
`post_drafts` table with status="pending". This module renders that draft
as a Telegram message (image + caption) with three inline buttons:

  ✅ დადასტურება  — mark approved, queue for publish (Phase 5 wires real publish)
  ✏️ რედაქტირება — user types feedback, generator re-runs with feedback injected
  ❌ უარყოფა     — generator re-runs with a "try a different angle" hint

The module exposes two public entry points:

  send_preview(bot, chat_id, draft)  — used by /generate command + scheduler
  router                              — included in bot.py dispatcher

Pre-rendered text-card or real-photo path is in draft.image_path. We use
Telegram's send_photo with caption ≤ 1024 chars; if the post is longer,
the photo is sent first then the body text in a follow-up.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src import config, db, guardrails
from src.ai import generator
from src.ai.generator import GeneratedPost
from src.logging_setup import get_logger
from src.telegram_bot import messages

log = get_logger(__name__)
router = Router()

# Telegram caption limit (1024 chars when message has media).
TG_CAPTION_LIMIT = 1024


class EditFeedback(StatesGroup):
    waiting_value = State()
    # Data: {"draft_id": int}


# ─── Rendering ───────────────────────────────────────────────────────────────


def _format_price(price: Optional[float]) -> str:
    if price is None or price == 0:
        return "ფასი არ არის"
    if price == int(price):
        return f"{int(price)} ₾"
    return f"{price:g} ₾"


def _md_escape(text: str) -> str:
    """Minimal Markdown-safe escape for free-text fields."""
    return (
        text.replace("\\", "\\\\")
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("`", "\\`")
        .replace("[", "\\[")
    )


def _format_violation_summary(violations: list[guardrails.Violation]) -> str:
    if not violations:
        return messages.PREVIEW_NO_VIOLATIONS
    lines = []
    for v in violations:
        icon = "❌" if v.severity is guardrails.Severity.BLOCK else "⚠️"
        lines.append(f"{icon} {_md_escape(v.detail)}")
    return messages.PREVIEW_VIOLATIONS_HEADER.format(lines="\n".join(lines))


def render_preview_header(
    slot: str,
    product_code: Optional[str],
    product_name: Optional[str],
    product_price: Optional[float],
) -> str:
    """Build the header block (slot + product line)."""
    if product_code:
        product_line = messages.PREVIEW_PRODUCT_LINE.format(
            code=_md_escape(product_code),
            name=_md_escape((product_name or "")[:50]),
            price=_format_price(product_price),
        )
    else:
        product_line = messages.PREVIEW_NO_PRODUCT_LINE
    return messages.PREVIEW_HEADER.format(slot=slot, product_line=product_line)


def render_preview_footer(hashtags: list[str], violations: list[guardrails.Violation]) -> str:
    return messages.PREVIEW_FOOTER.format(
        hashtags=" ".join(hashtags),
        violation_summary=_format_violation_summary(violations),
    )


def render_preview_text(
    body_text: str,
    slot: str,
    hashtags: list[str],
    product_code: Optional[str],
    product_name: Optional[str],
    product_price: Optional[float],
    violations: list[guardrails.Violation],
) -> str:
    """Full preview text: header + body + footer."""
    return (
        render_preview_header(slot, product_code, product_name, product_price)
        + body_text
        + render_preview_footer(hashtags, violations)
    )


def render_approval_keyboard(draft_id: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text=messages.BTN_APPROVE, callback_data=f"draft:approve:{draft_id}")
    kb.button(text=messages.BTN_EDIT, callback_data=f"draft:edit:{draft_id}")
    kb.button(text=messages.BTN_REJECT, callback_data=f"draft:reject:{draft_id}")
    kb.button(text=messages.BTN_BACK_TO_MENU, callback_data="menu:home")
    kb.adjust(3, 1)
    return kb


# ─── Sending the preview ─────────────────────────────────────────────────────


async def send_preview(
    bot: Bot,
    chat_id: int,
    post: GeneratedPost,
    draft_id: int,
) -> None:
    """Send a Telegram preview message for a generated draft.

    Strategy:
      - If post has an image_path: send_photo with caption (cap 1024 chars).
        If preview text is too long, follow up with the overflow as a text message.
      - If no image: send a plain text message.
    """
    text = render_preview_text(
        body_text=post.body_text,
        slot=post.slot,
        hashtags=post.hashtags,
        product_code=post.featured_product_code,
        product_name=post.featured_product_name,
        product_price=post.featured_product_price,
        violations=post.violations,
    )
    kb = render_approval_keyboard(draft_id).as_markup()

    if post.image_path and Path(post.image_path).exists():
        photo = FSInputFile(post.image_path)
        if len(text) <= TG_CAPTION_LIMIT:
            await bot.send_photo(chat_id, photo=photo, caption=text, reply_markup=kb)
            return
        # Caption overflow → send photo bare, then text with keyboard.
        await bot.send_photo(chat_id, photo=photo)
        await bot.send_message(chat_id, text, reply_markup=kb)
        return

    await bot.send_message(chat_id, text, reply_markup=kb)


# ─── Button handlers ─────────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("draft:approve:"))
async def handle_draft_approve(callback: CallbackQuery) -> None:
    """Approve a draft → mark in DB, then publish to Facebook (or DRY_RUN log).

    Flow:
      1. Mark draft as approved, stamp approved_at, update product.last_featured_at.
      2. If DRY_RUN=true: edit message to "approved (dry run)" and stop.
      3. If DRY_RUN=false: actually call Meta Graph API, save fb_post_id to
         posts table, edit message to "published" with permalink.
      4. On publish failure: tell the founder the error; draft is still
         approved in DB so we can retry later.
    """
    import asyncio
    from datetime import datetime as _dt
    from pathlib import Path

    from src import config as cfg_mod
    from src.facebook import publisher as fb_pub

    draft_id = int(callback.data.split(":")[-1])

    # ─── 1. Update DB ──
    with db.session_scope() as s:
        draft = s.get(db.PostDraft, draft_id)
        if draft is None:
            await callback.answer("ვერ მოიძებნა", show_alert=True)
            return
        draft.status = "approved"
        draft.approved_at = _dt.utcnow()
        # Snapshot what publisher will need (we leave the session before publishing).
        body_text = draft.body_text
        hashtags = json.loads(draft.hashtags_json) if draft.hashtags_json else []
        image_path = draft.image_path
        product_code = draft.featured_product_code
        if product_code:
            product = s.get(db.Product, product_code)
            if product is not None:
                product.last_featured_at = _dt.utcnow()

    log.info("draft_approved", draft_id=draft_id)

    cfg = cfg_mod.load()

    # ─── 2. Show "publishing" placeholder + actually publish ──
    await callback.answer("დადასტურდა")

    if cfg.dry_run:
        # Skip the publish call entirely.
        await _edit_approval_message(
            callback,
            messages.PREVIEW_APPROVED_DRYRUN.format(id=draft_id),
        )
        return

    if not image_path or not Path(image_path).exists():
        await _edit_approval_message(
            callback,
            messages.PREVIEW_PUBLISH_FAILED.format(
                id=draft_id, error="Image file not found on disk"
            ),
        )
        return

    # Edit message to "publishing…" so the founder knows we're hitting Meta.
    await _edit_approval_message(callback, messages.PREVIEW_PUBLISHING)

    def _do_publish() -> fb_pub.PublishResult:
        return fb_pub.publish_post(body_text, hashtags, image_path, cfg=cfg)

    try:
        result = await asyncio.to_thread(_do_publish)
    except fb_pub.FacebookCredentialsMissing as e:
        log.error("fb_publish_no_creds", error=str(e))
        await _edit_approval_message(
            callback,
            messages.PREVIEW_PUBLISH_FAILED.format(id=draft_id, error=str(e)),
        )
        return
    except fb_pub.FacebookPublishError as e:
        log.error("fb_publish_failed", error=str(e))
        await _edit_approval_message(
            callback,
            messages.PREVIEW_PUBLISH_FAILED.format(id=draft_id, error=str(e)[:300]),
        )
        return
    except Exception as e:
        log.exception("fb_publish_unexpected")
        await _edit_approval_message(
            callback,
            messages.PREVIEW_PUBLISH_FAILED.format(id=draft_id, error=f"{type(e).__name__}: {str(e)[:200]}"),
        )
        return

    # ─── 3. Persist the publish result ──
    with db.session_scope() as s:
        s.add(
            db.Post(
                draft_id=draft_id,
                fb_post_id=result.fb_post_id,
                fb_permalink=result.fb_permalink,
                published_at=_dt.utcnow(),
            )
        )
        d = s.get(db.PostDraft, draft_id)
        if d:
            d.status = "published"

    log.info("post_published", draft_id=draft_id, fb_post_id=result.fb_post_id)
    await _edit_approval_message(
        callback,
        messages.PREVIEW_PUBLISHED.format(
            fb_post_id=result.fb_post_id,
            permalink=result.fb_permalink or "—",
        ),
    )


async def _edit_approval_message(callback: CallbackQuery, text: str) -> None:
    """Helper — edit caption if message has a photo, else edit text. Both fail-safe."""
    if not callback.message:
        return
    try:
        if callback.message.photo:
            await callback.message.edit_caption(caption=text)
        else:
            await callback.message.edit_text(text)
    except Exception:
        try:
            await callback.message.answer(text)
        except Exception:
            pass


@router.callback_query(F.data.startswith("draft:edit:"))
async def handle_draft_edit(callback: CallbackQuery, state: FSMContext) -> None:
    draft_id = int(callback.data.split(":")[-1])
    await state.set_state(EditFeedback.waiting_value)
    await state.update_data(draft_id=draft_id)
    if callback.message:
        try:
            await callback.message.reply(messages.PREVIEW_EDIT_PROMPT)
        except Exception:
            pass
    await callback.answer()


@router.message(Command("cancel"), EditFeedback.waiting_value)
async def fsm_edit_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ გაუქმდა.")


@router.message(EditFeedback.waiting_value)
async def fsm_edit_feedback(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    draft_id = data.get("draft_id")
    feedback = (message.text or "").strip()
    if not feedback:
        await message.answer("გამოგზავნე ცარიელი არ შეიძლება.")
        return
    await state.clear()

    # Store user_feedback on the draft, mark as "edited", and regenerate.
    with db.session_scope() as s:
        draft = s.get(db.PostDraft, draft_id)
        if draft is None:
            await message.answer("draft ვერ მოიძებნა.")
            return
        draft.user_feedback = feedback
        draft.status = "edited"
        old_slot = draft.calendar_slot

    placeholder = await message.answer(messages.PREVIEW_REGENERATING)
    try:
        new_post = await _regenerate_with_feedback(old_slot, feedback)
    except Exception:
        log.exception("regenerate_failed")
        try:
            await placeholder.edit_text(messages.GENERATE_FAILED)
        except Exception:
            pass
        return

    new_draft_id = _persist_draft(new_post)
    try:
        await placeholder.delete()
    except Exception:
        pass
    await send_preview(message.bot, message.chat.id, new_post, new_draft_id)


@router.callback_query(F.data.startswith("draft:reject:"))
async def handle_draft_reject(callback: CallbackQuery) -> None:
    draft_id = int(callback.data.split(":")[-1])
    with db.session_scope() as s:
        draft = s.get(db.PostDraft, draft_id)
        if draft is None:
            await callback.answer("ვერ მოიძებნა", show_alert=True)
            return
        draft.status = "rejected"
        old_slot = draft.calendar_slot

    await callback.answer("ვცდი სხვა მიდგომით…")
    placeholder = await callback.message.answer(messages.PREVIEW_REGENERATING) if callback.message else None

    try:
        new_post = await _regenerate_with_feedback(
            old_slot,
            "წინა draft არ მოეწონა — ცადე სრულიად განსხვავებული მიდგომა (სხვა hook, სხვა angle).",
        )
    except Exception:
        log.exception("regenerate_failed")
        if placeholder:
            try:
                await placeholder.edit_text(messages.GENERATE_FAILED)
            except Exception:
                pass
        return

    new_draft_id = _persist_draft(new_post)
    if placeholder:
        try:
            await placeholder.delete()
        except Exception:
            pass
    if callback.message:
        await send_preview(callback.message.bot, callback.message.chat.id, new_post, new_draft_id)


# ─── Helpers ─────────────────────────────────────────────────────────────────


async def _regenerate_with_feedback(slot: str, feedback: str) -> GeneratedPost:
    """Re-run the generator with an extra feedback line in the prompts.

    Today the feedback is appended to the writer's prompt via the
    `previous_violations` mechanism. We synthesize a Violation-like entry
    that carries the founder's free text.
    """
    import asyncio

    pseudo_violation = guardrails.Violation(
        rule="founder_feedback",
        severity=guardrails.Severity.BLOCK,
        detail=feedback,
    )

    def _run() -> GeneratedPost:
        return _generate_with_violation(slot, pseudo_violation)

    # generator does synchronous SDK calls — run in executor so the bot loop stays free.
    return await asyncio.to_thread(_run)


def _generate_with_violation(slot: str, seed_violation: guardrails.Violation) -> GeneratedPost:
    """Wrapper that pre-seeds the generator's retry loop with one violation.

    We achieve this by calling write_post() directly with the seed, then
    re-using the rest of generator's pipeline. Simpler than a config flag.
    """
    cfg = config.load()
    from src.ai.claude_client import ClaudeClient
    from src.ai.gemini_client import GeminiClient

    claude = ClaudeClient(cfg)
    gemini = GeminiClient(cfg)

    brief = generator.pick_topic(claude, slot)
    product = generator._load_product(brief.featured_product_code)

    # Pre-seed: pass the founder feedback as a "previous_violation" so the
    # writer is told to incorporate it on the very first attempt.
    body, hashtags = generator.write_post(
        gemini, brief, product, previous_violations=[seed_violation]
    )
    draft = generator._make_draft(body, hashtags, product)
    violations = guardrails.validate(draft)

    # Same 3-tier hierarchy as generate_draft_for_slot.
    image_path, image_source = generator.resolve_image_path(brief.featured_product_code)
    if image_path is None and product is not None:
        try:
            overlay_path = generator.find_and_overlay_photo(
                product_code=product.code,
                product_name=product.name,
                price=product.price,
            )
            if overlay_path:
                image_path = overlay_path
                image_source = "found_overlay"
        except Exception:
            log.exception("find_and_overlay_failed")
    if image_path is None and product is not None:
        try:
            image_path = generator.render_text_card_for_product(
                product_code=product.code,
                product_name=product.name,
                price=product.price,
            )
            image_source = "text_card"
        except Exception:
            log.exception("text_card_render_failed")

    return GeneratedPost(
        slot=slot,
        body_text=body,
        hashtags=hashtags,
        cta=brief.cta,
        featured_product_code=product.code if product else None,
        featured_product_name=product.name if product else None,
        featured_product_price=product.price if product else None,
        image_path=image_path,
        image_source=image_source,
        violations=violations,
    )


def _persist_draft(post: GeneratedPost) -> int:
    """Save a GeneratedPost to post_drafts table. Returns new draft id."""
    from datetime import date

    with db.session_scope() as s:
        draft = db.PostDraft(
            target_date=date.today(),
            calendar_slot=post.slot,
            body_text=post.body_text,
            hashtags_json=json.dumps(post.hashtags, ensure_ascii=False),
            cta=post.cta,
            featured_product_code=post.featured_product_code,
            image_path=post.image_path,
            image_source=post.image_source,
            status="pending",
        )
        s.add(draft)
        s.flush()
        return draft.id
