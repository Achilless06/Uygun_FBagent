"""One-shot bulk importer for the founder's 2026 daily sales workbooks.

CLI wrapper around `src.sales_importer`. The Telegram `/import_sales` flow
uses the same library for monthly batches — this script is for the initial
historical backfill (or any out-of-band batch the founder wants to re-run).

Source layout (set by --root, default `/Users/achilles/Desktop/Uygun/2026/`):
    <root>/
      იანვარი 01 2026/ DD.MM.YYYY.xlsx
      …
      ივნისი 06 2026/ DD.MM.YYYY.xlsx

Each workbook has either "Sales" (English) or "satis" (Turkish, Jan-Mar
legacy) sheet — see `src/sales_importer.py` for the column layout.

Dry-run by default. Pass `--commit` to actually write. `--wipe-2026` first
deletes existing 2026 sales (idempotent re-runs).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config, db, sales_importer
from src.logging_setup import configure as configure_logging, get_logger

log = get_logger(__name__)

DEFAULT_ROOT = Path("/Users/achilles/Desktop/Uygun/2026")


def _format_money(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ")


def run(root: Path, commit: bool, wipe_2026: bool, top_n: int) -> int:
    cfg = config.load()
    db.init_engine(cfg.database_url)
    db.create_all()

    with db.session_scope() as s:
        catalog = {p.code: p.name for p in s.query(db.Product).all()}
    print(f"📚 catalog: {len(catalog)} products")

    parsed = list(sales_importer.parse_directory(root))
    file_count = len({r.source_file for r in parsed if r.source_file})

    if not parsed:
        print("❌ no sale rows parsed from", root)
        return 1

    # Per-code rollups for the dry-run report.
    by_code_qty: Counter[str] = Counter()
    by_code_revenue: dict[str, float] = defaultdict(float)
    unknown_codes: Counter[str] = Counter()
    for r in parsed:
        by_code_qty[r.product_code] += r.quantity
        by_code_revenue[r.product_code] += r.total_price
        if r.product_code not in catalog:
            unknown_codes[r.product_code] += 1
    total_revenue = sum(by_code_revenue.values())

    print()
    print("═" * 56)
    print(f"📂 files scanned: {file_count}")
    print(f"🧾 sale rows:     {len(parsed)}")
    print(f"💰 total revenue: {_format_money(total_revenue)} ₾")
    print(f"❓ unknown codes: {len(unknown_codes)}  "
          f"(rows ignoring catalog: {sum(unknown_codes.values())})")
    print("═" * 56)
    print()
    print(f"🏆 Top {top_n} codes by quantity sold:")
    for i, (code, qty) in enumerate(by_code_qty.most_common(top_n), 1):
        revenue = by_code_revenue[code]
        name = catalog.get(code, "??? (not in products.xlsx)")
        flag = "" if code in catalog else " ⚠️"
        name = (name[:42] + "…") if len(name) > 42 else name
        print(
            f"  {i:>2}. `{code}`{flag}  qty={qty:>7.0f}  "
            f"rev={_format_money(revenue):>10} ₾  {name}"
        )
    print()

    if unknown_codes:
        print(f"⚠️  Codes in xlsx but missing from products.xlsx ({len(unknown_codes)}):")
        for code, n in unknown_codes.most_common(20):
            print(f"     `{code}` — {n} rows")
        if len(unknown_codes) > 20:
            print(f"     … +{len(unknown_codes) - 20} more")
        print()

    if not commit:
        print("🧪 DRY-RUN — nothing written. Re-run with --commit to insert.")
        return 0

    wipe_period = None
    if wipe_2026:
        wipe_period = (datetime(2026, 1, 1), datetime(2027, 1, 1))

    inserted, deleted = sales_importer.commit_sales(parsed, wipe_period=wipe_period)
    if deleted:
        print(f"🧹 wiped {deleted} pre-existing 2026 sale rows")
    print(f"✅ inserted {inserted} rows into `sales`")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=DEFAULT_ROOT,
        help=f"Sales-folder root (default: {DEFAULT_ROOT})",
    )
    parser.add_argument(
        "--commit", action="store_true",
        help="Actually write to DB (default is dry-run).",
    )
    parser.add_argument(
        "--wipe-2026", action="store_true",
        help="Delete existing 2026 sales before insert. Use with --commit.",
    )
    parser.add_argument(
        "--top", type=int, default=30,
        help="How many top codes to print in the dry-run report.",
    )
    args = parser.parse_args(argv[1:])

    configure_logging("INFO")
    if not args.root.exists():
        print(f"❌ root not found: {args.root}", file=sys.stderr)
        return 1
    return run(args.root, args.commit, args.wipe_2026, args.top)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
