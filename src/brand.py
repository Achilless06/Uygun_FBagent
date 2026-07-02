"""Brandbook constants — the canonical source of truth in code.

Every value here is traceable to a specific page of
`Uygun_Georgia_Brandbook_v3_0.pdf`. Page numbers are noted inline.

These constants are imported by:
  - src/ai/prompts.py        (mission/vision/values → Claude system prompt)
  - src/ai/image_gen.py      (colors, contact block)
  - src/guardrails.py        (banned phrases, address form)
  - src/telegram_bot/admin.py (admin panel labels)
  - src/analytics/report.py  (weekly report template)

When the founder updates the brandbook, this file is updated to match.
Never let the AI hallucinate brand voice — it reads it from here.
"""

from __future__ import annotations

# ─── 1. Company identity (brandbook p. 4) ────────────────────────────────────

COMPANY_NAME = "Uygun Georgia"

MISSION = (
    "საქართველოს მასშტაბით ვამარაგებთ ვულკანიზაციებსა და ავტოსამრეცხაოებს "
    "ხარისხიანი პროდუქციით, რათა თავიანთ მომხმარებელს შესთავაზონ სანდო მომსახურება."
)

VISION = (
    "ვიქცეთ ბათუმისა და მთლიანი დასავლეთ საქართველოს წამყვან მომმარაგებლად "
    "ვულკანიზაცია-სამრეცხაოს სფეროში, ხოლო შემდგომ ეტაპზე გავაფართოვოთ "
    "საქმიანობა საქართველოს დანარჩენ რეგიონებზე."
)

# ─── 2. Brand values (brandbook p. 5) ────────────────────────────────────────
# Each post should lean on ONE dominant value. Generator rotates them.

VALUES = {
    "საიმედოობა": (
        "ვულკანიზაცია უსაფრთხოების საქმეა. ცუდი ხარისხის შეკეთება = "
        "საბურავი ისევ ეფეთქება გზაზე = ავარია."
    ),
    "პროფესიონალიზმი": (
        "კლიენტი პროფესიონალია, ენაც პროფესიონალური უნდა იყოს — "
        "'თქვენ' ფორმაში, კომპეტენტური შინაარსით."
    ),
    "ხელმისაწვდომობა": (
        "შეკვეთა და მიწოდება მარტივი უნდა იყოს. დაგვირეკეთ — გვითხარით — "
        "გავაგზავნით. მიწოდება უფასოა საქართველოს მასშტაბით."
    ),
    "გამჭვირვალობა": (
        "ფასები, ვადები, შემადგენლობა, ხელმისაწვდომობა — ღია ინფორმაცია. "
        "არ ვამბობთ 'დაახლოებით ფასი'. თუ რამე არ ვიცი — 'ვამოწმებ'."
    ),
}

# ─── 3. Audience segments (brandbook p. 6) ───────────────────────────────────

AUDIENCE_B2B = (
    "ვულკანიზაციის სარემონტო სახელოსნოები, ავტოსამრეცხაოები, მცირე ავტოსერვისები. "
    "გადაწყვეტილებას მფლობელი ან მენეჯერი იღებს. შეკვეთა საშუალო/დიდი მოცულობით, "
    "თვეში 1–4-ჯერ. ფასი საბითუმოა, ფასდაკლება მოცულობაზე დამოკიდებული. "
    "აფასებენ სტაბილურ მარაგს, სტაბილურ ფასს, სწრაფ მიწოდებას, ნდობას."
)

AUDIENCE_B2C = (
    "ავტოენთუზიასტები / DIY მძღოლები, რომელთაც სურთ თვითონ მოუარონ მანქანას. "
    "შეკვეთა იშვიათად, ცალკეული პროდუქტი. ფასი საცალოა, ფიქსირებული. "
    "აფასებენ ნათელ ინსტრუქციას, კონსულტაციას, ფასს, მცირე მინიმუმს."
)

# ─── 4. Content slots (Phase 18, 2026-06) ────────────────────────────────────
# Default behavior: every day = "Daily" — product-spotlight on a top-selling /
# in-stock item. Old weekday-based rotation (B2B Mon, B2C Tue, …) was removed
# because the founder wanted a single steady format. Legacy slots B2B/B2C/EDU/
# BTS/LITE/Promo are retained as MANUAL overrides for `/generate B2B` etc.

CalendarSlot = str  # "Daily" (default) | "B2B" | "B2C" | "EDU" | "BTS" | "LITE" | "Promo"

SLOT_DESCRIPTIONS: dict[CalendarSlot, str] = {
    "Daily": (
        "მოთხოვნადი პროდუქცია — ბოლო თვის top-seller ან მარაგში არსებული. "
        "Product Spotlight ფორმატი: სახელი + ფასი + 1 აღწერითი წინადადება. "
        "სამიზნე აუდიტორია შერეულია (B2B + B2C)."
    ),
    "B2B": (
        "მიმართეთ ვულკანიზაცია / ავტოსამრეცხაოს მფლობელს. ფოკუსი: მარაგი, "
        "საბითუმო ფასი, სტაბილური მიწოდება. ტონი — პრაქტიკული, ფასი/მოცულობა."
    ),
    "B2C": (
        "მიმართეთ ავტოენთუზიასტს, რომელიც თვითონ აკეთებს რემონტს. ფოკუსი: "
        "კონკრეტული პროდუქტი, ექსპერტული რჩევა, ხელმისაწვდომი ფასი."
    ),
    "EDU": (
        "ასწავლეთ რაიმე ვულკანიზაციის / ავტოსამრეცხაოს თემაზე — Radial vs Bias, "
        "რეზინის ცემენტის გამოყენება, სეზონური რჩევა და ა.შ. პროდუქტი მეორეხარისხოვანი."
    ),
    "BTS": (
        "Behind the scenes: მაღაზიის ფოტო, გუნდი, მიწოდების პროცესი, "
        "'ერთი დღე Uygun-ში'. პერსონალური, თბილი ტონი."
    ),
    "LITE": (
        "მსუბუქი, ემოციური პოსტი — სუფთა მანქანის ფოტო, შენიშვნა "
        "საქართველოს გზებზე, ხუმრობა. პროდუქტი არ არის სავალდებულო."
    ),
    "Promo": (
        "კონკრეტული აქცია ან შეთავაზება. ფასი ან ფასდაკლება — მხოლოდ "
        "products.xlsx-ში არსებული ციფრებიდან."
    ),
}

DEFAULT_SLOT: CalendarSlot = "Daily"

# ─── 5. Post formats (brandbook p. 15) ───────────────────────────────────────
# Generator rotates between these to avoid monotony.

POST_FORMATS = [
    "Product Spotlight",
    "Educational",
    "Promotional",
    "Behind-the-scenes",
    "Customer Story",
    "Industry / Tip",
    "Light / Emotional",
]

# ─── 6. Colors (brandbook p. 8) ──────────────────────────────────────────────
# Extracted from the logo. Used by image_gen.py.

UYGUN_RED = "#BC1215"
DEEP_BLACK = "#0F0F0F"
PURE_WHITE = "#FFFFFF"
DARK_RED = "#7A0C0E"
LIGHT_GREY = "#F5F5F5"
MID_GREY = "#555555"

# 60/30/10 proportion: white-or-grey 60%, black 30%, red 10%.

# ─── 7. Image specs (brandbook p. 16) ────────────────────────────────────────

IMAGE_SIZE_SQUARE = (1080, 1080)
IMAGE_SIZE_PORTRAIT = (1080, 1350)
IMAGE_SIZE_STORIES = (1080, 1920)

# ─── 8. Contact block (brandbook p. 21) ──────────────────────────────────────
# Appended to every published post.

CONTACT_PHONE = "+995 568 90 90 87"
CONTACT_WHATSAPP = "+995 568 90 90 87"  # same number; for posts that use 💬 WhatsApp: format
CONTACT_ADDRESS = "ბათუმი, მამია ვარშანიძის 189"
DELIVERY_NOTE = "უფასო მიწოდება საქართველოს მასშტაბით"
WORKING_HOURS = "ორშაბათი – შაბათი 10:00 – 19:00"

# Pre-computed digit-only forms used by website href attributes. Keeping them
# here (rather than recomputing in templates) means a phone-number change only
# touches one file.
CONTACT_PHONE_TEL = "+995568909087"           # for href="tel:..."
CONTACT_WHATSAPP_URL = "https://wa.me/995568909087"  # for href="https://..."

# Public social media URLs (website footer + contact page only).
FACEBOOK_URL = "https://www.facebook.com/profile.php?id=61572328379507"
INSTAGRAM_URL = "https://www.instagram.com/uygungeorgia/"

# Canonical public website origin — founder-confirmed 2026-07: uygungeorgia.com
# (NOT uygun.ge, which was never registered). Used by JSON-LD structured data
# and any template that needs an absolute URL.
SITE_URL = "https://uygungeorgia.com"

CONTACT_BLOCK = f"📞 {CONTACT_PHONE}\n📍 {CONTACT_ADDRESS}"

# ─── 9. Brand voice rules (brandbook p. 10-12) ───────────────────────────────
# Encoded as both a system-prompt instruction (see ai/prompts.py) and as
# guardrail validators (see guardrails.py).

# Phrases the brand uses (positive examples — formal "თქვენ" form).
LOVED_PHRASES = [
    "გვაქვს მარაგში",
    "შემოგვიარეთ",
    "მოგვწერეთ",
    "დაგვირეკეთ",
    "გვითხარით რა გჭირდებათ",
    "გავაგზავნით",
    "უფასო მიწოდება საქართველოს მასშტაბით",
]

# Phrases that must never appear (negative examples).
# These are validated by guardrails.check_banned_phrases().
BANNED_PHRASES = [
    "გვაქვს თქვენთვის შესანიშნავი შემოთავაზება",
    "არ გამოტოვოთ ეს უნიკალური შესაძლებლობა",
    "ვინც ნამდვილ ხარისხს უძღვნის",
    "პატივცემულო პარტნიორებო",
    "ფანტასტიკურ შესაძლებლობას",
]

# Phase 18 (2026-06): brand uses formal "თქვენ" form, not informal "შენ".
# Guardrails detect common "შენ"-form markers (informal 2nd-person sing).
# Matched via word-boundary regex in guardrails.check_address_form() to avoid
# prefix false-positives (e.g. "შემოგვიარე" inside formal "შემოგვიარეთ").
SHEN_MARKERS = [
    "შენ",
    "შენი",
    "შენთვის",
    "შენთან",
    "შენს",
    "შემოგვიარე",
    "მოგვწერე",
    "დაგვირეკე",
    "გვითხარი",
    "გაქვს",
    "გჭირდება",
    "შეგიძლია",
    "შემოგვიერთდი",
]

# Tire = "საბურავი" (NOT "სალტე" — explicitly forbidden, brandbook p. 11).
TIRE_CORRECT = "საბურავი"
TIRE_FORBIDDEN = "სალტე"

# Competitor mention guardrail — list grows as needed.
# Brandbook p. 20 §4: never mention competitors by name, logo, or paraphrase.
COMPETITORS_FORBIDDEN: list[str] = [
    # Add specific competitor names as they're identified.
]

# ─── 10. Hashtag pools (brandbook p. 17) ─────────────────────────────────────

HASHTAGS_BRAND = ["#UygunGeorgia", "#UygunBatumi"]
HASHTAGS_INDUSTRY = [
    "#ვულკანიზაცია",
    "#ავტოსამრეცხაო",
    "#საბურავი",
    "#ცემენტი",
    "#ლატკი",
    "#ავტოქიმია",
]
HASHTAGS_GEO = ["#ბათუმი", "#აჭარა", "#საქართველო", "#ქართულიავტო"]

# Recommended composition per post (minimalist format, 2025+): 1 brand + 1 industry
# (+ optional 1 geo) = 2–3 total. Reduced from the prior 3–5 to match the new
# minimal 5-line post format.
MIN_HASHTAGS = 2
MAX_HASHTAGS = 3

# ─── 11. Legal / payment details (brandbook p. 21) ───────────────────────────
# Reserved for future use (e.g. invoice generation). Not included in posts.

LEGAL_ENTITY = "შპს უიგუნ ჯორჯია"
BANK_NAME = "თბს ბანკი"
IBAN = "GE60TB7185736080100011"
TELEGRAM_ADMIN_USERNAME = "@achilless6"
