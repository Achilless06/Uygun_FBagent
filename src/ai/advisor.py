"""Daily advisor / analyst — generates 4-5 context-aware tips per day.

The advisor knows:
  - Today's date (and what season it is in Batumi — tourist start, peak summer, etc.)
  - Day of week (B2B day, B2C day, EDU day per brandbook calendar)
  - Current inventory state (% priced, % in-stock, % with photos)
  - Recent posting activity (last 7 days, pending drafts)
  - Brand voice rules from brand.py

It returns up to 5 short tips with icons, categories, and optional action labels.
Tips are cached in `settings` table under key `tips:YYYY-MM-DD` so we don't burn
API budget on every /tips view — regenerated at most once per day (or on demand
via the "🔃 განახლება" button).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from src import brand, db
from src.ai.claude_client import ClaudeClient
from src.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class Tip:
    icon: str  # one emoji
    category: str  # seasonal | inventory | content | audience | action | growth
    title: str
    body: str
    action_label: Optional[str] = None


WEEKDAYS_KA = [
    "ორშაბათი",  # 0
    "სამშაბათი",  # 1
    "ოთხშაბათი",  # 2
    "ხუთშაბათი",  # 3
    "პარასკევი",  # 4
    "შაბათი",  # 5
    "კვირა",  # 6
]

MONTHS_KA = [
    "იანვარი", "თებერვალი", "მარტი", "აპრილი", "მაისი", "ივნისი",
    "ივლისი", "აგვისტო", "სექტემბერი", "ოქტომბერი", "ნოემბერი", "დეკემბერი",
]


def _season_hint(month: int) -> str:
    """Batumi-specific seasonal context. Batumi is subtropical Black Sea coast."""
    if month == 5:
        return (
            "გვიანი გაზაფხული. ბათუმის ტურისტული სეზონი იხსნება. "
            "მძღოლები ემზადებიან საზაფხულო მგზავრობებისთვის — საბურავი, ანტიფრიზის "
            "შემოწმება, სამრეცხაო ქიმია გაყიდვების ზრდის სიგნალია."
        )
    if month in (6, 7, 8):
        return (
            "ზაფხული — პიკი ტურისტული სეზონი. სიცხეა, საბურავი უფრო ცხელდება, "
            "ვულკანიზაცია მეტი მუშაობს. სამრეცხაო ბიზნესი ბუმს განიცდის."
        )
    if month == 9:
        return "ადრე შემოდგომა. ტურისტული სეზონის ბოლო. გადასასვლელი პერიოდი."
    if month in (10, 11):
        return (
            "შემოდგომა. სველი ამინდი, გზაზე ლურსმანი/მინა — ვულკანიზაცია მეტი "
            "სამუშაოა. ხალხი ემზადება ზამთრის საბურავის შესაცვლელად."
        )
    if month in (12, 1, 2):
        return "ზამთარი. ცივი, ნოტიო ამინდი. ზამთრის საბურავი + ანტიფრიზი."
    return "გაზაფხული. ხალხი ცვლის ზამთრის საბურავს საზაფხულოზე."


SYSTEM_PROMPT = f"""\
შენ ხარ Uygun Georgia-ს ბრენდის ანალიტიკოსი და მრჩეველი.

ბრენდის შესახებ:
{brand.MISSION}

ხედვა: {brand.VISION}

სამიზნე აუდიტორია: B2B (ვულკანიზაცია/ავტოსამრეცხაო მფლობელები) + B2C (DIY მძღოლები).
ბრენდის ხმა: პროფესიონალური, პირდაპირი, დახმარებაზე ორიენტირებული, "შენ" ფორმით.

შენი ამოცანა — დღევანდელი თარიღისთვის მისცე ფასილატორს 4-5 პრაქტიკული, კონკრეტული რჩევა:
- ერთი მაინც სეზონური (Batumi-ის ამინდის/ტურისტული სეზონის გათვალისწინებით)
- ერთი მაინც კონტენტ-სტრატეგიის შესახებ (ბრენდბუქის კალენდრის მიხედვით)
- ერთი მაინც კონკრეტული მოქმედებაზე (action item) მონაცემების საფუძველზე
- დანარჩენი — სავაჭრო, აუდიტორიის, ან ზრდის რჩევები

თითოეული რჩევა იყოს მოკლე: title 4-6 სიტყვა, body 1-2 წინადადება.

აკრძალულია:
- ცარიელი ფრაზები ("გაიხდი მუშტრის ვარსკვლავი" ტიპის)
- კონკურენტების ხსენება
- "თქვენ" ფორმის გამოყენება
- ფასების მოგონება
- მარკეტინგული ჟარგონი

დააბრუნე მხოლოდ JSON მასივი, არანაირი დამატებითი ტექსტი:

[
  {{
    "icon": "🌞",
    "category": "seasonal",
    "title": "მოკლე სათაური",
    "body": "1-2 წინადადება სხეული.",
    "action_label": null
  }}
]

categories: "seasonal" | "inventory" | "content" | "audience" | "action" | "growth"
icons: კატეგორიის შესაბამისი ერთი emoji
action_label: null ან 2-3 სიტყვა (მაგ. "/products", "/inventory")
"""


USER_PROMPT_TEMPLATE = """\
დღევანდელი თარიღი: {date_human} ({weekday_ka})

ბათუმის სეზონური კონტექსტი:
{season_hint}

ბრენდბუქის კალენდრით დღეს უნდა გავაკეთო: {calendar_slot} ფოკუსიანი პოსტი
(B2B = ვულკანიზაცია/სამრეცხაოს მფლობელები, B2C = ენთუზიასტი, EDU = საგანმანათლებლო,
BTS = behind the scenes, LITE = მსუბუქი, Promo = აქცია).

მაღაზიის სტატისტიკა:
- პროდუქცია სულ: {total_products}
- ფასით: {priced_products} ({price_pct}%)
- მარაგში: {in_stock} ({stock_pct}%)
- ფოტოთი: {with_photos} ({photo_pct}%)

Facebook სტატისტიკა:
- გამოქვეყნებული პოსტი სულ: {posts_published}
- ბოლო 7 დღე გამოქვეყნებული: {posts_last_week}
- დასადასტურებლად ელოდება: {pending_drafts}

დააბრუნე 4-5 რჩევა JSON მასივში.
"""


class Advisor:
    """Generates and caches daily tips."""

    def __init__(self, claude: ClaudeClient) -> None:
        self._claude = claude

    def get_tips_for_today(self, force_refresh: bool = False) -> list[Tip]:
        today = date.today()
        cache_key = f"tips:{today.isoformat()}"

        if not force_refresh:
            cached = db.get_setting(cache_key)
            if cached:
                try:
                    return [Tip(**t) for t in json.loads(cached)]
                except (json.JSONDecodeError, TypeError) as e:
                    log.warning("advisor_cache_corrupt", error=str(e))

        tips = self._generate(today)
        if tips:
            db.set_setting(
                cache_key,
                json.dumps([asdict(t) for t in tips], ensure_ascii=False),
            )
        return tips

    def _generate(self, today: date) -> list[Tip]:
        ctx = self._gather_context(today)
        user_prompt = USER_PROMPT_TEMPLATE.format(**ctx)

        try:
            response = self._claude.generate(
                SYSTEM_PROMPT, user_prompt, operation="advisor_tips", max_tokens=2000
            )
        except Exception:
            log.exception("advisor_claude_call_failed")
            return []

        cleaned = ClaudeClient.strip_json_fences(response.text)
        try:
            tips_data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            log.error(
                "advisor_parse_failed",
                error=str(e),
                raw_preview=response.text[:300],
            )
            return []

        if not isinstance(tips_data, list):
            log.error("advisor_response_not_a_list", type=type(tips_data).__name__)
            return []

        tips: list[Tip] = []
        for item in tips_data:
            if not isinstance(item, dict):
                continue
            tips.append(
                Tip(
                    icon=str(item.get("icon", "💡"))[:4],
                    category=str(item.get("category", "action")),
                    title=str(item.get("title", "")).strip(),
                    body=str(item.get("body", "")).strip(),
                    action_label=item.get("action_label") or None,
                )
            )

        # Drop any malformed (empty title/body) entries.
        tips = [t for t in tips if t.title and t.body]
        log.info("advisor_tips_generated", count=len(tips))
        return tips

    @staticmethod
    def _gather_context(today: date) -> dict:
        with db.session_scope() as s:
            total = s.query(db.Product).count()
            priced = s.query(db.Product).filter(db.Product.price.isnot(None)).count()
            in_stock = s.query(db.Product).filter(db.Product.stock_qty > 0).count()
            with_photos = s.query(db.Product).filter(db.Product.has_photo.is_(True)).count()
            posts_pub = s.query(db.Post).count()
            week_ago = datetime.utcnow() - timedelta(days=7)
            posts_last_week = s.query(db.Post).filter(
                db.Post.published_at >= week_ago
            ).count()
            pending = s.query(db.PostDraft).filter(db.PostDraft.status == "pending").count()

        return {
            "date_human": f"{today.day} {MONTHS_KA[today.month - 1]} {today.year}",
            "weekday_ka": WEEKDAYS_KA[today.weekday()],
            "season_hint": _season_hint(today.month),
            "calendar_slot": brand.WEEKLY_CALENDAR.get(today.weekday(), "B2C"),
            "total_products": total,
            "priced_products": priced,
            "price_pct": round(priced / total * 100) if total else 0,
            "in_stock": in_stock,
            "stock_pct": round(in_stock / total * 100) if total else 0,
            "with_photos": with_photos,
            "photo_pct": round(with_photos / total * 100) if total else 0,
            "posts_published": posts_pub,
            "posts_last_week": posts_last_week,
            "pending_drafts": pending,
        }
