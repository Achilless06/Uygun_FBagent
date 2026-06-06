"""Demand aggregation + trend classification.

Reads `sales` rows for a given time window and ranks product codes by total
quantity. Each top-N row carries a `trend` tag (🔥 burst / ✅ daily staple /
…) and a one-line Georgian narrative — both used by the Monthly Top Sellers
Airtable view and the Daily-mode strategist's demand candidates.

Two windows matter:
  - PERIOD window: the time range we're reporting on (e.g. one month).
  - RECENT-30 window: the last 30 days from `now` — even inside a monthly
    report, the founder cares whether the leader is still moving recently.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date as _date, datetime, timedelta
from typing import Optional

from src import db


@dataclass
class TopSeller:
    rank: int
    code: str
    name: str
    qty: float
    revenue: float
    avg_unit_price: float
    days_sold: int
    tx_count: int
    unique_companies: int
    last_sold: _date
    qty_recent_30d: float
    stock_qty: Optional[int]
    catalog_price: Optional[float]
    trend_tag: str
    insight: str
    extra: dict = field(default_factory=dict)


def classify_trend(
    qty_period: float,
    qty_30d: float,
    avg_price: float,
    days_sold: int,
) -> tuple[str, str]:
    """Return (trend_tag, narrative) — one-line Georgian insight.

    Threshold order matters: the most-specific signal wins. High-margin
    detection runs before generic "active" so a 💎 product doesn't get
    mislabeled as a low-info ✅ active.
    """
    pct_30 = (qty_30d / qty_period) if qty_period > 0 else 0

    if avg_price >= 3 and qty_period >= 100:
        if qty_30d == 0:
            return (
                "💎 stalled",
                f"მარჟიანი (avg ₾{avg_price:.2f}), მაგრამ ბოლო 30 დღეში "
                f"არ გაუყიდია — შემოწმე მარაგი/ფასი",
            )
        return (
            "💎 high-margin",
            f"მარჟიანი ბესტსელერი (avg ₾{avg_price:.2f}, "
            f"qty_30d={qty_30d:.0f}) — პოსტისთვის იდეალური",
        )

    if qty_30d == 0 and qty_period >= 200:
        return (
            "❌ stalled",
            "წელს ბესტსელერი იყო, ბოლო 30 დღეში 0 — გადასამოწმებელია "
            "(მარაგი/სეზონი/კონკურენტი)",
        )

    if pct_30 >= 0.30 and qty_30d >= 200:
        return (
            "🔥 burst",
            f"ბოლო 30 დღეში მთლიანი პერიოდის {pct_30 * 100:.0f}% — "
            "სავარაუდოდ ერთჯერადი B2B ბურსტი",
        )

    if qty_30d >= 100 and days_sold >= 25:
        return (
            "✅ daily staple",
            f"ყოველდღიური მოთხოვნა, {days_sold} სხვადასხვა დღეზე "
            "გაიყიდა — სტაბილური ბირთვი",
        )

    if qty_30d < 30 and qty_period >= 300:
        return (
            "⚠️ cooling",
            f"პერიოდის მოცულობით ლიდერი, ბოლო თვეში მკვეთრად "
            f"დაიკლო (qty_30d={qty_30d:.0f})",
        )

    if avg_price < 0.15:
        return (
            "➖ filler",
            f"ფასი ძალიან დაბალია (avg ₾{avg_price:.2f}) — "
            "მოცულობით, არა revenue-ით",
        )

    if qty_30d > 50:
        return (
            "✅ active",
            f"ბოლო 30 დღეში {qty_30d:.0f} ცალი გაიყიდა — ჯერ კიდევ მუშაობს",
        )

    return "➖ flat", "მზომიერი მოცულობა, არც ბურსტი, არც ვარდნა"


def analyze_top_sellers(
    period_start: datetime,
    period_end: datetime,
    *,
    top_n: int = 15,
    now: Optional[datetime] = None,
) -> list[TopSeller]:
    """Return top-N codes by qty within [period_start, period_end).

    `qty_recent_30d` is computed against `now - 30d` (defaults to utcnow)
    so monthly reports for past months still surface trend context.
    """
    if now is None:
        now = datetime.utcnow()
    cutoff_30 = now - timedelta(days=30)

    with db.session_scope() as s:
        period_rows = (
            s.query(db.Sale)
            .filter(db.Sale.sold_at >= period_start, db.Sale.sold_at < period_end)
            .all()
        )
        all_codes_in_period = {r.product_code for r in period_rows}
        recent_rows = (
            s.query(db.Sale)
            .filter(db.Sale.sold_at >= cutoff_30)
            .filter(db.Sale.product_code.in_(all_codes_in_period))
            .all()
            if all_codes_in_period
            else []
        )
        products = {p.code: p for p in s.query(db.Product).all()}

    qty_period: Counter[str] = Counter()
    rev_period: dict[str, float] = defaultdict(float)
    days_sold: dict[str, set] = defaultdict(set)
    tx_count: Counter[str] = Counter()
    companies: dict[str, set] = defaultdict(set)
    last_sold: dict[str, _date] = {}

    for r in period_rows:
        c = r.product_code
        qty_period[c] += float(r.quantity)
        rev_period[c] += float(r.total_price)
        d = r.sold_at.date()
        days_sold[c].add(d)
        tx_count[c] += 1
        if r.notes:
            companies[c].add(r.notes.strip())
        cur = last_sold.get(c)
        if cur is None or d > cur:
            last_sold[c] = d

    qty_30: Counter[str] = Counter()
    for r in recent_rows:
        qty_30[r.product_code] += float(r.quantity)

    ranked: list[TopSeller] = []
    for i, (code, qty) in enumerate(qty_period.most_common(top_n), 1):
        p = products.get(code)
        rev = rev_period[code]
        avg_p = rev / qty if qty else 0
        tag, narrative = classify_trend(qty, qty_30[code], avg_p, len(days_sold[code]))
        ranked.append(TopSeller(
            rank=i,
            code=code,
            name=(p.name if p else "?"),
            qty=qty,
            revenue=round(rev, 2),
            avg_unit_price=round(avg_p, 3),
            days_sold=len(days_sold[code]),
            tx_count=tx_count[code],
            unique_companies=len(companies[code]),
            last_sold=last_sold[code],
            qty_recent_30d=qty_30[code],
            stock_qty=(p.stock_qty if p else None),
            catalog_price=(p.price if p and p.price else None),
            trend_tag=tag,
            insight=narrative,
        ))
    return ranked


def analyze_month(
    year: int, month: int, *, top_n: int = 15, now: Optional[datetime] = None
) -> list[TopSeller]:
    """Convenience wrapper: analyze a single calendar month."""
    from src.sales_importer import month_bounds

    start, end = month_bounds(year, month)
    return analyze_top_sellers(start, end, top_n=top_n, now=now)
