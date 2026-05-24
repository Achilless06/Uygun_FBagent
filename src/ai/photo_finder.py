"""Web-search a product photo by name, validate it, cache it.

When the founder hasn't uploaded a real photo to data/photos/{code}.jpg, the
generator falls back here. We:

  1. Strip the product name to its Latin/digit tokens (Georgian text doesn't
     help DDG find the actual product packaging — Turkish/English brand names do)
  2. Hit DDG image search with the cleaned query + a category hint
  3. Walk top results, downloading each and validating:
     - Min resolution 400×400
     - JPEG/PNG (not GIF/SVG)
     - Filesize 5 KB – 5 MB (filters placeholders + banner-sized images)
     - Aspect ratio between 0.5 and 2.0 (excludes hero strips)
  4. Save the first qualifying result to data/found_photos/{code}.jpg
  5. Cache forever — re-running for the same code re-uses the cached file

Marketing overlay is applied SEPARATELY by image_gen.apply_marketing_overlay()
on top of whatever path this returns.

Why DuckDuckGo: zero setup (no API key, no billing). Google's Custom Search
JSON API would give better results but requires a billing-enabled Google Cloud
project — too much setup friction for the founder. Revisit if DDG quality
degrades.

Disclaimer: web-found photos may have copyright. Acceptable risk for a small
business advertising the actual products it sells (similar to a car dealer
using manufacturer photos), but worth noting for the founder.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Optional

import requests
from ddgs import DDGS
from PIL import Image

from src import config
from src.logging_setup import get_logger

log = get_logger(__name__)

# Cache directory for downloaded photos. One file per product code.
_FOUND_PHOTOS_DIR = config.DATA_DIR / "found_photos"

# Quality bar.
MIN_DIMENSION = 300          # pixels (300 is the smallest Telegram doesn't ugly-scale)
MAX_DIMENSION = 5000         # sanity ceiling (banners get rejected)
MIN_FILESIZE = 5 * 1024      # 5 KB — anything smaller is likely a placeholder
MAX_FILESIZE = 5 * 1024 * 1024  # 5 MB — anything larger is unreasonable
MIN_ASPECT = 0.5
MAX_ASPECT = 2.0
DOWNLOAD_TIMEOUT = 15
SEARCH_RESULTS_LIMIT = 15    # walk top N candidates before giving up

# Category hints appended to the search query — boost relevance.
# Every hint includes "tire" or "rubber" because the Uygun catalog is
# overwhelmingly vulcanization / car-wash supplies, and these words
# strongly disambiguate generic terms like "CEMENT" (construction
# vs rubber cement) and "PATCH" (clothing vs tire patch).
_CATEGORY_HINTS: dict[str, str] = {
    "საბურავის": "tire patch repair",
    "რეზინის": "rubber tire",
    "AERO": "pneumatic tire tool",
    "ცემენტ": "rubber cement vulcanizing tire",
    "წებო": "rubber cement vulcanizing tire",
    "ფირფიტა": "tire patch rubber",
    "ფურცელი": "rubber sheet tire",
    "ქანჩი": "tire nut",
    "ხელის": "tire hand tool",
    "კომპრესორი": "tire compressor",
    "დომკრატი": "car lift jack",
    "ლატკ": "tire patch repair",
}

# Default hint applied when the Georgian prefix doesn't match anything above
# but the product is clearly from this catalog.
_DEFAULT_HINT = "tire repair vulcanizing"

# Known brand product-line prefixes. When any of these short tokens appear in
# a product name, the search query is prepended with the brand name — this
# turns a generic "MR 10 patch" search into "Maruni MR 10 patch" which
# returns the actual manufacturer's product page.
#
# Token comparison is case-insensitive and must match a full whitespace-separated
# token (so "MUR" or "MRC" won't accidentally trigger).
_BRAND_BY_TOKEN: dict[str, str] = {
    "MR": "Maruni",   # Maruni RADYAL YAMASI radial patches
    "MU": "Maruni",   # Maruni bias-ply patches
}


# Tokens that are pure measurements/units — useless for image search.
_MEASUREMENT_RE = re.compile(
    r"^("
    r"\d+"                       # any pure number
    r"|\d+(GR|G|ML|CC|L|MM|CM|KG|OZ|LB)"  # number + unit (e.g. 225GR, 200CC)
    r"|GR|ML|CC|MM|CM|KG|LU|LI"  # bare units
    r")$",
    re.IGNORECASE,
)


def _is_brand_token(token: str) -> bool:
    """Heuristic: 3+ chars and contains a letter (not pure digits or units)."""
    if len(token) < 3:
        return False
    if _MEASUREMENT_RE.match(token):
        return False
    return any(c.isalpha() for c in token)


def _detect_brand(tokens: list[str]) -> Optional[str]:
    """If any token matches a known brand-line prefix, return the brand name."""
    for t in tokens:
        if t.upper() in _BRAND_BY_TOKEN:
            return _BRAND_BY_TOKEN[t.upper()]
    return None


def _clean_query(product_name: str) -> str:
    """Build an effective image-search query from a mixed Georgian/Latin name.

    Strategy:
      1. Drop the Georgian. (Search engines don't index Turkish/English product
         pages with Georgian descriptions.)
      2. Detect known brand-line tokens (MR/MU → Maruni). When found, anchor
         the query with the brand name + the MR/MU code + the immediately
         following size token (e.g. "Maruni MR-10" vs "Maruni MU-02") so the
         search engine differentiates two products from the same brand.
         Otherwise Bing happily serves the same generic "Maruni patch" image
         for every variant.
      3. From the Latin half, drop measurement tokens like "225GR", "200CC", "1000".
      4. ALWAYS append a category hint (tire/rubber/vulcanizing) for
         disambiguation. We learned the hard way that "OZEL MAVI CEMENT
         SOLUSYON" alone matched construction floor cement — the word "tire"
         in the hint pulls results back to our actual industry.

    Examples:
      "წებო 225 GR OZEL MAVI CEMENT SOLUSYON"
        → "OZEL MAVI CEMENT SOLUSYON rubber cement vulcanizing tire"
      "საბურავის ლატკა MR 10 RADYAL YAMASI"
        → "Maruni MR-10 RADYAL YAMASI radial tire patch"
      "საბურავის ლატკა MU 02 CIVI DELIGI YAMASI"
        → "Maruni MU-02 CIVI DELIGI YAMASI tire patch repair"
    """
    hint = _DEFAULT_HINT
    for prefix, h in _CATEGORY_HINTS.items():
        if prefix in product_name:
            hint = h
            break

    tokens = re.findall(r"[A-Za-z0-9./-]+", product_name)
    brand_name = _detect_brand(tokens)

    # Brand-line anchored query: "Maruni MR-10 RADYAL YAMASI ..."
    if brand_name:
        try:
            idx = next(i for i, t in enumerate(tokens) if t.upper() in _BRAND_BY_TOKEN)
        except StopIteration:
            idx = -1
        if idx >= 0:
            model = tokens[idx].upper()
            # Combine MR/MU with the next token (usually the size/number) into a hyphenated SKU.
            sku = f"{model}-{tokens[idx + 1]}" if idx + 1 < len(tokens) else model
            # Plus any remaining descriptive tokens (RADYAL/CIVI/DELIGI/YAMASI etc.) — keep 3.
            tail_tokens = [t for t in tokens[idx + 2:] if _is_brand_token(t)][:3]
            tail = " ".join(tail_tokens)
            return " ".join(filter(None, [brand_name, sku, tail, hint])).strip()

    # Fallback: generic catalog product (no recognized brand line).
    brand_tokens = [t for t in tokens if _is_brand_token(t)]
    base = " ".join(brand_tokens[:5]).strip()
    if not base:
        base = product_name
    return f"{base} {hint}".strip()


def _passes_quality(content: bytes, content_type: Optional[str]) -> bool:
    """Validate downloaded bytes before keeping them."""
    if not (MIN_FILESIZE <= len(content) <= MAX_FILESIZE):
        return False
    try:
        with Image.open(io.BytesIO(content)) as img:
            w, h = img.size
            fmt = (img.format or "").upper()
    except Exception:
        return False
    if fmt not in ("JPEG", "PNG", "WEBP"):
        return False
    if not (MIN_DIMENSION <= w <= MAX_DIMENSION):
        return False
    if not (MIN_DIMENSION <= h <= MAX_DIMENSION):
        return False
    aspect = w / h
    if not (MIN_ASPECT <= aspect <= MAX_ASPECT):
        return False
    return True


def _save_jpeg(content: bytes, output_path: Path) -> None:
    """Re-encode whatever we got as RGB JPEG (handles WEBP, PNG with alpha, etc.)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(content)) as img:
        img = img.convert("RGB")
        img.save(output_path, format="JPEG", quality=92, optimize=True)


def cached_path_for(product_code: str) -> Path:
    """Where we'd cache the found photo for this product code."""
    return _FOUND_PHOTOS_DIR / f"{product_code}.jpg"


def find_product_photo(
    product_code: str,
    product_name: str,
    *,
    use_cache: bool = True,
) -> Optional[Path]:
    """Return a Path to a cached found photo, or None if search/quality failed.

    The cache is forever — once we find a good photo, we don't re-search.
    Use `use_cache=False` to force a re-search (the founder might want to
    refresh a photo that turned out wrong).
    """
    cached = cached_path_for(product_code)
    if use_cache and cached.exists():
        log.info("photo_cache_hit", code=product_code, path=str(cached))
        return cached

    query = _clean_query(product_name)
    log.info("photo_search_start", code=product_code, query=query)

    try:
        results = list(DDGS().images(query=query, max_results=SEARCH_RESULTS_LIMIT))
    except Exception:
        log.exception("photo_search_failed", code=product_code, query=query)
        return None

    if not results:
        log.info("photo_search_empty", code=product_code, query=query)
        return None

    for i, hit in enumerate(results):
        url = hit.get("image")
        if not url:
            continue
        try:
            response = requests.get(
                url,
                timeout=DOWNLOAD_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) UygunBot"},
            )
        except Exception as e:
            log.info("photo_download_failed", url=url[:80], err=str(e)[:80])
            continue
        if response.status_code != 200:
            continue
        content = response.content
        ct = response.headers.get("Content-Type", "")
        if not _passes_quality(content, ct):
            log.info(
                "photo_rejected_quality",
                url=url[:80],
                size=len(content),
                content_type=ct[:50],
            )
            continue

        _save_jpeg(content, cached)
        log.info(
            "photo_saved",
            code=product_code,
            url=url[:80],
            attempt=i + 1,
            size_kb=round(len(content) / 1024),
        )
        return cached

    log.info(
        "photo_search_exhausted",
        code=product_code,
        query=query,
        candidates=len(results),
    )
    return None
