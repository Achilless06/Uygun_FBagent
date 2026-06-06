"""Export the founder-facing sales analysis to an .xlsx on the Desktop.

Sheets produced:
  1. Summary       — totals, date range, file count
  2. Top 15 Insights — narrative analysis of top 15 demand codes with trend tags
  3. Top by Qty 30d — top 50 products by quantity over last 30 days
  4. Top by Qty YTD — top 50 products by quantity over the whole import
  5. Top by Revenue — top 50 products by total revenue
  6. Monthly        — sales count / units / revenue per month
  7. Daily Totals   — sales count / revenue per day
  8. Dead Stock     — products in catalog with zero sales in 2026
  9. All Sales      — every imported row

Run after `import_sales_2026.py --commit`.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config, db
from src.demand_analysis import classify_trend


OUTPUT_PATH = Path.home() / "Desktop" / "Uygun_Sales_Analysis_2026.xlsx"


HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill(fill_type="solid", start_color="BC1215", end_color="BC1215")
HEADER_ALIGN = Alignment(horizontal="left", vertical="center")

MONEY_FMT = "#,##0.00 \"₾\""
QTY_FMT = "#,##0"
DATE_FMT = "yyyy-mm-dd"

MONTHS_KA = [
    "იანვარი", "თებერვალი", "მარტი", "აპრილი", "მაისი", "ივნისი",
    "ივლისი", "აგვისტო", "სექტემბერი", "ოქტომბერი", "ნოემბერი", "დეკემბერი",
]


def _style_header(ws, ncols: int) -> None:
    for col in range(1, ncols + 1):
        c = ws.cell(row=1, column=col)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = HEADER_ALIGN
    ws.freeze_panes = "A2"


def _autosize(ws, padding: int = 2) -> None:
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = 0
        for cell in col:
            v = cell.value
            if v is None:
                continue
            length = len(str(v))
            if length > max_len:
                max_len = length
        ws.column_dimensions[col_letter].width = min(max_len + padding, 60)


def build_workbook() -> Workbook:
    cfg = config.load()
    db.init_engine(cfg.database_url)

    with db.session_scope() as s:
        sales = (
            s.query(db.Sale)
            .order_by(db.Sale.sold_at.asc(), db.Sale.id.asc())
            .all()
        )
        products = {p.code: p for p in s.query(db.Product).all()}

    if not sales:
        raise RuntimeError(
            "No sales rows in DB. Run scripts/import_sales_2026.py --commit first."
        )

    wb = Workbook()
    wb.remove(wb.active)  # we'll add named sheets below

    from datetime import timedelta as _td

    now = datetime.utcnow()
    cutoff_30 = now - _td(days=30)
    cutoff_90 = now - _td(days=90)

    # ─── Aggregations ──────────────────────────────────────────────────────
    qty_30: Counter[str] = Counter()
    rev_30: dict[str, float] = defaultdict(float)
    qty_90: Counter[str] = Counter()
    qty_total: Counter[str] = Counter()
    rev_total: dict[str, float] = defaultdict(float)
    last_sold: dict[str, datetime] = {}
    days_sold: dict[str, set] = defaultdict(set)
    tx_count: Counter[str] = Counter()
    companies: dict[str, set] = defaultdict(set)

    monthly_rev: dict[str, float] = defaultdict(float)
    monthly_units: dict[str, float] = defaultdict(float)
    monthly_count: Counter[str] = Counter()

    daily_rev: dict[datetime, float] = defaultdict(float)
    daily_count: Counter[datetime] = Counter()

    for s_row in sales:
        code = s_row.product_code
        qty = float(s_row.quantity)
        total = float(s_row.total_price)
        qty_total[code] += qty
        rev_total[code] += total
        days_sold[code].add(s_row.sold_at.date())
        tx_count[code] += 1
        if s_row.notes:
            companies[code].add(s_row.notes.strip())
        if s_row.sold_at >= cutoff_30:
            qty_30[code] += qty
            rev_30[code] += total
        if s_row.sold_at >= cutoff_90:
            qty_90[code] += qty
        cur = last_sold.get(code)
        if cur is None or s_row.sold_at > cur:
            last_sold[code] = s_row.sold_at

        month_key = s_row.sold_at.strftime("%Y-%m")
        monthly_rev[month_key] += total
        monthly_units[month_key] += qty
        monthly_count[month_key] += 1

        day = s_row.sold_at.date()
        daily_rev[day] += total
        daily_count[day] += 1

    # ─── Sheet 1: Summary ──────────────────────────────────────────────────
    ws = wb.create_sheet("Summary")
    rows = [
        ("ანგარიში გენერირებულია", now.strftime("%Y-%m-%d %H:%M UTC")),
        ("მთლიანი row რაოდენობა", len(sales)),
        ("მთლიანი შემოსავალი (₾)", round(sum(rev_total.values()), 2)),
        ("მთლიანი ერთეული (გაყიდული)", round(sum(qty_total.values()), 2)),
        ("უნიკალური პროდუქცია გაყიდვებში", len(qty_total)),
        ("კატალოგში პროდუქცია", len(products)),
        ("dead-stock (გაყიდვის გარეშე)", len(products) - len(qty_total)),
        ("გაყიდვის თარიღი (ყველაზე ადრე)", sales[0].sold_at.strftime("%Y-%m-%d")),
        ("გაყიდვის თარიღი (ყველაზე გვიან)", sales[-1].sold_at.strftime("%Y-%m-%d")),
        ("საშუალო day-revenue (₾)", round(sum(daily_rev.values()) / len(daily_rev), 2) if daily_rev else 0),
        ("Top-1 პროდუქცია (qty)", f"{qty_total.most_common(1)[0][0]} — {products.get(qty_total.most_common(1)[0][0]).name if products.get(qty_total.most_common(1)[0][0]) else '?'}"),
        ("Top-1 პროდუქცია (revenue)", f"{sorted(rev_total.items(), key=lambda kv: kv[1], reverse=True)[0][0]} — {round(sorted(rev_total.items(), key=lambda kv: kv[1], reverse=True)[0][1], 2)} ₾"),
    ]
    ws.append(["მაჩვენებელი", "მნიშვნელობა"])
    for k, v in rows:
        ws.append([k, v])
    _style_header(ws, 2)
    _autosize(ws, padding=4)

    # ─── Sheet 2: Top 15 Insights (analysis) ───────────────────────────────
    ws = wb.create_sheet("Top 15 Insights")
    ws.append([
        "#", "კოდი", "სახელი", "მარაგი", "ფასი ₾",
        "qty (სრული)", "qty_30d", "qty_90d",
        "revenue ₾", "avg unit ₾",
        "სავაჭრო დღე", "tx", "უნიკ. კომპანია",
        "ბოლო გაყიდვა", "trend", "insight",
    ])
    top_15 = qty_total.most_common(15)
    for i, (code, qt) in enumerate(top_15, 1):
        p = products.get(code)
        rev = rev_total[code]
        avg_p = rev / qt if qt else 0
        tag, narrative = classify_trend(
            qt, qty_30[code], avg_p, len(days_sold[code])
        )
        ws.append([
            i, code,
            p.name if p else "?",
            (p.stock_qty if p else None),
            (p.price if p and p.price else None),
            qt, qty_30[code], qty_90[code],
            round(rev, 2), round(avg_p, 3),
            len(days_sold[code]), tx_count[code], len(companies[code]),
            last_sold[code].strftime("%Y-%m-%d"),
            tag, narrative,
        ])
    _style_header(ws, 16)
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=5).number_format = MONEY_FMT
        for col in (6, 7, 8, 11, 12, 13):
            ws.cell(row=r, column=col).number_format = QTY_FMT
        ws.cell(row=r, column=9).number_format = MONEY_FMT
        ws.cell(row=r, column=10).number_format = MONEY_FMT
        ws.cell(row=r, column=16).alignment = Alignment(wrap_text=True, vertical="top")
    _autosize(ws)
    # narrative gets wider treatment
    ws.column_dimensions["P"].width = 65
    ws.column_dimensions["O"].width = 18

    # Bottom narrative block — 5 key insights.
    blank_row = ws.max_row + 2
    insight_block = [
        ("📊 5 მთავარი insight", ""),
        ("1. ორი დონის ბესტსელერი", "Bulk-consumables (<0.5₾, qty>1000) გვაძლევს მოცულობას; mid-priced staples (1.5-6₾) — რეალურ revenue-ს."),
        ("2. Top-1 revenue ≠ Top-1 qty", "ფულით ლიდერი — `36` GAV R 10 (2,073₾, qty rank #6). qty-ით — `156` ტყვიის წონა (3,800 ცალი)."),
        ("3. ⚠️ Stalled codes (qty_30d=0)", "`159`, `3`, `10`, `14` — წელს ლიდერები, ბოლო თვეში 0. შემოწმე მარაგი/სეზონი/კონკურენტი — Daily-mode-ში ეს კოდები არ მოხვდება (filter excludes)."),
        ("4. 🔥 Burst code", "`156` 30 დღეში 1,300/3,800 (34%). ერთჯერადი B2B ბურსტი (2 უნიკ. კომპანია). FB-ზე B2B angle."),
        ("5. პოსტებისთვის ოპტიმუმი", "Recent (qty_30d>10) + Margin (avg>0.30₾): `36`, `109`, `411`, `8`, `136`, `81`, `1`, `6`, `347`, `5`. ეს ნამდვილად 'მოთხოვნადი + ფული'."),
    ]
    for i, (k, v) in enumerate(insight_block):
        ws.cell(row=blank_row + i, column=2, value=k).font = Font(bold=True)
        ws.cell(row=blank_row + i, column=3, value=v).alignment = Alignment(
            wrap_text=True, vertical="top"
        )
        ws.merge_cells(start_row=blank_row + i, start_column=3, end_row=blank_row + i, end_column=16)
        ws.row_dimensions[blank_row + i].height = 30 if i > 0 else 22

    # ─── Sheet 3: Top by Qty (30 days) ─────────────────────────────────────
    ws = wb.create_sheet("Top Qty 30d")
    ws.append(["#", "კოდი", "სახელი", "მარაგი", "ფასი ₾", "qty (30 დღე)", "rev (30 დღე) ₾", "ბოლო გაყიდვა"])
    for i, (code, q) in enumerate(qty_30.most_common(50), 1):
        p = products.get(code)
        ws.append([
            i, code,
            p.name if p else "?",
            (p.stock_qty if p else None),
            (p.price if p and p.price else None),
            q,
            round(rev_30[code], 2),
            last_sold[code].strftime("%Y-%m-%d") if code in last_sold else "",
        ])
    _style_header(ws, 8)
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=5).number_format = MONEY_FMT
        ws.cell(row=r, column=6).number_format = QTY_FMT
        ws.cell(row=r, column=7).number_format = MONEY_FMT
    _autosize(ws)

    # ─── Sheet 3: Top by Qty (YTD) ─────────────────────────────────────────
    ws = wb.create_sheet("Top Qty YTD")
    ws.append(["#", "კოდი", "სახელი", "მარაგი", "ფასი ₾", "qty (სრული 2026)", "rev (სრული) ₾", "ბოლო გაყიდვა"])
    for i, (code, q) in enumerate(qty_total.most_common(50), 1):
        p = products.get(code)
        ws.append([
            i, code,
            p.name if p else "?",
            (p.stock_qty if p else None),
            (p.price if p and p.price else None),
            q,
            round(rev_total[code], 2),
            last_sold[code].strftime("%Y-%m-%d") if code in last_sold else "",
        ])
    _style_header(ws, 8)
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=5).number_format = MONEY_FMT
        ws.cell(row=r, column=6).number_format = QTY_FMT
        ws.cell(row=r, column=7).number_format = MONEY_FMT
    _autosize(ws)

    # ─── Sheet 4: Top by Revenue ───────────────────────────────────────────
    ws = wb.create_sheet("Top Revenue")
    ws.append(["#", "კოდი", "სახელი", "მარაგი", "ფასი ₾", "rev (₾)", "qty"])
    rev_sorted = sorted(rev_total.items(), key=lambda kv: kv[1], reverse=True)[:50]
    for i, (code, rev) in enumerate(rev_sorted, 1):
        p = products.get(code)
        ws.append([
            i, code,
            p.name if p else "?",
            (p.stock_qty if p else None),
            (p.price if p and p.price else None),
            round(rev, 2),
            qty_total[code],
        ])
    _style_header(ws, 7)
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=5).number_format = MONEY_FMT
        ws.cell(row=r, column=6).number_format = MONEY_FMT
        ws.cell(row=r, column=7).number_format = QTY_FMT
    _autosize(ws)

    # ─── Sheet 5: Monthly ──────────────────────────────────────────────────
    ws = wb.create_sheet("Monthly")
    ws.append(["თვე", "ტრანზაქცია", "ერთეული", "შემოსავალი ₾"])
    for month_key in sorted(monthly_rev.keys()):
        y, m = month_key.split("-")
        label = f"{MONTHS_KA[int(m) - 1]} {y}"
        ws.append([
            label,
            monthly_count[month_key],
            round(monthly_units[month_key], 2),
            round(monthly_rev[month_key], 2),
        ])
    _style_header(ws, 4)
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=3).number_format = QTY_FMT
        ws.cell(row=r, column=4).number_format = MONEY_FMT
    _autosize(ws)

    # ─── Sheet 6: Daily Totals ─────────────────────────────────────────────
    ws = wb.create_sheet("Daily Totals")
    ws.append(["თარიღი", "ტრანზაქცია", "შემოსავალი ₾"])
    for day in sorted(daily_rev.keys()):
        ws.append([day, daily_count[day], round(daily_rev[day], 2)])
    _style_header(ws, 3)
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=1).number_format = DATE_FMT
        ws.cell(row=r, column=3).number_format = MONEY_FMT
    _autosize(ws)

    # ─── Sheet 7: Dead Stock ───────────────────────────────────────────────
    ws = wb.create_sheet("Dead Stock")
    ws.append(["კოდი", "სახელი", "მარაგი", "ფასი ₾", "კატეგორია"])
    for code, p in sorted(products.items(), key=lambda kv: kv[0]):
        if code in qty_total:
            continue
        ws.append([
            code,
            p.name,
            p.stock_qty,
            p.price if p.price else None,
            p.category or "",
        ])
    _style_header(ws, 5)
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=4).number_format = MONEY_FMT
    _autosize(ws)

    # ─── Sheet 8: All Sales ────────────────────────────────────────────────
    ws = wb.create_sheet("All Sales")
    ws.append(["თარიღი", "კოდი", "სახელი", "qty", "ცალის ფასი ₾", "ჯამი ₾", "კომპანია"])
    for s_row in sales:
        ws.append([
            s_row.sold_at.date(),
            s_row.product_code,
            s_row.product_name,
            s_row.quantity,
            round(s_row.unit_price, 4),
            round(s_row.total_price, 2),
            s_row.notes or "",
        ])
    _style_header(ws, 7)
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=1).number_format = DATE_FMT
        ws.cell(row=r, column=4).number_format = QTY_FMT
        ws.cell(row=r, column=5).number_format = MONEY_FMT
        ws.cell(row=r, column=6).number_format = MONEY_FMT
    _autosize(ws)

    return wb


def main() -> int:
    wb = build_workbook()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUTPUT_PATH)
    size_kb = OUTPUT_PATH.stat().st_size // 1024
    print(f"✅ saved: {OUTPUT_PATH}  ({size_kb} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
