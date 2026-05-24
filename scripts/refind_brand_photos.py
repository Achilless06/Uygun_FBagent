"""Re-fetch product photos for a brand-line prefix (e.g. MR/MU → Maruni).

Use when:
  - You added a new brand to `photo_finder._BRAND_BY_TOKEN` and want existing
    cached photos refreshed under the new query.
  - DDG returned wrong results historically and you've since improved the query
    builder.

Usage:
  python -m scripts.refind_brand_photos           # default: MR + MU tokens
  python -m scripts.refind_brand_photos MR        # only MR-prefixed products
  python -m scripts.refind_brand_photos MR MU XX  # custom token list

It walks the catalog, drops any product whose name contains one of the given
tokens as a standalone Latin word, deletes the cached found_photos/{code}.jpg,
and re-runs the photo finder. Skipped if no rows match.
"""

from __future__ import annotations

import re
import sys
from typing import Iterable

from src import config, db
from src.ai import photo_finder
from src.logging_setup import configure as configure_logging
from src.logging_setup import get_logger

log = get_logger(__name__)


def _matches_any_token(name: str, tokens: Iterable[str]) -> bool:
    upper_tokens = {t.upper() for t in tokens}
    raw = re.findall(r"[A-Za-z0-9./-]+", name)
    return any(t.upper() in upper_tokens for t in raw)


def main(argv: list[str]) -> int:
    configure_logging("INFO")
    cfg = config.load()
    db.init_engine(cfg.database_url)
    db.create_all()

    tokens = argv[1:] if len(argv) > 1 else ["MR", "MU"]
    log.info("refind_start", tokens=tokens)

    with db.session_scope() as s:
        rows = s.query(db.Product).all()
        matched = [(p.code, p.name) for p in rows if _matches_any_token(p.name, tokens)]

    print(f"Matched {len(matched)} products for tokens {tokens}:\n")
    if not matched:
        return 0

    success = 0
    failed = 0
    for code, name in matched:
        cached = photo_finder.cached_path_for(code)
        if cached.exists():
            try:
                cached.unlink()
            except Exception:
                log.warning("photo_unlink_failed", code=code)
        result = photo_finder.find_product_photo(code, name, use_cache=False)
        if result is not None:
            success += 1
            print(f"  ✓ {code:<10s} {name[:60]}")
        else:
            failed += 1
            print(f"  ✗ {code:<10s} {name[:60]}  (no photo found)")

    print(f"\nDone: {success} found, {failed} failed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
