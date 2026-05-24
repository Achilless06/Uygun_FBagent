"""Walk the catalog and fetch a web photo for every product that lacks one.

Resumable: skips products that already have a founder-uploaded photo at
`data/photos/{code}.jpg` OR a cached found photo at `data/found_photos/{code}.jpg`.
If DDG rate-limits us mid-run, just re-invoke — it picks up where it left off.

Usage:
  python -m scripts.fetch_all_photos              # all uncached
  python -m scripts.fetch_all_photos --force      # re-fetch everything
  python -m scripts.fetch_all_photos --limit 50   # try the first 50 uncached
  python -m scripts.fetch_all_photos --sleep 1.0  # extra delay between calls

Logs go to stdout with [N/M] progress. Background-safe: stdout to a file works.
"""

from __future__ import annotations

import argparse
import sys
import time

from src import config, db
from src.ai import photo_finder
from src.config import DATA_DIR
from src.logging_setup import configure as configure_logging
from src.logging_setup import get_logger

log = get_logger(__name__)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Re-fetch even if cached")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N products")
    parser.add_argument(
        "--sleep", type=float, default=0.6, help="Seconds to sleep between API calls"
    )
    args = parser.parse_args(argv[1:])

    configure_logging("INFO")
    cfg = config.load()
    db.init_engine(cfg.database_url)
    db.create_all()

    uploaded_dir = DATA_DIR / "photos"

    with db.session_scope() as s:
        all_rows = (
            s.query(db.Product)
            .order_by(db.Product.code_sort.asc().nullslast(), db.Product.code.asc())
            .all()
        )
        products = [(p.code, p.name) for p in all_rows]

    pending: list[tuple[str, str]] = []
    skipped = 0
    for code, name in products:
        uploaded = uploaded_dir / f"{code}.jpg"
        cached = photo_finder.cached_path_for(code)
        if not args.force and (uploaded.exists() or cached.exists()):
            skipped += 1
            continue
        pending.append((code, name))

    if args.limit:
        pending = pending[: args.limit]

    print(f"Catalog total : {len(products)}")
    print(f"Already cached: {skipped}")
    print(f"To fetch      : {len(pending)}")
    print(f"Sleep between : {args.sleep}s\n")
    if not pending:
        print("Nothing to do.")
        return 0

    found = 0
    failed = 0
    failed_codes: list[str] = []
    for i, (code, name) in enumerate(pending, 1):
        prefix = f"[{i:>3d}/{len(pending)}]"
        try:
            result = photo_finder.find_product_photo(
                code, name, use_cache=not args.force
            )
        except Exception as e:
            print(f"{prefix} {code:<8s} ERROR {str(e)[:50]}", flush=True)
            failed += 1
            failed_codes.append(code)
        else:
            if result:
                found += 1
                print(f"{prefix} {code:<8s} ✓ {name[:55]}", flush=True)
            else:
                failed += 1
                failed_codes.append(code)
                print(f"{prefix} {code:<8s} ✗ no result — {name[:50]}", flush=True)
        if i < len(pending):
            time.sleep(args.sleep)

    print(
        f"\nDone: {found} found, {failed} failed out of {len(pending)}."
    )
    if failed_codes:
        print(f"Failed codes: {', '.join(failed_codes[:30])}"
              + (f" (+{len(failed_codes)-30} more)" if len(failed_codes) > 30 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
