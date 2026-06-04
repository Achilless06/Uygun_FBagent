"""Post generation pipeline.

Public entry point: `generate_draft_for_slot(slot)`.

The pipeline has 4 stages:

  1. **pick_topic**     — Claude reads the calendar slot, candidate products,
                          recent history, and founder memories; returns a
                          JSON brief (topic, featured product, angle, CTA).

  2. **write_post**     — Gemini takes the brief and writes the Georgian text
                          + hashtags.

  3. **validate**       — Two-layer check:
                          a) regex-only guardrails (src/guardrails.py)
                          b) Claude second-pass for tone/marketing-speak
                          If anything is BLOCK-severity, we either accept
                          Claude's polished_text rewrite OR retry with
                          violations in the next-turn prompt (max 2 retries).

  4. **resolve_image**  — Look for data/photos/{code}.jpg. If present, use
                          it. Otherwise return None (caller decides:
                          PIL text-card, or ask founder before Gemini-gen).

The result is a `GeneratedPost` dataclass that callers (the scheduler,
later a /generate Telegram command) can render as a preview and save to
the post_drafts table.

CLI for smoke-testing:

    python -m src.ai.generator                 # uses today's slot
    python -m src.ai.generator --slot=B2B      # force a slot
    python -m src.ai.generator --slot=B2C --no-validate   # skip Claude validator
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from src import brand, config, db, guardrails
from src.ai import image_gen, photo_finder, prompts
from src.ai.claude_client import ClaudeClient
from src.ai.gemini_client import GeminiClient
from src.logging_setup import get_logger

log = get_logger(__name__)

MAX_REGENERATION_RETRIES = 2
PRODUCT_CANDIDATES_LIMIT = 25


# ─── Result types ────────────────────────────────────────────────────────────


@dataclass
class TopicBrief:
    calendar_slot: str
    post_format: str
    featured_product_code: Optional[str]
    topic_title: str
    angle: str
    hook_style: str
    target_word_count: int
    cta: str


@dataclass
class GeneratedPost:
    slot: str
    body_text: str
    hashtags: list[str]
    cta: str
    featured_product_code: Optional[str]
    featured_product_name: Optional[str]
    featured_product_price: Optional[float]
    image_path: Optional[str] = None
    image_source: Optional[str] = None  # real | gemini | text_card | none
    violations: list[guardrails.Violation] = field(default_factory=list)
    validator_polish: Optional[str] = None   # Claude's rewrite, if any


# ─── Stage 1: pick topic (Claude) ────────────────────────────────────────────


def _slot_for_today() -> str:
    """Look up today's calendar slot from brand.WEEKLY_CALENDAR."""
    return brand.WEEKLY_CALENDAR.get(date.today().weekday(), "B2C")


def _season_hint_for(month: int) -> str:
    """Short Batumi seasonal context — same logic as advisor.py."""
    if month == 5:
        return "გვიანი გაზაფხული, ტურისტული სეზონის გახსნა."
    if month in (6, 7, 8):
        return "ზაფხული, პიკი ტურისტული სეზონი."
    if month == 9:
        return "ადრე შემოდგომა, სეზონის ბოლო."
    if month in (10, 11):
        return "შემოდგომა, ვულკანიზაცია მეტი მუშაობს."
    if month in (12, 1, 2):
        return "ზამთარი. ცივი ამინდი."
    return "გაზაფხული."


_WEEKDAYS_KA = [
    "ორშაბათი", "სამშაბათი", "ოთხშაბათი", "ხუთშაბათი",
    "პარასკევი", "შაბათი", "კვირა",
]


def _gather_product_candidates(slot: str, limit: int) -> list[db.Product]:
    """Pick a candidate set the strategist will choose from.

    Rules:
      - In stock (stock_qty > 0)
      - Not featured in the last 7 days (avoid repeats)
      - For Promo slot: must have a price
      - Random sample to give the strategist variety
    """
    with db.session_scope() as s:
        q = s.query(db.Product).filter(db.Product.stock_qty > 0)
        week_ago = datetime.utcnow() - timedelta(days=7)
        q = q.filter(
            (db.Product.last_featured_at.is_(None))
            | (db.Product.last_featured_at < week_ago)
        )
        if slot == "Promo":
            q = q.filter(db.Product.price.isnot(None), db.Product.price > 0)
        candidates = q.all()

    # Random shuffle + limit, so the strategist sees a fresh subset each day.
    random.shuffle(candidates)
    return candidates[:limit]


def _recent_topics() -> list[str]:
    """Return last 7 days' post topic titles (from drafts/posts)."""
    week_ago = datetime.utcnow() - timedelta(days=7)
    with db.session_scope() as s:
        rows = (
            s.query(db.PostDraft)
            .filter(db.PostDraft.created_at >= week_ago)
            .filter(db.PostDraft.status.in_(("approved", "published")))
            .order_by(db.PostDraft.created_at.desc())
            .all()
        )
    titles = []
    for r in rows:
        # We don't store a separate title; use the first line of body_text.
        first = (r.body_text or "").split("\n", 1)[0][:60]
        if first:
            titles.append(first)
    return titles


def _format_product_candidates(products: list[db.Product]) -> str:
    if not products:
        return "(კატალოგი ცარიელია)"
    lines = []
    for p in products:
        price_str = f"{p.price:g} ₾" if p.price else "—"
        # Keep each line short for the prompt.
        name = p.name[:50] if p.name else "(უსახელო)"
        lines.append(f"- `{p.code}` · {name} · {price_str}")
    return "\n".join(lines)


def _format_memories(memories: list[db.Memory]) -> str:
    if not memories:
        return "(ჯერ მახსოვრობა ცარიელია)"
    return "\n".join(f"- [{m.category}] {m.content}" for m in memories)


def pick_topic(gemini: GeminiClient, slot: str) -> TopicBrief:
    """Stage 1 — Gemini returns a topic brief as JSON.

    Switched from Claude to Gemini Flash (~10x cheaper) — JSON-mode output is
    clean and structured enough for this picker task. See plan
    `elegant-waddling-brook.md` (2026-06).
    """
    today = date.today()
    products = _gather_product_candidates(slot, PRODUCT_CANDIDATES_LIMIT)
    memories = db.list_memories()

    user_prompt = prompts.TOPIC_STRATEGIST_USER_TEMPLATE.format(
        today=today.isoformat(),
        weekday_ka=_WEEKDAYS_KA[today.weekday()],
        slot=slot,
        slot_description=brand.SLOT_DESCRIPTIONS.get(slot, "")[:120],
        season_hint=_season_hint_for(today.month),
        recent_topics="\n".join(f"- {t}" for t in _recent_topics()) or "(ცარიელია)",
        product_candidates=_format_product_candidates(products),
        memories_block=_format_memories(memories),
    )

    response = gemini.generate_json(
        prompts.TOPIC_STRATEGIST_SYSTEM,
        user_prompt,
        operation="post_strategist",
        max_tokens=600,
    )
    raw = ClaudeClient.strip_json_fences(response.text)  # belt-and-suspenders: strip any fences
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log.error("topic_strategist_bad_json", raw_preview=raw[:200])
        raise RuntimeError("Strategist returned malformed JSON for topic brief") from e

    return TopicBrief(
        calendar_slot=data.get("calendar_slot", slot),
        post_format=data.get("format", "Product Spotlight"),
        featured_product_code=data.get("featured_product_code"),
        topic_title=data.get("topic_title", ""),
        angle=data.get("angle", ""),
        hook_style=data.get("hook_style", "descriptive"),
        target_word_count=int(data.get("target_word_count", 20)),
        cta=data.get("cta", "გვითხარი რა გჭირდება"),
    )


# ─── Stage 2: write post (Gemini) ────────────────────────────────────────────


def _format_product_block(product: Optional[db.Product]) -> str:
    if product is None:
        return "მიმდინარე პოსტში პროდუქცია არ ფიგურირებს."
    price_str = f"{product.price:g} ₾" if product.price else "ფასი არ არის ცნობილი — ნუ ახსენებ ფასს."
    stock_str = "მარაგშია" if product.stock_qty > 0 else "ამოწურულია — ნუ ამბობ 'გვაქვს' ან 'მარაგში'."
    return (
        f"ფეიჩერ პროდუქცია:\n"
        f"- კოდი: `{product.code}`\n"
        f"- სახელწოდება: {product.name}\n"
        f"- ფასი: {price_str}\n"
        f"- მარაგი: {stock_str}\n"
    )


def write_post(
    gemini: GeminiClient,
    brief: TopicBrief,
    product: Optional[db.Product],
    previous_violations: Optional[list[guardrails.Violation]] = None,
) -> tuple[str, list[str]]:
    """Stage 2 — Gemini writes body + hashtags. Returns (body_text, hashtags)."""
    today = date.today()
    memories = db.list_memories()

    user_prompt = prompts.POST_WRITER_USER_TEMPLATE.format(
        today=today.isoformat(),
        slot=brief.calendar_slot,
        post_format=brief.post_format,
        topic_title=brief.topic_title,
        angle=brief.angle,
        hook_style=brief.hook_style,
        target_word_count=brief.target_word_count,
        cta=brief.cta,
        product_block=_format_product_block(product),
        memories_block=_format_memories(memories),
    )

    if previous_violations:
        violation_summary = "\n".join(
            f"- [{v.rule}] {v.detail}" for v in previous_violations
        )
        user_prompt += (
            "\n\n⚠️ წინა მცდელობამ ჩაიჭრა ამ მიზეზებით — გასწორდი:\n"
            + violation_summary
        )

    response = gemini.generate_multi(
        system=prompts.POST_WRITER_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
        operation="post_writer",
        max_tokens=1500,
    )

    # Gemini sometimes wraps JSON in ```json fences too.
    raw = response.text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3].rstrip()
    raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log.error("post_writer_bad_json", raw_preview=raw[:200])
        raise RuntimeError("Gemini returned malformed JSON for post writer") from e

    body = str(data.get("body_text", "")).strip()
    tags = data.get("hashtags", [])
    if not isinstance(tags, list):
        tags = []
    return body, [str(t) for t in tags if t]


# ─── Stage 3: validate ───────────────────────────────────────────────────────


def _make_draft(
    body: str, tags: list[str], product: Optional[db.Product]
) -> guardrails.Draft:
    return guardrails.Draft(
        body_text=body,
        hashtags=tags,
        featured_product_code=product.code if product else None,
        featured_product_price=product.price if product else None,
        featured_product_stock_qty=product.stock_qty if product else 0,
    )


def validate_post(
    gemini: GeminiClient, body: str, hashtags: list[str], slot: str
) -> tuple[bool, list[guardrails.Violation], Optional[str]]:
    """Stage 3b — Gemini second-pass review (was Claude pre-2026-06).

    Returns (approved, list_of_violations, optional_polished_text).
    Violations here are STYLISTIC issues the regex layer misses (marketing
    speak, audience mismatch, weak hook). Switched to Gemini JSON mode for
    ~10x cost reduction.
    """
    audience = "B2B (ვულკანიზაცია/სამრეცხაო მფლობელი)" if slot == "B2B" else "B2C (DIY მძღოლი)"
    user_prompt = prompts.POST_VALIDATOR_USER_TEMPLATE.format(
        body_text=body,
        hashtags=", ".join(hashtags),
        slot=slot,
        audience=audience,
    )
    response = gemini.generate_json(
        prompts.POST_VALIDATOR_SYSTEM,
        user_prompt,
        operation="post_validator",
        # 1500 is needed because the validator emits a JSON array of issues
        # plus an optional polished_text rewrite of the whole post.
        max_tokens=1500,
    )
    raw = ClaudeClient.strip_json_fences(response.text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.error("post_validator_bad_json", raw_preview=raw[:200])
        return True, [], None

    approved = bool(data.get("approved", True))
    issues_data = data.get("issues") or []
    polished = data.get("polished_text") or None

    violations: list[guardrails.Violation] = []
    for it in issues_data:
        if not isinstance(it, dict):
            continue
        sev = (
            guardrails.Severity.BLOCK
            if str(it.get("severity", "warn")).lower() == "block"
            else guardrails.Severity.WARN
        )
        violations.append(
            guardrails.Violation(
                rule=str(it.get("rule", "tone")),
                severity=sev,
                detail=str(it.get("detail", "")),
            )
        )
    return approved, violations, polished


# ─── Stage 4: resolve image ──────────────────────────────────────────────────


def resolve_image_path(product_code: Optional[str]) -> tuple[Optional[str], str]:
    """Look for a manually uploaded photo at data/photos/{code}.{jpg,jpeg,png}.

    This is the FIRST source the generator tries — the founder dropping real
    photos here is always preferred over auto-search.
    """
    if not product_code:
        return None, "none"
    for ext in ("jpg", "jpeg", "png"):
        candidate = config.PHOTOS_DIR / f"{product_code}.{ext}"
        if candidate.exists():
            return str(candidate), "real"
    return None, "none"


# Cache dir for auto-rendered text cards. One file per featured product code,
# overwritten if the product price changes (e.g. after a /reimport).
_TEXT_CARD_DIR = config.DATA_DIR / "rendered_cards"
# Cache dir for found-photo + marketing-overlay output.
_OVERLAY_DIR = config.DATA_DIR / "overlaid_photos"


def render_text_card_for_product(
    product_code: str, product_name: str, price: Optional[float]
) -> str:
    """Render a branded text card for the given product, return the path."""
    _TEXT_CARD_DIR.mkdir(parents=True, exist_ok=True)
    output_path = _TEXT_CARD_DIR / f"{product_code}.png"
    image_gen.render_for_product(
        product_code=product_code,
        product_name=product_name,
        price=price,
        output_path=output_path,
    )
    return str(output_path)


def find_and_overlay_photo(
    product_code: str, product_name: str, price: Optional[float]
) -> Optional[str]:
    """Web-search for a product photo, apply marketing overlay, return the path.

    Returns None if the search finds nothing usable. The caller falls back
    to render_text_card_for_product in that case.

    Two-step caching:
      - Raw search hit cached to data/found_photos/{code}.jpg (forever)
      - Overlaid version cached to data/overlaid_photos/{code}.jpg (re-rendered
        if price changes, since the badge is part of the overlay)
    """
    raw = photo_finder.find_product_photo(product_code, product_name)
    if raw is None:
        return None

    _OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
    overlaid = _OVERLAY_DIR / f"{product_code}.jpg"
    try:
        image_gen.apply_marketing_overlay(
            source_path=raw,
            output_path=overlaid,
            product_name=product_name,
            price=price,
        )
    except Exception:
        log.exception("marketing_overlay_failed", code=product_code)
        return None
    return str(overlaid)


# ─── Pipeline entry point ────────────────────────────────────────────────────


def _load_product(code: Optional[str]) -> Optional[db.Product]:
    if not code:
        return None
    with db.session_scope() as s:
        p = s.get(db.Product, code)
        if p is not None:
            s.expunge(p)
        return p


def generate_draft_for_slot(
    slot: Optional[str] = None,
    *,
    run_validator: bool = False,
) -> GeneratedPost:
    """Full pipeline. Returns a GeneratedPost with optional violations.

    `run_validator` defaults to False (2026-06): the LLM second-pass review
    only catches stylistic issues — regex guardrails already block real
    safety problems. Skipping saves 50% of the post-generation API budget.
    Pass True to opt in (e.g. when piloting a new prompt).
    """
    cfg = config.load()
    gemini = GeminiClient(cfg)

    chosen_slot = slot or _slot_for_today()
    log.info("generator_start", slot=chosen_slot)

    # ─── 1. Pick topic ──
    brief = pick_topic(gemini, chosen_slot)
    product = _load_product(brief.featured_product_code)
    log.info(
        "topic_picked",
        slot=brief.calendar_slot,
        format=brief.post_format,
        product=brief.featured_product_code,
        title=brief.topic_title,
    )

    # ─── 2. Write + 3. Validate (loop up to N retries) ──
    body, hashtags = "", []
    violations: list[guardrails.Violation] = []
    polished: Optional[str] = None

    for attempt in range(MAX_REGENERATION_RETRIES + 1):
        body, hashtags = write_post(gemini, brief, product, previous_violations=violations or None)

        # 3a — regex guardrails (cheap, deterministic).
        draft = _make_draft(body, hashtags, product)
        violations = guardrails.validate(draft)

        # 3b — Gemini tone validator (optional, off by default).
        if run_validator:
            approved, llm_issues, polished_text = validate_post(
                gemini, body, hashtags, chosen_slot
            )
            violations.extend(llm_issues)
            polished = polished_text

        log.info(
            "validation_pass",
            attempt=attempt + 1,
            total_violations=len(violations),
            blocking=sum(1 for v in violations if v.severity is guardrails.Severity.BLOCK),
        )

        # If Claude already gave us a clean polished rewrite, apply it.
        if polished and not guardrails.has_blocking_violations(violations):
            body = polished
            polished = None
            break

        if not guardrails.has_blocking_violations(violations):
            break  # accepted

        # Else: loop with the violations included in the prompt next time.

    # ─── 4. Image — three-tier hierarchy ──
    # Tier 1: founder's manually uploaded photo (data/photos/{code}.jpg)
    image_path, image_source = resolve_image_path(brief.featured_product_code)

    # Tier 2: web-found real product photo + marketing overlay.
    # Skipped if no featured product (e.g. BTS or LITE slot).
    if image_path is None and product is not None:
        try:
            overlay_path = find_and_overlay_photo(
                product_code=product.code,
                product_name=product.name,
                price=product.price,
            )
            if overlay_path:
                image_path = overlay_path
                image_source = "found_overlay"
        except Exception:
            log.exception("find_and_overlay_failed")

    # Tier 3: branded text card. Always succeeds when product info exists.
    if image_path is None and product is not None:
        try:
            image_path = render_text_card_for_product(
                product_code=product.code,
                product_name=product.name,
                price=product.price,
            )
            image_source = "text_card"
        except Exception:
            log.exception("text_card_render_failed")

    return GeneratedPost(
        slot=chosen_slot,
        body_text=body,
        hashtags=hashtags,
        cta=brief.cta,
        featured_product_code=product.code if product else None,
        featured_product_name=product.name if product else None,
        featured_product_price=product.price if product else None,
        image_path=image_path,
        image_source=image_source,
        violations=violations,
        validator_polish=polished,
    )


# ─── CLI for smoke-testing ───────────────────────────────────────────────────


def _print_post(post: GeneratedPost) -> None:
    bar = "─" * 64
    print(bar)
    print(f"SLOT: {post.slot}")
    if post.featured_product_code:
        price = f"{post.featured_product_price:g} ₾" if post.featured_product_price else "—"
        print(f"PRODUCT: [{post.featured_product_code}] {post.featured_product_name} ({price})")
    else:
        print("PRODUCT: (none)")
    print(f"IMAGE: {post.image_path or '(none)'}  source={post.image_source}")
    print(bar)
    print(post.body_text)
    print(bar)
    print("HASHTAGS:", " ".join(post.hashtags))
    print(f"CTA: {post.cta}")
    print(bar)
    if post.violations:
        print("VIOLATIONS:")
        print(guardrails.format_violations(post.violations))
    else:
        print("✅ ყველა შემოწმება გაიარა")
    print(bar)


def main(argv: list[str]) -> int:
    from src.logging_setup import configure as configure_logging

    parser = argparse.ArgumentParser(description="Generate a Facebook post draft (no publish).")
    parser.add_argument(
        "--slot",
        choices=["B2B", "B2C", "EDU", "BTS", "LITE", "Promo"],
        help="Force a calendar slot (default: today's).",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip Claude validator (faster, cheaper).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print result; don't persist to post_drafts.",
    )
    args = parser.parse_args(argv[1:])

    configure_logging("INFO")
    cfg = config.load()
    db.init_engine(cfg.database_url)

    try:
        post = generate_draft_for_slot(slot=args.slot, run_validator=not args.no_validate)
    except Exception as e:
        log.exception("generator_failed")
        print(f"❌ generation failed: {e}", file=sys.stderr)
        return 1

    _print_post(post)
    if not args.dry_run:
        _persist_draft(post)
        print("💾 saved to post_drafts (status=pending)")
    return 0


def _persist_draft(post: GeneratedPost) -> None:
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


if __name__ == "__main__":
    sys.exit(main(sys.argv))
