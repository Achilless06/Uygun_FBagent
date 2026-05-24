"""Image generation for Facebook posts.

Three pathways (one is used per post, in priority order):

  1. **Real photo**   — `data/photos/{product_code}.{jpg,jpeg,png}` exists.
                        Resolved by generator.resolve_image_path(); this module
                        just composes a branded overlay on top if requested.

  2. **Branded text card** — PIL renders a square card with brand colors,
                              logo (if present), product name, price, and
                              the contact strip. Zero API cost, deterministic.

  3. **Gemini image generation** — only if the founder explicitly approves
                                    via the Telegram confirmation flow
                                    (Phase 4). Stubbed here.

Sizes follow brandbook p. 16:
  - Square (default):   1080×1080
  - Portrait:           1080×1350
  - Stories:            1080×1920

Brand colors (brandbook p. 8):
  - UYGUN_RED:  #BC1215  (accent — 10%)
  - DEEP_BLACK: #0F0F0F  (text/structure — 30%)
  - PURE_WHITE: #FFFFFF  (canvas — 60%)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from src import brand, config
from src.logging_setup import get_logger

log = get_logger(__name__)

# Font selection — bundled-in-repo first (works locally + on Railway), then
# system fonts as fallback. NotoSansGeorgian is the one we ship: it handles
# Georgian, Latin, digits AND the ₾ symbol in one TTF. Earlier we used the
# macOS-only SFGeorgian.ttf which only had Georgian glyphs and rendered digits
# / Latin as box placeholders ("≡≡≡").
_REPO_FONT_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "fonts"
_FONT_CANDIDATES = [
    _REPO_FONT_DIR / "NotoSansGeorgian.ttf",                      # bundled, primary
    Path("/usr/share/fonts/truetype/noto/NotoSansGeorgian-Bold.ttf"),  # Railway/Debian
    Path("/System/Library/Fonts/SFGeorgian.ttf"),                 # macOS fallback (Georgian only)
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"), # generic Linux fallback
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """Try the candidates in order; fall back to PIL's default if none work."""
    for path in _FONT_CANDIDATES:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default()


# Brandbook image dims.
SIZE_SQUARE = (1080, 1080)
SIZE_PORTRAIT = (1080, 1350)
SIZE_STORIES = (1080, 1920)


@dataclass
class CardInput:
    """Inputs needed to render a branded text card."""
    title: str               # short headline (product name or post hook)
    price: Optional[str] = None    # e.g. "20 ₾" or None
    subtitle: Optional[str] = None  # e.g. "ვულკანიზაცია · მარაგში"
    body: Optional[str] = None     # 1-2 lines of detail
    size: tuple[int, int] = SIZE_SQUARE


def _wrap_text(
    text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw
) -> list[str]:
    """Greedy word-wrap by pixel width. Returns list of lines."""
    if not text:
        return []
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = (" ".join(current + [word])).strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def render_text_card(card: CardInput, output_path: Path) -> Path:
    """Render a branded text-only card to PNG. Returns the path written."""
    width, height = card.size
    img = Image.new("RGB", (width, height), brand.PURE_WHITE)
    draw = ImageDraw.Draw(img)

    # ─── Layout ──
    # Top-right red accent strip (10% rule — the only place we use big red).
    accent_height = int(height * 0.04)
    draw.rectangle([(0, 0), (width, accent_height)], fill=brand.UYGUN_RED)
    # Bottom contact strip (black band, ~10% tall).
    contact_height = int(height * 0.12)
    contact_y = height - contact_height
    draw.rectangle([(0, contact_y), (width, height)], fill=brand.DEEP_BLACK)

    # ─── Logo (optional) — top-left, 12-15% of width per brandbook ──
    logo_path = config.BRAND_ASSETS_DIR / "logo.png"
    logo_size = int(width * 0.18)
    if logo_path.exists():
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo.thumbnail((logo_size, logo_size))
            img.paste(logo, (int(width * 0.04), accent_height + int(width * 0.03)), logo)
        except Exception:
            log.warning("logo_load_failed", path=str(logo_path))

    # ─── Title (big) ──
    title_font_size = int(width * 0.07)
    title_font = _load_font(title_font_size)
    title_max_width = int(width * 0.86)
    title_lines = _wrap_text(card.title, title_font, title_max_width, draw)[:3]
    title_y = int(height * 0.30)
    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        line_w = bbox[2] - bbox[0]
        x = (width - line_w) // 2
        draw.text((x, title_y), line, fill=brand.DEEP_BLACK, font=title_font)
        title_y += int(title_font_size * 1.2)

    # ─── Subtitle ──
    if card.subtitle:
        sub_font = _load_font(int(width * 0.035))
        bbox = draw.textbbox((0, 0), card.subtitle, font=sub_font)
        x = (width - (bbox[2] - bbox[0])) // 2
        draw.text((x, title_y + 8), card.subtitle, fill=brand.MID_GREY, font=sub_font)

    # ─── Price (big red accent box) ──
    if card.price:
        price_font = _load_font(int(width * 0.09))
        bbox = draw.textbbox((0, 0), card.price, font=price_font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        pad_x = int(width * 0.04)
        pad_y = int(height * 0.015)
        box_w = text_w + pad_x * 2
        box_h = text_h + pad_y * 2
        box_x = (width - box_w) // 2
        box_y = int(height * 0.62)
        draw.rectangle(
            [(box_x, box_y), (box_x + box_w, box_y + box_h)],
            fill=brand.UYGUN_RED,
        )
        draw.text(
            (box_x + pad_x, box_y + pad_y - int(text_h * 0.15)),
            card.price,
            fill=brand.PURE_WHITE,
            font=price_font,
        )

    # ─── Body (smaller, optional) ──
    if card.body:
        body_font = _load_font(int(width * 0.032))
        body_lines = _wrap_text(card.body, body_font, title_max_width, draw)[:3]
        body_y = int(height * 0.78)
        for line in body_lines:
            bbox = draw.textbbox((0, 0), line, font=body_font)
            line_w = bbox[2] - bbox[0]
            x = (width - line_w) // 2
            draw.text((x, body_y), line, fill=brand.MID_GREY, font=body_font)
            body_y += int(body_font.size * 1.3)

    # ─── Contact strip (bottom black band) ──
    contact_font = _load_font(int(width * 0.034))
    line1 = f"Tel: {brand.CONTACT_PHONE}    ·    {brand.CONTACT_ADDRESS}"
    line2 = brand.DELIVERY_NOTE
    for i, line in enumerate((line1, line2)):
        bbox = draw.textbbox((0, 0), line, font=contact_font)
        x = (width - (bbox[2] - bbox[0])) // 2
        y = contact_y + int(contact_height * 0.15) + i * int(contact_font.size * 1.4)
        draw.text((x, y), line, fill=brand.PURE_WHITE, font=contact_font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, format="PNG", optimize=True)
    log.info("text_card_rendered", path=str(output_path))
    return output_path


def render_for_product(
    product_code: str,
    product_name: str,
    price: Optional[float],
    output_path: Path,
    subtitle: Optional[str] = None,
) -> Path:
    """Convenience: render a product-spotlight text card."""
    card = CardInput(
        title=product_name,
        price=f"{price:g} ₾" if price else None,
        subtitle=subtitle or f"კოდი #{product_code}",
        body=None,
        size=SIZE_SQUARE,
    )
    return render_text_card(card, output_path)


def gemini_generate_image_stub(prompt: str, output_path: Path) -> Path:
    """Stub: Gemini image generation. Wired in Phase 4 after Telegram confirmation."""
    raise NotImplementedError(
        "Gemini image generation requires founder confirmation via Telegram. "
        "Wired in Phase 4 of the plan."
    )


# ─── Marketing overlay on a real photo ───────────────────────────────────────


def _fit_square(source_img: Image.Image, target_size: int) -> Image.Image:
    """Cover-fit the source photo into a square canvas: center-crop, then resize.

    "Cover-fit" = the photo fills the entire square; long sides get cropped.
    Preferred over "contain-fit" (letterboxing) because Facebook truncates
    images in the feed and white bars look amateurish.
    """
    sw, sh = source_img.size
    side = min(sw, sh)
    left = (sw - side) // 2
    top = (sh - side) // 2
    cropped = source_img.crop((left, top, left + side, top + side))
    return cropped.resize((target_size, target_size), Image.LANCZOS)


def apply_marketing_overlay(
    source_path: Path,
    output_path: Path,
    *,
    product_name: Optional[str] = None,
    price: Optional[float] = None,
    size: tuple[int, int] = SIZE_SQUARE,
) -> Path:
    """Take a real product photo and composite our brand frame on top.

    Layout (1080×1080):
      ┌──────────────────────────────────────────┐
      │ [red strip 4% tall]                      │
      ├──────────────────────────────────────────┤
      │                                          │
      │                                          │
      │              [photo, square-fit]         │
      │                                          │
      │                                  ┌────┐  │
      │                                  │price│  │
      │                                  │badge│  │
      │                                  └────┘  │
      ├──────────────────────────────────────────┤
      │ [black contact strip, ~12% tall]         │
      │   📞 phone   📍 address   🚚 delivery     │
      └──────────────────────────────────────────┘

    The red strip + price badge in red + contact strip in black gives ~10%
    red / 30% black / 60% photo, matching the brandbook's 60/30/10 rule.
    """
    width, height = size
    canvas = Image.new("RGB", (width, height), brand.PURE_WHITE)

    # ─── Photo (cover-fit) ──
    with Image.open(source_path) as source:
        source = source.convert("RGB")
        fitted = _fit_square(source, width)
        canvas.paste(fitted, (0, 0))

    draw = ImageDraw.Draw(canvas)

    # ─── Top red accent strip (brand frame) ──
    accent_height = int(height * 0.04)
    draw.rectangle([(0, 0), (width, accent_height)], fill=brand.UYGUN_RED)

    # ─── Top-left logo (optional) ──
    logo_path = config.BRAND_ASSETS_DIR / "logo.png"
    if logo_path.exists():
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo_w = int(width * 0.16)
            logo.thumbnail((logo_w, logo_w))
            # Anchor just below the red strip on the left.
            canvas.paste(logo, (int(width * 0.03), accent_height + int(width * 0.02)), logo)
        except Exception:
            log.warning("logo_load_failed", path=str(logo_path))

    # ─── Price badge (bottom-right, before the contact strip) ──
    contact_height = int(height * 0.13)
    contact_y = height - contact_height
    if price is not None and price > 0:
        price_text = f"{int(price)} ₾" if price == int(price) else f"{price:g} ₾"
        price_font = _load_font(int(width * 0.085))
        bbox = draw.textbbox((0, 0), price_text, font=price_font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        pad_x = int(width * 0.035)
        pad_y = int(height * 0.012)
        box_w = text_w + pad_x * 2
        box_h = text_h + pad_y * 2 + int(text_h * 0.2)
        # Anchor in the bottom-right, just above the contact strip.
        box_x = width - box_w - int(width * 0.04)
        box_y = contact_y - box_h - int(height * 0.025)
        # Subtle shadow for depth.
        shadow_offset = int(width * 0.006)
        draw.rectangle(
            [(box_x + shadow_offset, box_y + shadow_offset),
             (box_x + box_w + shadow_offset, box_y + box_h + shadow_offset)],
            fill=(0, 0, 0, 60),
        )
        draw.rectangle(
            [(box_x, box_y), (box_x + box_w, box_y + box_h)], fill=brand.UYGUN_RED
        )
        draw.text(
            (box_x + pad_x, box_y + pad_y - int(text_h * 0.1)),
            price_text,
            fill=brand.PURE_WHITE,
            font=price_font,
        )

    # ─── Bottom contact strip (black band) ──
    # NB: Noto Sans Georgian (our bundled font) doesn't include color emoji
    # glyphs, so we use text labels instead of 📞 / 📍 / 🚚. Looks cleaner
    # on the printed image anyway — the founder's brand frame, not a chat bubble.
    draw.rectangle([(0, contact_y), (width, height)], fill=brand.DEEP_BLACK)
    contact_font = _load_font(int(width * 0.032))
    line1 = f"Tel: {brand.CONTACT_PHONE}    ·    {brand.CONTACT_ADDRESS}"
    line2 = brand.DELIVERY_NOTE
    for i, line in enumerate((line1, line2)):
        bbox = draw.textbbox((0, 0), line, font=contact_font)
        x = (width - (bbox[2] - bbox[0])) // 2
        y = contact_y + int(contact_height * 0.18) + i * int(contact_font.size * 1.35)
        draw.text((x, y), line, fill=brand.PURE_WHITE, font=contact_font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="JPEG", quality=92, optimize=True)
    log.info(
        "marketing_overlay_applied",
        source=str(source_path),
        output=str(output_path),
        had_price=price is not None,
    )
    return output_path
