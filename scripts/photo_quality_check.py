"""AI-vision filter for product photos.

Walks data/photos/*.jpg, asks Gemini Vision whether each image actually
depicts the product it's named after, and moves obvious mismatches to
data/photos/_quarantine/ (NOT deleted — recoverable).

Background: photos came from automated DuckDuckGo image search, which
returned plenty of false positives (a slipper image landed on a tire-repair
product, etc.). This script is the cleanup pass.

Usage:
    python scripts/photo_quality_check.py --dry-run              # analyze only
    python scripts/photo_quality_check.py --limit 20             # test on 20
    python scripts/photo_quality_check.py                        # do it (threshold 70)
    python scripts/photo_quality_check.py --threshold 60         # stricter

Cost: ~$0.0004/photo via gemini-3.5-flash. 341 photos ≈ $0.14 total.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from pathlib import Path

from google import genai
from google.genai import types as genai_types

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import config, db  # noqa: E402
from src.logging_setup import configure as configure_logging  # noqa: E402
from src.logging_setup import get_logger  # noqa: E402

log = get_logger(__name__)

PHOTOS_DIR = ROOT / "data" / "photos"
QUARANTINE_DIR = PHOTOS_DIR / "_quarantine"
REPORT_PATH = ROOT / "data" / "photo_quality_report.csv"

PROMPT_SYSTEM = (
    "You are reviewing a product photo for Uygun Georgia — a Batumi-based "
    "supplier of tire vulcanization materials (patches, glues, valves, tubes), "
    "car-wash chemicals, automotive lubricants, antifreeze, brake fluid, and "
    "related auto-service consumables. The catalog also includes some basic "
    "shop tools (knives, hammers, jacks, scales, gloves)."
)

PROMPT_USER_TEMPLATE = (
    "Product code: {code}\n"
    "Product name (Georgian/Turkish mix): {name}\n"
    "Category: {category}\n\n"
    "Question: Does the IMAGE depict this product, or at least an item from "
    "the correct product category for an auto-service supplier?\n\n"
    "Return STRICT JSON with these keys:\n"
    '  "match": boolean — true if the image fits, false if obviously wrong\n'
    '  "confidence": integer 0-100 — how sure you are\n'
    '  "image_subject": short string — what the image actually depicts\n'
    '  "reason": short string — why match/no match\n\n'
    "Rules:\n"
    "- A slipper, shoe, food, animal, or unrelated object = match:false, confidence>=90\n"
    "- Generic stock photo of the right product TYPE = match:true (even if "
    "brand differs)\n"
    "- Auto parts that are NOT what the supplier sells (engines, brake pads, "
    "complete tires) = match:false unless name explicitly mentions them\n"
    "- If unsure between right category but wrong specific product = match:true, "
    "confidence around 50\n"
)


def analyze_photo(
    client: genai.Client,
    model: str,
    image_path: Path,
    code: str,
    name: str,
    category: str | None,
) -> dict | None:
    """Returns parsed JSON dict or None on failure."""
    image_bytes = image_path.read_bytes()
    user_prompt = PROMPT_USER_TEMPLATE.format(
        code=code, name=name, category=category or "(unknown)"
    )
    contents = [
        genai_types.Content(
            role="user",
            parts=[
                genai_types.Part.from_bytes(
                    data=image_bytes, mime_type="image/jpeg"
                ),
                genai_types.Part.from_text(text=user_prompt),
            ],
        )
    ]
    cfg = genai_types.GenerateContentConfig(
        system_instruction=PROMPT_SYSTEM,
        max_output_tokens=400,
        temperature=0.2,
        thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
        response_mime_type="application/json",
    )
    try:
        response = client.models.generate_content(
            model=model, contents=contents, config=cfg
        )
        return json.loads(response.text or "{}")
    except Exception as exc:
        log.warning("gemini_call_failed", code=code, error=str(exc))
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze and report, but don't move any files or touch DB.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process only the first N photos (0 = all).",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=70,
        help="Confidence threshold for quarantine (default 70).",
    )
    args = parser.parse_args()

    configure_logging()
    cfg = config.load()
    db.init_engine(cfg.database_url)

    client = genai.Client(api_key=cfg.google_api_key)
    model = cfg.gemini_text_model  # 3.5-flash handles vision

    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)

    photos = sorted(PHOTOS_DIR.glob("*.jpg"))
    if args.limit:
        photos = photos[: args.limit]

    print(
        f"📸 {len(photos)} photos to analyze "
        f"({'DRY RUN' if args.dry_run else 'LIVE'}, "
        f"threshold={args.threshold}, model={model})\n"
    )

    rows: list[dict] = []
    quarantine_codes: list[str] = []
    skipped = errors = 0

    for i, photo in enumerate(photos, 1):
        code = photo.stem
        product = db.get_product(code) if hasattr(db, "get_product") else None
        if product is None:
            with db.session_scope() as s:
                product = s.query(db.Product).filter_by(code=code).first()
                name = product.name if product else None
                category = product.category if product else None
        else:
            name = product.name
            category = product.category

        if not name:
            print(f"  [{i:>3}/{len(photos)}] {code:<10} ⊘ no DB record, skipping")
            skipped += 1
            continue

        result = analyze_photo(client, model, photo, code, name, category)
        if result is None:
            errors += 1
            print(f"  [{i:>3}/{len(photos)}] {code:<10} ⚠ gemini error")
            continue

        match = bool(result.get("match", True))
        conf = int(result.get("confidence", 0))
        subject = (result.get("image_subject") or "")[:40]
        reason = (result.get("reason") or "")[:60]

        will_quarantine = (not match) and conf >= args.threshold
        marker = "🗑 " if will_quarantine else ("✓ " if match else "? ")
        print(
            f"  [{i:>3}/{len(photos)}] {code:<10} {marker} "
            f"conf={conf:>3}  subj={subject!r:<42}  "
            f"{name[:30]}"
        )

        rows.append(
            {
                "code": code,
                "name": name,
                "category": category or "",
                "match": match,
                "confidence": conf,
                "image_subject": subject,
                "reason": reason,
                "quarantined": will_quarantine and not args.dry_run,
            }
        )

        if will_quarantine and not args.dry_run:
            shutil.move(str(photo), str(QUARANTINE_DIR / photo.name))
            quarantine_codes.append(code)

        time.sleep(0.3)  # gentle pacing — gemini free tier ≈ 15 RPM

    # ─── DB sync ─────────────────────────────────────────────────────────────
    if quarantine_codes and not args.dry_run:
        with db.session_scope() as s:
            s.query(db.Product).filter(
                db.Product.code.in_(quarantine_codes)
            ).update({db.Product.has_photo: False}, synchronize_session=False)
        print(f"\n💾 DB updated: has_photo=False for {len(quarantine_codes)} products")

    # ─── CSV report ──────────────────────────────────────────────────────────
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "code",
                "name",
                "category",
                "match",
                "confidence",
                "image_subject",
                "reason",
                "quarantined",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    n_mismatch = sum(1 for r in rows if not r["match"])
    n_low_conf = sum(1 for r in rows if not r["match"] and r["confidence"] < args.threshold)

    print(
        f"\n📊 Summary:\n"
        f"  analyzed:  {len(rows)}\n"
        f"  skipped:   {skipped}  (no DB record)\n"
        f"  errors:    {errors}\n"
        f"  mismatch:  {n_mismatch}  (low-conf borderline: {n_low_conf})\n"
        f"  quarantined: {len(quarantine_codes)}  "
        f"{'(DRY RUN — files untouched)' if args.dry_run else f'→ {QUARANTINE_DIR}'}\n"
        f"\n📄 Full report: {REPORT_PATH}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
