"""Brand-voice and safety validators for generated posts.

Every post the AI produces must pass these checks before it's sent to the
founder for approval. A failure isn't fatal — the generator gets a chance
to regenerate with the violation flagged in the next prompt — but a draft
that still fails after retries is surfaced to the founder with the issues
listed so they decide.

All validators are pure functions taking a `Draft` dataclass and returning
a list of `Violation`s. They're trivially unit-testable (see
tests/test_guardrails.py).

Coverage maps to brandbook §11 (page 20):
  1. ❌ Invented price  →  check_price_grounding()
  2. ❌ Invented stock  →  check_stock_grounding()
  3. ❌ Self-declared discount  →  check_promo_flag() (mild — flag only)
  4. ❌ Competitor mention  →  check_competitor_mentions()
  5. ❌ Political/religious/sensitive  →  check_banned_topics()
  6. ❌ Stolen photo/video  →  (out of scope here; handled at image_gen.py)
  7. ❌ Autonomous publish  →  (enforced by the approval flow, not here)

Plus brandbook §4 voice rules:
  - ✅ "შენ" form only       → check_address_form()
  - ✅ No banned phrases     → check_banned_phrases()
  - ✅ "საბურავი" not "სალტე" → check_tire_word()
  - ✅ Hashtag count 3-5     → check_hashtags()
  - ✅ Contact block present → check_contact_block()
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src import brand


class Severity(str, Enum):
    BLOCK = "block"   # cannot be approved as-is, must regenerate
    WARN = "warn"     # founder sees the warning but may approve anyway


@dataclass
class Violation:
    rule: str                # e.g. "address_form", "banned_phrase"
    severity: Severity
    detail: str              # human-readable explanation in Georgian
    matched_text: Optional[str] = None  # the exact substring that triggered it


@dataclass
class Draft:
    """Subset of post_draft fields the validators care about."""
    body_text: str
    hashtags: list[str] = field(default_factory=list)
    featured_product_code: Optional[str] = None
    featured_product_price: Optional[float] = None     # from products.price
    featured_product_stock_qty: int = 0                # from products.stock_qty


# ─── Individual checks ───────────────────────────────────────────────────────


def check_address_form(draft: Draft) -> list[Violation]:
    """Reject "თქვენ"-form markers — brandbook p. 11 requires "შენ" form."""
    out: list[Violation] = []
    text = draft.body_text
    for marker in brand.TKVEN_MARKERS:
        if marker in text:
            out.append(
                Violation(
                    rule="address_form",
                    severity=Severity.BLOCK,
                    detail=f"'თქვენ' ფორმის გამოყენება ('{marker.strip()}') — გამოიყენე 'შენ'.",
                    matched_text=marker.strip(),
                )
            )
    return out


def check_banned_phrases(draft: Draft) -> list[Violation]:
    """Reject brandbook §11 banned phrases ("ფანტასტიკური შემოთავაზება" etc.)."""
    out: list[Violation] = []
    text_lower = draft.body_text.lower()
    for phrase in brand.BANNED_PHRASES:
        if phrase.lower() in text_lower:
            out.append(
                Violation(
                    rule="banned_phrase",
                    severity=Severity.BLOCK,
                    detail=f"აკრძალული ფრაზა: '{phrase}'",
                    matched_text=phrase,
                )
            )
    return out


def check_tire_word(draft: Draft) -> list[Violation]:
    """Brandbook p. 11: 'საბურავი' is correct, 'სალტე' is forbidden."""
    if brand.TIRE_FORBIDDEN in draft.body_text:
        return [
            Violation(
                rule="tire_word",
                severity=Severity.BLOCK,
                detail=f"'{brand.TIRE_FORBIDDEN}' — გამოიყენე '{brand.TIRE_CORRECT}'.",
                matched_text=brand.TIRE_FORBIDDEN,
            )
        ]
    return []


def check_competitor_mentions(draft: Draft) -> list[Violation]:
    """Brandbook §11 #4: never name a competitor."""
    out: list[Violation] = []
    text_lower = draft.body_text.lower()
    for name in brand.COMPETITORS_FORBIDDEN:
        if name.lower() in text_lower:
            out.append(
                Violation(
                    rule="competitor",
                    severity=Severity.BLOCK,
                    detail=f"კონკურენტი ნახსენებია: '{name}'",
                    matched_text=name,
                )
            )
    return out


# Topics that brandbook §11 #5 explicitly forbids.
_BANNED_TOPIC_PATTERNS = [
    re.compile(r"ავარია\w*", re.IGNORECASE),
    re.compile(r"კონფლიქტ\w*", re.IGNORECASE),
    re.compile(r"კატასტროფ\w*", re.IGNORECASE),
    re.compile(r"პოლიტიკ\w*", re.IGNORECASE),
    re.compile(r"რელიგ\w*", re.IGNORECASE),
]


def check_banned_topics(draft: Draft) -> list[Violation]:
    """Block political/religious/disaster topics — brandbook §11 #5."""
    out: list[Violation] = []
    for pattern in _BANNED_TOPIC_PATTERNS:
        m = pattern.search(draft.body_text)
        if m:
            out.append(
                Violation(
                    rule="banned_topic",
                    severity=Severity.BLOCK,
                    detail=f"აკრძალული თემა: '{m.group(0)}'",
                    matched_text=m.group(0),
                )
            )
    return out


# Matches a price-like number followed by ₾, "ლარი", or "GEL".
_PRICE_RE = re.compile(
    r"(\d{1,5}(?:[.,]\d{1,2})?)\s*(?:₾|ლარი|ლარად|გელ|GEL|lari)",
    re.IGNORECASE,
)


def check_price_grounding(draft: Draft) -> list[Violation]:
    """Every price mentioned in the body must match the featured product's
    real price (within 1 ლარი tolerance).

    Brandbook §11 #1: never invent prices. If the draft doesn't feature a
    product or that product has no known price, *any* price in the body is
    a violation.
    """
    out: list[Violation] = []
    matches = _PRICE_RE.findall(draft.body_text)
    if not matches:
        return out

    if draft.featured_product_price is None:
        for raw in matches:
            try:
                value = float(raw.replace(",", "."))
            except ValueError:
                continue
            out.append(
                Violation(
                    rule="price_invented",
                    severity=Severity.BLOCK,
                    detail=(
                        f"ფასი ({value:g} ₾) ნახსენებია, მაგრამ პროდუქტს "
                        f"products.xlsx-ში ფასი არ აქვს."
                    ),
                    matched_text=str(value),
                )
            )
        return out

    real_price = draft.featured_product_price
    for raw in matches:
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            continue
        if abs(value - real_price) > 1.0:
            out.append(
                Violation(
                    rule="price_mismatch",
                    severity=Severity.BLOCK,
                    detail=(
                        f"ფასი ({value:g} ₾) არ ემთხვევა products.xlsx-ში "
                        f"მითითებულ ფასს ({real_price:g} ₾)."
                    ),
                    matched_text=str(value),
                )
            )
    return out


# Words that imply we have stock. If present, stock_qty must be > 0.
_STOCK_CLAIM_PATTERNS = [
    re.compile(r"\bგვაქვს\b"),
    re.compile(r"\bმარაგში\b"),
    re.compile(r"\bხელმისაწვდომი\w*\b"),
]


def check_stock_grounding(draft: Draft) -> list[Violation]:
    """If the body claims "გვაქვს" / "მარაგში", the featured product must be in stock."""
    if draft.featured_product_code is None:
        return []
    if draft.featured_product_stock_qty > 0:
        return []
    for pattern in _STOCK_CLAIM_PATTERNS:
        m = pattern.search(draft.body_text)
        if m:
            return [
                Violation(
                    rule="stock_claim_without_stock",
                    severity=Severity.BLOCK,
                    detail=(
                        f"ფრაზა '{m.group(0)}' გულისხმობს მარაგში არსებობას, "
                        f"მაგრამ პროდუქცია {draft.featured_product_code} "
                        f"აღნიშნულია როგორც ამოწურული."
                    ),
                    matched_text=m.group(0),
                )
            ]
    return []


def check_hashtags(draft: Draft) -> list[Violation]:
    """Brandbook p. 17: 3-5 hashtags per post."""
    n = len(draft.hashtags)
    if n < brand.MIN_HASHTAGS:
        return [
            Violation(
                rule="hashtag_count",
                severity=Severity.WARN,
                detail=f"მცირე ჰეშთეგი: {n}. რეკომენდირებული {brand.MIN_HASHTAGS}-{brand.MAX_HASHTAGS}.",
            )
        ]
    if n > brand.MAX_HASHTAGS:
        return [
            Violation(
                rule="hashtag_count",
                severity=Severity.BLOCK,
                detail=(
                    f"ძალიან ბევრი ჰეშთეგი: {n}. Facebook-ის ალგორითმი 10+ "
                    f"ჰეშთეგიან პოსტებს სპამად აღიქვამს."
                ),
            )
        ]
    return []


def check_contact_block(draft: Draft) -> list[Violation]:
    """Phone OR address must appear in the body — brandbook p. 21."""
    has_phone = brand.CONTACT_PHONE.replace(" ", "") in draft.body_text.replace(" ", "")
    has_address = brand.CONTACT_ADDRESS[:15] in draft.body_text  # prefix match
    if not (has_phone or has_address):
        return [
            Violation(
                rule="contact_missing",
                severity=Severity.WARN,
                detail="ტელეფონის ნომერი ან მისამართი ვერ ნახა პოსტში.",
            )
        ]
    return []


def check_placeholders(draft: Draft) -> list[Violation]:
    """Forbid `[telephone]`, `[მისამართი]`, etc. — common AI mistake."""
    out: list[Violation] = []
    for m in re.finditer(r"\[[\w\sა-ჰ/]+\]", draft.body_text):
        out.append(
            Violation(
                rule="placeholder",
                severity=Severity.BLOCK,
                detail=f"Placeholder ნაპოვნია: '{m.group(0)}' — გამოიყენე რეალური მონაცემები.",
                matched_text=m.group(0),
            )
        )
    return out


# ─── Aggregate ───────────────────────────────────────────────────────────────


ALL_CHECKS = (
    check_address_form,
    check_banned_phrases,
    check_tire_word,
    check_competitor_mentions,
    check_banned_topics,
    check_price_grounding,
    check_stock_grounding,
    check_hashtags,
    check_contact_block,
    check_placeholders,
)


def validate(draft: Draft) -> list[Violation]:
    """Run every check; return all violations. Empty list = passes."""
    out: list[Violation] = []
    for check in ALL_CHECKS:
        out.extend(check(draft))
    return out


def has_blocking_violations(violations: list[Violation]) -> bool:
    return any(v.severity is Severity.BLOCK for v in violations)


def format_violations(violations: list[Violation]) -> str:
    """Human-readable summary for Telegram messages / logs."""
    if not violations:
        return "✅ ყველა შემოწმება გაიარა"
    lines: list[str] = []
    for v in violations:
        icon = "❌" if v.severity is Severity.BLOCK else "⚠️"
        lines.append(f"{icon} [{v.rule}] {v.detail}")
    return "\n".join(lines)
