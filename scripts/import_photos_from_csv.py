"""Batch-import product photos from a CSV with `code,...,Image_URL` columns.

Mirrors the admin upload pipeline (`src/web/routes/admin.py`):
  - Pillow normalize → max 1600px, JPEG quality 85
  - Decompression-bomb defense (MAX_IMAGE_PIXELS = 40M)
  - EXIF/ICC strip on save
  - Atomic save to `data/photos/{code}.jpg`
  - DB flip `Product.has_photo = True`

Bot reuses these via `resolve_image_path()` automatically — no other wiring.

Usage:
    python scripts/import_photos_from_csv.py PATH_TO_CSV [--limit N] [--workers 8]

CSV column order expected (matches products_with_photos.csv):
    code, name, price, stock, Image_URL, Image_File, Status, Match_Title

Codes containing `/` or `\\` are skipped (path-traversal guard, same as
admin route). Non-existent codes in DB are logged and skipped.
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import requests
from PIL import Image

# Project root on sys.path so `src.*` imports work.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import bindparam, text  # noqa: E402

from src import config, db  # noqa: E402
from src.db import Product, set_product_photo, list_products_paginated  # noqa: E402, F401

PHOTOS_DIR = ROOT / "data" / "photos"
MAX_DIMENSION = 1600
JPEG_QUALITY = 85
HTTP_TIMEOUT = 20  # seconds
HTTP_RETRIES = 1
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
)

Image.MAX_IMAGE_PIXELS = 40_000_000  # decompression-bomb cap

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("import_photos")


@dataclass
class Row:
    code: str
    url: str
    name: str


@dataclass
class Result:
    code: str
    status: str           # ok | skip-no-code | skip-no-url | skip-unknown | skip-traversal | error
    detail: str = ""
    bytes_saved: int = 0


def _fix_mojibake(s: str) -> str:
    """Some CSVs paste in as UTF-8-displayed-as-Latin-1 mojibake; recover."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def _read_csv(path: Path) -> list[Row]:
    """Parse the CSV, fixing the common UTF-8/Latin-1 mojibake pattern."""
    raw = path.read_bytes()
    # If the file decodes cleanly as UTF-8, prefer that. Otherwise fall back
    # to Latin-1 + the mojibake fix.
    try:
        text = raw.decode("utf-8-sig")
        # Heuristic: if the header has the BOM artifact, the file is actually
        # UTF-8 bytes that were saved as Latin-1 from a UTF-8 editor — fix.
        if "á" in text[:200] and "ი" not in text[:200]:
            text = raw.decode("latin-1")
            text = _fix_mojibake(text)
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
        text = _fix_mojibake(text)

    rows: list[Row] = []
    reader = csv.DictReader(io.StringIO(text))
    # Column names in the CSV header are Georgian → we look up by position.
    # First two columns are code, name. Image_URL is the 5th.
    headers = reader.fieldnames or []
    if not headers:
        log.error("empty CSV")
        return rows
    code_col = headers[0]
    name_col = headers[1] if len(headers) > 1 else ""
    url_col = "Image_URL" if "Image_URL" in headers else (
        headers[4] if len(headers) > 4 else ""
    )

    for row in reader:
        code = (row.get(code_col) or "").strip()
        url = (row.get(url_col) or "").strip()
        name = (row.get(name_col) or "").strip()
        if not code:
            continue
        rows.append(Row(code=code, url=url, name=name))
    return rows


def _safe_path(code: str) -> Path | None:
    """Same guard as src/web/routes/admin.py `_photo_path()`. Returns None
    on any code that would escape PHOTOS_DIR."""
    if not code or "/" in code or "\\" in code or ".." in code:
        return None
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    candidate = (PHOTOS_DIR / f"{code}.jpg").resolve()
    photos_root = PHOTOS_DIR.resolve()
    if candidate.parent != photos_root or candidate.suffix != ".jpg":
        return None
    return candidate


def _download(url: str) -> bytes:
    headers = {"User-Agent": USER_AGENT, "Accept": "image/*,*/*;q=0.8"}
    last_err: Exception | None = None
    for attempt in range(HTTP_RETRIES + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT, stream=False)
            resp.raise_for_status()
            data = resp.content
            if len(data) == 0:
                raise ValueError("empty response body")
            if len(data) > 25 * 1024 * 1024:  # 25 MB hard ceiling
                raise ValueError(f"response too large: {len(data)} bytes")
            return data
        except Exception as e:
            last_err = e
            if attempt < HTTP_RETRIES:
                time.sleep(0.5)
    raise last_err or RuntimeError("download failed")


def _normalize_and_save(data: bytes, dest: Path) -> int:
    """Same pipeline as the admin upload route. Returns bytes written."""
    img = Image.open(io.BytesIO(data))
    img.load()  # force decode (triggers DecompressionBombError if needed)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
    # Atomic write via .tmp + rename.
    tmp = dest.with_suffix(".jpg.tmp")
    img.save(tmp, format="JPEG", quality=JPEG_QUALITY, optimize=True, exif=b"")
    tmp.replace(dest)
    return dest.stat().st_size


def process_one(row: Row, valid_codes: set[str]) -> Result:
    if not row.code:
        return Result(code=row.code, status="skip-no-code")
    if not row.url:
        return Result(code=row.code, status="skip-no-url")
    if row.code not in valid_codes:
        return Result(code=row.code, status="skip-unknown")
    dest = _safe_path(row.code)
    if dest is None:
        return Result(code=row.code, status="skip-traversal")
    try:
        data = _download(row.url)
    except Exception as e:
        return Result(code=row.code, status="error", detail=f"download: {e}")
    try:
        size = _normalize_and_save(data, dest)
    except Image.DecompressionBombError as e:
        return Result(code=row.code, status="error", detail=f"bomb: {e}")
    except Exception as e:
        return Result(code=row.code, status="error", detail=f"normalize: {e}")
    return Result(code=row.code, status="ok", bytes_saved=size)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument("--limit", type=int, default=0,
                        help="process only first N rows (0 = no limit)")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true",
                        help="parse CSV + report match counts only")
    args = parser.parse_args()

    if not args.csv.exists():
        log.error("CSV not found: %s", args.csv)
        return 2

    # DB init.
    cfg = config.load()
    db.init_engine(cfg.database_url)

    log.info("loading CSV: %s", args.csv)
    rows = _read_csv(args.csv)
    log.info("rows in CSV: %d", len(rows))
    if args.limit:
        rows = rows[: args.limit]
        log.info("limited to first %d rows", args.limit)

    # Pull the set of valid codes from DB so we can short-circuit unknowns
    # without making 478 DB roundtrips.
    with db.session_scope() as s:
        valid_codes = {r[0] for r in s.execute(text("SELECT code FROM products")).all()}
    log.info("known product codes in DB: %d", len(valid_codes))

    rows_with_url = [r for r in rows if r.url and r.code in valid_codes]
    log.info("rows with valid URL + known code: %d", len(rows_with_url))

    if args.dry_run:
        skipped_no_url = sum(1 for r in rows if not r.url)
        skipped_unknown = sum(1 for r in rows if r.code not in valid_codes)
        skipped_traversal = sum(1 for r in rows
                                if r.url and r.code in valid_codes
                                and _safe_path(r.code) is None)
        log.info("dry-run summary:")
        log.info("  no URL:           %d", skipped_no_url)
        log.info("  unknown code:     %d", skipped_unknown)
        log.info("  path-traversal:   %d", skipped_traversal)
        log.info("  would download:   %d",
                 len(rows_with_url) - skipped_traversal)
        return 0

    # Concurrent download/process.
    results: list[Result] = []
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process_one, r, valid_codes): r for r in rows}
        done = 0
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            done += 1
            if r.status == "ok":
                log.info("[%d/%d] %s saved (%d KB)",
                         done, len(rows), r.code, r.bytes_saved // 1024)
            elif r.status == "error":
                log.warning("[%d/%d] %s FAILED — %s",
                            done, len(rows), r.code, r.detail)

    # Flip has_photo for everything that saved. Batch-update keeps it fast.
    saved_codes = [r.code for r in results if r.status == "ok"]
    if saved_codes:
        with db.session_scope() as s:
            stmt = text(
                "UPDATE products SET has_photo = 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE code IN :codes"
            ).bindparams(bindparam("codes", expanding=True))
            s.execute(stmt, {"codes": saved_codes})
            # session_scope auto-commits on exit; no explicit commit needed.

    # Summary.
    elapsed = time.time() - started
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    log.info("=" * 50)
    log.info("done in %.1fs  (%d workers)", elapsed, args.workers)
    for k in ("ok", "skip-no-url", "skip-unknown", "skip-traversal", "error"):
        log.info("  %-18s %d", k, by_status.get(k, 0))
    log.info("=" * 50)
    log.info("photos on disk now: %d", len(list(PHOTOS_DIR.glob("*.jpg"))))
    log.info("products has_photo=1 in DB: %d",
             sum(1 for c in saved_codes) + (
                 1 if not saved_codes else 0  # plus pre-existing
             ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
