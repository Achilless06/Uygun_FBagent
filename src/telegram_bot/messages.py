"""Georgian message templates sent to the founder via Telegram.

All user-facing strings in one place so the founder can edit them later
without hunting through handlers. Code, comments, log messages stay in
English; user-facing strings stay in Georgian.

f-strings here use named placeholders — handlers call `.format(...)` rather
than f-string interpolation so the templates can hold curly braces safely
and be edited by non-developers.
"""

# ─── Welcome / main menu / help ──────────────────────────────────────────────

DIVIDER = "━━━━━━━━━━━━━━━━━━━━━━━"

WELCOME = (
    f"{DIVIDER}\n"
    "🤖 *Uygun Georgia Agent*\n"
    "_Facebook ავტომატიზაცია · v0.1_\n"
    f"{DIVIDER}\n\n"
    "👋 *გამარჯობა!*\n"
    "ყოველდღე 11:30-ზე ვამზადებ პოსტს, გიგზავნი დასადასტურებლად, "
    "შენი ✅-ის შემდეგ 12:00-ზე ვაქვეყნებ.\n\n"
    "👇 აირჩიე სექცია მენიუდან."
)

MAIN_MENU = (
    f"{DIVIDER}\n"
    "🤖 *Uygun Georgia Agent*\n"
    f"{DIVIDER}\n\n"
    "{agent_status_line}\n"
    "📦 `{total_products}` პროდუქცია · `{in_stock}` მარაგში\n"
    "📰 `{posts_published}` პოსტი · `{pending_drafts}` ელოდება\n"
    "💰 `${spent:.4f}` / `${budget:.2f}` ({budget_pct}%)\n\n"
    f"{DIVIDER}\n"
    "👇 *მენიუ*"
)

# Backward-compat alias for callers still using MAIN_MENU_HEADER name.
MAIN_MENU_HEADER = MAIN_MENU

UNAUTHORIZED = "⚠️ ეს ბოტი მხოლოდ ერთ ადამიანს ემსახურება."

HELP = (
    "📋 *ბრძანებები*\n\n"
    "*💬 ჩატი*\n"
    "უბრალოდ მომწერე — დაგეხმარები ლაივში (პოსტი, რჩევა, სტრატეგია).\n"
    "/forget\\_chat — ჩატის ისტორიის წაშლა\n\n"
    "*🧾 გაყიდვები*\n"
    "/sale `კოდი რაოდენობა ფასი` — გაყიდვის ჩაწერა\n"
    "/sales — ბოლო გაყიდვები\n"
    "/sales\\_summary — დღევანდელი + თვის ანალიზი\n"
    "/undo\\_sale `id` — გაყიდვის წაშლა\n"
    "/import\\_sales — თვის ZIP-ის იმპორტი → Airtable Top-15\n\n"
    "*🧠 მახსოვრობა*\n"
    "/remember `ტექსტი` — შენი preference-ის შენახვა\n"
    "/memories — შენახული მახსოვრობა\n"
    "/forget `id` — კონკრეტული მახსოვრობის წაშლა\n\n"
    "*ნავიგაცია*\n"
    "/menu — მთავარი მენიუ\n"
    "/dashboard — სტატისტიკის ხედი\n"
    "/tips — დღევანდელი რჩევები\n\n"
    "*კატალოგი*\n"
    "/products — პროდუქციის სია\n"
    "/inventory — მარაგი\n"
    "/categories — კატეგორიები\n"
    "/search `სიტყვა` — ძებნა (მაგ: `/search ცემენტი`)\n\n"
    "*მართვა*\n"
    "/toggle\\_stock `კოდი` — მარაგის ცვლილება\n"
    "/refind\\_photo `კოდი` — ფოტოს ხელახლა მოძებნა\n"
    "/cleanup\\_drafts — წაიშალოს გამოუქვეყნებელი draft-ები\n"
    "/reimport — products.xlsx-ის ხელახლა იმპორტი\n"
    "/test\\_fb — Facebook ტოკენის შემოწმება\n"
    "/scheduler — ავტო-სქედულერის სტატუსი\n"
    "/test\\_schedule — ხელით გაუშვი ავტო-გენერაცია\n\n"
    "*პარამეტრები*\n"
    "/settings — სრული ხედი\n"
    "/set\\_active `true`/`false`\n"
    "/set\\_gen\\_time `HH:MM`\n"
    "/set\\_publish\\_time `HH:MM`\n"
    "/set\\_budget `USD`\n\n"
    "*სხვა*\n"
    "/spend — API ხარჯი\n"
    "/help — ეს მესიჯი"
)

# ─── Tips / Advisor ──────────────────────────────────────────────────────────

TIPS_HEADER = (
    f"{DIVIDER}\n"
    "💡 *რჩევები · {date_human}*\n"
    "_{weekday} · ბათუმი_\n"
    f"{DIVIDER}\n\n"
)
TIPS_FOOTER = f"\n{DIVIDER}\n_განახლდება ყოველდღე ერთხელ_"
TIPS_TIP_TEMPLATE = "{icon}  *{title}*\n   {body}\n\n"
TIPS_LOADING = "💭 ანალიტიკოსი ფიქრობს… (5-10 წამი)"
TIPS_EMPTY = (
    "💡 *რჩევები*\n\n"
    "სამწუხაროდ, ვერ მოვახერხე რჩევების მომზადება.\n"
    "ხშირი მიზეზები: API ლიმიტი, ქსელის შეცდომა.\n"
    "ცადე მოგვიანებით."
)
TIPS_CACHED_NOTE = "_📌 ნაჩვენებია დღევანდელი დაკეშირებული რჩევები. განახლებისთვის ⤵️_"

# ─── Chat (conversational mode) ──────────────────────────────────────────────

CHAT_THINKING = "💭 _ვფიქრობ…_"
CHAT_ERROR = "😕 ვერ შევძელი პასუხის გენერაცია. სცადე ისევ."

CHAT_INTRO = (
    f"{DIVIDER}\n"
    "💬 *ჩატ-რეჟიმი*\n"
    f"{DIVIDER}\n\n"
    "მე ვარ შენი SMM მენეჯერი. უბრალოდ მომწერე ნებისმიერი ფრაზა:\n\n"
    "მაგალითად:\n"
    "• _\"დღეს რამე პოსტი მოიფიქრე\"_\n"
    "• _\"უფრო აგრესიული ტონი დაწერე\"_\n"
    "• _\"ახალგაზრდებზე გათვალე\"_\n"
    "• _\"emoji-ები შეამცირე\"_\n"
    "• _\"ცემენტ #29-ზე ცალკე პოსტი\"_\n\n"
    "_თუ რამე გინდა რომ დაგიმახსოვრო (preference, style) — გამიყენე /remember._"
)

# ─── Memory commands ─────────────────────────────────────────────────────────

MEMORY_USAGE = (
    "🧠 *მახსოვრობა*\n\n"
    "გამოყენება: `/remember შენი preference-ის ტექსტი`\n\n"
    "მაგალითები:\n"
    "• `/remember არ მიყვარს corporate ტექსტი`\n"
    "• `/remember ვამჯობინებ მოკლე aggressive hook-ებს`\n"
    "• `/remember emoji limit = moderate`\n"
    "• `/remember მე ვარ აჩი, მფლობელი`"
)

MEMORY_ADDED = "✅ შენახულია მახსოვრობაში (id: `{id}`)\n\n_{content}_"
MEMORY_LIST_HEADER = "🧠 *მახსოვრობა* — `{count}` ჩანაწერი\n\n"
MEMORY_LIST_ROW = "`{id}` · [{category}] {content}\n"
MEMORY_EMPTY = (
    "🧠 *მახსოვრობა*\n\n"
    "ჯერ ცარიელია. გამოიყენე `/remember ტექსტი`\n\n"
    "მაგ: `/remember ვამჯობინებ მოკლე ტექსტებს`"
)
MEMORY_FORGET_USAGE = "გამოყენება: `/forget id`\n\nმაგ: `/forget 5`"
MEMORY_FORGET_OK = "🗑 წაიშალა მახსოვრობა `{id}`."
MEMORY_FORGET_NOT_FOUND = "❌ მახსოვრობა `{id}` ვერ მოიძებნა."

# ─── Forget chat ─────────────────────────────────────────────────────────────

CHAT_CLEARED = "🗑 ჩატის ისტორია წაიშალა (`{count}` მესიჯი)."

# ─── Sales / Bookkeeping ─────────────────────────────────────────────────────

SALES_HUB = (
    f"{DIVIDER}\n"
    "🧾 *გაყიდვები*\n"
    f"{DIVIDER}\n\n"
    "📅 *დღევანდელი*\n"
    "• ტრანზაქცია: `{today_count}`\n"
    "• ჯამი: `{today_revenue:.2f}` ₾\n\n"
    "📅 *ამ თვის*\n"
    "• ტრანზაქცია: `{month_count}`\n"
    "• ჯამი: `{month_revenue:.2f}` ₾\n"
)

SALE_USAGE = (
    "🧾 *ახალი გაყიდვა*\n\n"
    "*ერთ-ხაზიანი:*\n"
    "`/sale კოდი რაოდენობა ფასი`\n\n"
    "მაგ:\n"
    "• `/sale 29 5 25` — 5 ცალი 29-კოდიანი 25₾-ად\n"
    "• `/sale 7 1 1.8` — 1 ცალი 7-კოდიანი 1.8₾-ად\n\n"
    "_ან მენიუდან: 🧾 → ➕ ახალი გაყიდვა (ნაბიჯ-ნაბიჯ)_"
)

SALE_RECORDED = (
    "✅ *შენახულია გაყიდვა* `#{id}`\n\n"
    "🏷 `{code}` — {name}\n"
    "📦 რაოდენობა: `{qty:g}`\n"
    "💵 ცალი: `{unit_price:g}` ₾\n"
    "═══════════════════\n"
    "💰 *ჯამი: `{total:.2f}` ₾*"
)

SALE_INVALID_FORMAT = (
    "❌ არასწორი ფორმატი.\n\n"
    "გამოყენება: `/sale კოდი რაოდენობა ფასი`\n"
    "მაგ: `/sale 29 5 25`"
)
SALE_PRODUCT_NOT_FOUND = "❌ პროდუქცია კოდით `{code}` ვერ მოიძებნა."
SALE_INVALID_NUMBER = "❌ რაოდენობა და ფასი უნდა იყოს რიცხვი (მაგ: `5` ან `1.5`)."

SALES_LIST_HEADER = "🧾 *ბოლო გაყიდვები* — `{count}`\n\n"
SALES_LIST_ROW = "`#{id}` · `{code}` × {qty:g} = *{total:.2f}* ₾  _({when})_\n"
SALES_EMPTY = (
    "🧾 *გაყიდვები*\n\n"
    "ჯერ ცარიელია. გამოიყენე `/sale კოდი რაოდენობა ფასი`"
)

SALE_UNDO_USAGE = "გამოყენება: `/undo_sale id`\n\nმაგ: `/undo_sale 5`"
SALE_UNDO_OK = "🗑 წაიშალა გაყიდვა `#{id}`."
SALE_UNDO_NOT_FOUND = "❌ გაყიდვა `#{id}` ვერ მოიძებნა."

# ── Sale detail / edit / delete ──

SALE_DETAIL = (
    f"{DIVIDER}\n"
    "🧾 *გაყიდვა* `#{id}`\n"
    f"{DIVIDER}\n\n"
    "🏷 `{code}` — {name}\n"
    "📦 რაოდენობა: `{qty:g}`\n"
    "💵 ცალის ფასი: `{unit_price:g}` ₾\n"
    "═══════════════════\n"
    "💰 *ჯამი: `{total:.2f}` ₾*\n\n"
    "📝 შენიშვნა: {notes}\n"
    "🕐 თარიღი: {when} ({timestamp})"
)
SALE_DETAIL_NO_NOTES = "_—_"

SALE_EDIT_MENU = (
    "✏️ *გაყიდვის რედაქტირება* `#{id}`\n\n"
    "🏷 `{code}` — {name}\n"
    "📦 {qty:g} × {unit_price:g} ₾ = *{total:.2f}* ₾\n\n"
    "რას ცვლი?"
)
SALE_EDIT_ASK_QTY = (
    "📦 *ახალი რაოდენობა*\n\n"
    "მიმდინარე: `{current:g}`\n\n"
    "გამოგზავნე ახალი მნიშვნელობა (მაგ: `5` ან `0.5`)\n"
    "_გასაუქმებლად: /cancel_"
)
SALE_EDIT_ASK_PRICE = (
    "💵 *ახალი ცალის ფასი (₾)*\n\n"
    "მიმდინარე: `{current:g}` ₾\n\n"
    "გამოგზავნე ახალი მნიშვნელობა (მაგ: `25`)\n"
    "_გასაუქმებლად: /cancel_"
)
SALE_EDIT_ASK_NOTES = (
    "📝 *ახალი შენიშვნა*\n\n"
    "მიმდინარე: {current}\n\n"
    "გამოგზავნე ახალი ტექსტი, ან `-` შენიშვნის წასაშლელად\n"
    "_გასაუქმებლად: /cancel_"
)
SALE_EDIT_DONE = (
    "✅ *განახლდა გაყიდვა* `#{id}`\n\n"
    "📦 {qty:g} × {unit_price:g} ₾ = *{total:.2f}* ₾"
)

SALE_DELETE_CONFIRM = (
    "⚠️ *ნამდვილად წავშალო?*\n\n"
    "🧾 გაყიდვა `#{id}`\n"
    "🏷 `{code}` — {name}\n"
    "💰 `{total:.2f}` ₾"
)
SALE_DELETED = "🗑 წაიშალა გაყიდვა `#{id}`."

# Button labels
BTN_SALE_EDIT = "✏️ რედაქტირება"
BTN_SALE_DELETE = "🗑 წაშლა"
BTN_SALE_EDIT_QTY = "📦 რაოდენობა"
BTN_SALE_EDIT_PRICE = "💵 ფასი"
BTN_SALE_EDIT_NOTES = "📝 შენიშვნა"
BTN_CONFIRM_DELETE = "✅ დიახ, წაშალე"
BTN_CANCEL_DELETE = "❌ არა"

SALES_SUMMARY = (
    f"{DIVIDER}\n"
    "📊 *გაყიდვების ანალიზი*\n"
    f"{DIVIDER}\n\n"
    "📅 *დღევანდელი*\n"
    "• ტრანზაქცია: `{today_count}`\n"
    "• ერთეული: `{today_units:g}`\n"
    "• ჯამი: `{today_revenue:.2f}` ₾\n\n"
    "📅 *ამ თვის*\n"
    "• ტრანზაქცია: `{month_count}`\n"
    "• ერთეული: `{month_units:g}`\n"
    "• ჯამი: `{month_revenue:.2f}` ₾\n\n"
    "{top_block}"
)
SALES_SUMMARY_TOP_HEADER = "🏆 *ტოპ პროდუქცია (თვის)*\n"
SALES_SUMMARY_TOP_ROW = "`{n}.` `{code}` · {name} — *{revenue:.2f}* ₾  ({qty:g} ცალი)\n"
SALES_SUMMARY_NO_DATA = "_ჯერ მონაცემები არ არის._"

# FSM flow
SALE_FSM_ASK_CODE = (
    "🧾 *ახალი გაყიდვა — ნაბიჯი 1/3*\n\n"
    "გამოგზავნე *პროდუქტის კოდი*\n\n"
    "მაგ: `29`\n"
    "_გასაუქმებლად: /cancel_"
)
SALE_FSM_ASK_QTY = (
    "🧾 *ნაბიჯი 2/3*\n\n"
    "✅ პროდუქცია: `{code}` — {name}\n\n"
    "გამოგზავნე *რაოდენობა*\n\n"
    "მაგ: `5` ან `0.5`\n"
    "_გასაუქმებლად: /cancel_"
)
SALE_FSM_ASK_PRICE = (
    "🧾 *ნაბიჯი 3/3*\n\n"
    "✅ პროდუქცია: `{code}` — {name}\n"
    "✅ რაოდენობა: `{qty:g}`\n\n"
    "გამოგზავნე *ცალის ფასი ლარში*\n\n"
    "მაგ: `25` ან `1.8`\n"
    "_გასაუქმებლად: /cancel_"
)
SALE_FSM_CANCELLED = "❌ გაუქმდა."

# ─── Post Approval Flow ──────────────────────────────────────────────────────

GENERATE_LOADING = "🤖 _ვამზადებ პოსტს… (10-30 წამი)_"
GENERATE_USAGE = (
    "📝 *პოსტის გენერაცია*\n\n"
    "გამოყენება:\n"
    "`/generate` — Daily (ნაგულისხმევი) · მოთხოვნადი პროდუქცია\n"
    "`/generate B2B` — კონკრეტული სლოტი (ხელით override)\n\n"
    "_სლოტები: Daily, B2B, B2C, EDU, BTS, LITE, Promo_"
)
GENERATE_FAILED = "❌ გენერაცია ვერ მოხერხდა. დეტალები ლოგებშია."
GENERATE_INVALID_SLOT = "❌ უცნობი სლოტი. სცადე: Daily / B2B / B2C / EDU / BTS / LITE / Promo"

# Preview message — sent as a caption when there's an image, or as a plain
# message when no image. Caption limit on Telegram is 1024 chars.
PREVIEW_HEADER = (
    f"{DIVIDER}\n"
    "📝 *პოსტის Preview* — `{slot}`\n"
    "{product_line}"
    f"{DIVIDER}\n\n"
)
PREVIEW_PRODUCT_LINE = "🏷 `{code}` · {name} ({price})\n"
PREVIEW_NO_PRODUCT_LINE = ""
PREVIEW_FOOTER = (
    f"\n{DIVIDER}\n"
    "🏷 {hashtags}\n"
    "{violation_summary}"
)
PREVIEW_VIOLATIONS_HEADER = "⚠️ შენიშვნები:\n{lines}"
PREVIEW_NO_VIOLATIONS = "✅ ყველა შემოწმება გაიარა"

PREVIEW_APPROVED_DRYRUN = (
    "✅ *დადასტურდა* — draft `#{id}`\n\n"
    "🧪 _DRY\\_RUN რეჟიმი — Facebook-ზე ფაქტობრივად არ გამოქვეყნდა._\n"
    "_როცა მზად ხარ რეალურ პუბლიკაციაზე: .env-ში DRY\\_RUN=false._"
)
PREVIEW_PUBLISHED = (
    "🚀 *გამოქვეყნდა Facebook-ზე*\n\n"
    "📰 Post: `{fb_post_id}`\n"
    "🔗 {permalink}"
)
PREVIEW_PUBLISH_FAILED = (
    "⚠️ *დადასტურდა, მაგრამ FB-ზე გამოქვეყნება ჩავარდა*\n\n"
    "Draft `#{id}` მონიშნულია როგორც approved (DB-ში).\n"
    "შეცდომა:\n`{error}`"
)
PREVIEW_PUBLISHING = "🚀 _ვაქვეყნებ Facebook-ზე…_"

FB_TEST_OK = (
    "✅ *Facebook ტოკენი მუშაობს*\n\n"
    "📄 Page: {name}\n"
    "🆔 ID: `{id}`\n"
    "📁 Category: {category}"
)
FB_TEST_FAILED = "❌ *Facebook ტოკენი ვერ მუშაობს*\n\n`{error}`"
FB_TEST_NO_CREDS = (
    "❌ Meta credentials არ არის შევსებული.\n\n"
    ".env-ში გჭირდება: META\\_APP\\_ID, META\\_APP\\_SECRET, "
    "FB\\_PAGE\\_ID, FB\\_PAGE\\_ACCESS\\_TOKEN"
)

# ─── Draft cleanup ───────────────────────────────────────────────────────────

CLEANUP_DRAFTS_EMPTY = "✅ მოუსაგვერი draft-ი არ არის."
CLEANUP_DRAFTS_DONE = (
    "🗑 წაიშალა *{count}* მოუსაგვერი draft-ი\n"
    "_(status: pending / edited / rejected — არ შეხებია published-ს)_"
)

# ─── Photo refind ────────────────────────────────────────────────────────────

REFIND_PHOTO_USAGE = (
    "📸 *ფოტოს ხელახლა მოძებნა*\n\n"
    "გამოყენება: `/refind_photo კოდი`\n\n"
    "მაგ: `/refind_photo 29`\n\n"
    "_ფოტოს cache იშლება და ხელახლა მოძებნება ვებიდან._"
)
REFIND_PHOTO_NOT_FOUND = "❌ პროდუქცია კოდით `{code}` ვერ მოიძებნა."
REFIND_PHOTO_SEARCHING = "🔎 _ვძებნი ფოტოს `{code}` — {name}_…"
REFIND_PHOTO_SUCCESS = (
    "✅ *ფოტო ხელახლა მოიძებნა* `{code}`\n\n"
    "📸 {name}\n"
    "_მომავალ /generate-ში ეს ფოტო გამოიყენება._"
)
REFIND_PHOTO_FAILED = (
    "⚠️ ვერ მოვძებნე ფოტო `{code}`-ისთვის.\n\n"
    "ფოლბექი — branded text card გამოიყენება პოსტში."
)

# ─── Budget circuit breaker ──────────────────────────────────────────────────

BUDGET_WARN_80 = (
    "⚠️ *ბიუჯეტის გაფრთხილება*\n\n"
    "ამ თვის ხარჯი 80%-ს გადააჭარბა.\n"
    "💰 `${spent:.4f}` / `${cap:.2f}` (`{pct:.0f}%`)\n\n"
    "_აგენტი ისევ მუშაობს. ლიმიტამდე {remaining:.2f}$ დარჩა._"
)
BUDGET_BLOCK_100 = (
    "🛑 *ბიუჯეტი ამოწურულია*\n\n"
    "ამ თვის ხარჯი 100%-ს მიაღწია.\n"
    "💰 `${spent:.4f}` / `${cap:.2f}`\n\n"
    "🔴 აგენტი დროებით პაუზაშია (agent\\_active=false).\n"
    "გასაგრძელებლად:\n"
    "1. გაზარდე ბიუჯეტი: /set\\_budget `25`\n"
    "2. ან აქტიური გახადე: /set\\_active `true`"
)

# ─── Sales import (/import_sales — monthly Airtable workflow) ────────────────

IMPORT_SALES_PROMPT = (
    f"{DIVIDER}\n"
    "📥 *თვის გაყიდვების იმპორტი*\n"
    f"{DIVIDER}\n\n"
    "გამომიგზავნე *ერთი ZIP ფაილი* — შეფუთული თვის ფოლდერი "
    "(მაგ. `ივნისი 06 2026.zip`).\n\n"
    "*როგორ:* Finder-ში → marc-დაკიდე ფოლდერი → Right-click → *Compress*. "
    "მიღებული `.zip` დააგდე ჩატში.\n\n"
    "📊 მე გავაანალიზებ ფაილებს, გაჩვენებ Top-15 ბესტსელერებს და "
    "შევანახავ Airtable-ში.\n\n"
    "_გასაუქმებლად: /cancel_"
)
IMPORT_SALES_NEED_ZIP = (
    "📥 ZIP ფაილი მინდა (.zip). გადააფუთე თვის ფოლდერი — Finder → "
    "Right-click → Compress.\n\n_გასაუქმებლად: /cancel_"
)
IMPORT_SALES_DOWNLOADING = "⬇️ _ფაილს გადმოვწერ…_"
IMPORT_SALES_DOWNLOAD_FAILED = "❌ გადმოწერა ვერ მოხერხდა.\n\n`{error}`"
IMPORT_SALES_PARSING = "🔍 _ფაილს ვშლი და ვაანალიზებ…_"
IMPORT_SALES_NO_DATA = (
    "⚠️ ZIP-ში გაყიდვის row არ ვიპოვე.\n\n"
    "შემოწმდი:\n"
    "• `.xlsx` ფაილებია შიგნით\n"
    "• Sales ან satis sheet-ი არსებობს\n"
    "• C2 უჯრაში თარიღია (DD/MM/YYYY)"
)
IMPORT_SALES_MIXED_MONTHS = (
    "⚠️ ZIP შეიცავს {count} თვის ფაილს. Top-15-ისთვის ვიყენებ "
    "ყველაზე ცხრიან თვეს: *{dominant}*. დანარჩენი row-ები მაინც "
    "ჩაიწერება DB-ში.\n\n"
)
IMPORT_SALES_PREVIEW = (
    f"{DIVIDER}\n"
    "📊 *Preview — {period}*\n"
    f"{DIVIDER}\n\n"
    "{warning}"
    "📂 ფაილი: `{files}`\n"
    "🧾 row: `{rows}`\n"
    "💰 ჯამი: *{revenue:,.2f}* ₾\n"
    "🏷 უნიკალური კოდი: `{unique}`\n"
    "📅 {date_range}\n"
    "{unknown}\n\n"
    "ჩავწერო DB-ში + Airtable Top-15-ში?"
)
IMPORT_BTN_CONFIRM = "✅ დადასტურება"
IMPORT_BTN_CANCEL = "❌ გაუქმება"
IMPORT_SALES_CANCELLED = "❌ იმპორტი გაუქმდა."
IMPORT_SALES_WORKING = "⚙️ _ვწერ DB-ში + Airtable-ში…_"
IMPORT_SALES_COMMIT_FAILED = "❌ იმპორტი ჩავარდა.\n\n`{error}`"
IMPORT_SALES_DONE = (
    f"{DIVIDER}\n"
    "✅ *იმპორტი დასრულდა — {period}*\n"
    f"{DIVIDER}\n\n"
    "💾 DB: `{inserted}` row ჩაიწერა (`{deleted}` ძველი წაიშალა)\n"
    "{airtable_status}\n"
    "{airtable_url}\n\n"
    "🏆 *Top-5:*\n"
    "{top_summary}\n\n"
    "_სრული Top-15: Airtable-ში → Monthly Top Sellers → Period={period}_"
)

# ─── Inventory low-stock alert ───────────────────────────────────────────────

INVENTORY_LOW_HEADER = (
    "📦 *მცირე მარაგი — {count} პროდუქცია*\n\n"
    "შემდეგი პროდუქცია ≤ `{threshold}` ერთეულზე ჩამოვიდა:\n\n"
)
INVENTORY_LOW_ROW = "• `{code}` · {name} — *{stock}* ცალი\n"
INVENTORY_LOW_FOOTER = (
    "\n💡 _admin-ში შესწორება: /admin/products_\n"
    "_ზღვრის შეცვლა: /admin/settings_"
)
PREVIEW_REJECTED = "❌ უარყოფილია. ვცდი სხვა მიდგომით…"
PREVIEW_EDIT_PROMPT = (
    "✏️ *რას შეცვალო?*\n\n"
    "მომწერე free-text მითითება, მაგ:\n"
    "• _\"უფრო აგრესიული ტონი დაწერე\"_\n"
    "• _\"emoji-ები შეამცირე\"_\n"
    "• _\"ფასი ამოშალე\"_\n"
    "• _\"მოკლე გახადე\"_\n\n"
    "_გასაუქმებლად: /cancel_"
)
PREVIEW_REGENERATING = "🔄 _თავიდან ვაგენერირებ…_"

# Button labels
BTN_APPROVE = "✅ დადასტურება"
BTN_EDIT = "✏️ რედაქტირება"
BTN_REJECT = "❌ უარყოფა"
BTN_GEMINI_IMAGE = "🎨 Gemini-image"

BTN_MENU_GENERATE = "📝 ახალი პოსტი"
BTN_MENU_SALES = "🧾 გაყიდვები"
BTN_SALES_NEW = "➕ ახალი გაყიდვა"
BTN_SALES_RECENT = "📋 ბოლო გაყიდვები"
BTN_SALES_SUMMARY = "📊 ანალიზი"

# ─── Dashboard (with visual bars) ────────────────────────────────────────────

DASHBOARD = (
    "📊 *Dashboard*\n"
    "_{date}_\n\n"
    "*კატალოგი — {total_products} პროდუქცია*\n"
    "ფასით:    {priced_bar} `{priced_pct}%`\n"
    "ფოტოთი:   {photos_bar} `{photos_pct}%`\n"
    "მარაგში:  {stock_bar} `{stock_pct}%`\n\n"
    "*Facebook პოსტები*\n"
    "📰 გამოქვეყნებული: `{posts_published}`\n"
    "📅 ბოლო 7 დღე: `{posts_last_week}`\n"
    "⏳ დასადასტურებლად: `{pending_drafts}`\n\n"
    "*აგენტი*\n"
    "{agent_status} გენერაცია `{gen_time}` · პუბლიკაცია `{publish_time}`\n\n"
    "*ბიუჯეტი (თვის)*\n"
    "{budget_bar} `${spent:.2f}` / `${budget:.0f}` (`{budget_pct}%`)"
)

# ─── Products list (paginated) ───────────────────────────────────────────────

PRODUCTS_PAGE_HEADER = "🏷 *პროდუქცია* — გვერდი `{page}/{total_pages}` (`{total}` სულ)\n"
PRODUCTS_PAGE_FOOTER = "\nტაპი პროდუქტის ნომერზე → დეტალები"
PRODUCTS_ROW = "{stock_icon} `{code}` · {name} — *{price}*\n"
PRODUCTS_EMPTY = "კატალოგი ცარიელია. გაუშვი /reimport"

STOCK_IN = "🟢"
STOCK_OUT = "🔴"

# ─── Product detail card ─────────────────────────────────────────────────────

PRODUCT_DETAIL = (
    "🏷 *პროდუქტი*\n\n"
    "*კოდი:* `{code}`\n"
    "*დასახელება:* {name}\n"
    "*ფასი:* {price}\n"
    "*მარაგი:* {stock_label}\n"
    "*კატეგორია:* {category}\n"
    "*ფოტო:* {photo_status}\n"
    "*ბოლო პოსტში:* {last_featured}\n"
)

PRODUCT_NOT_FOUND = "❌ პროდუქცია კოდით `{code}` ვერ მოიძებნა."
PRODUCT_PHOTO_YES = "✅ data/photos/{code} - ფოლდერშია"
PRODUCT_PHOTO_NO = "❌ არ არის"
PRODUCT_LAST_FEATURED_NEVER = "ჯერ არ ყოფილა"
PRODUCT_STOCK_IN_LABEL = "🟢 მარაგშია"
PRODUCT_STOCK_OUT_LABEL = "🔴 ამოწურულია"

# ─── Inventory ───────────────────────────────────────────────────────────────

INVENTORY_HEADER_IN_STOCK = "🟢 *მარაგში:* `{count}` პროდუქცია\n"
INVENTORY_HEADER_OUT = "🔴 *ამოწურულია:* `{count}` პროდუქცია\n"
INVENTORY_EMPTY = "✅ ყველა პროდუქცია მარაგშია!"
INVENTORY_ROW = "🔴 `{code}` · {name}\n"

# ─── Search ──────────────────────────────────────────────────────────────────

SEARCH_USAGE = (
    "🔍 *ძებნა*\n\n"
    "გამოყენება: `/search სიტყვა`\n\n"
    "მაგალითები:\n"
    "• `/search ცემენტი`\n"
    "• `/search ლატკა`\n"
    "• `/search 100` (კოდის მიხედვით)\n"
)
SEARCH_HEADER = "🔍 *ძებნა:* `{query}` — `{count}` შედეგი\n\n"
SEARCH_EMPTY = "🔍 *ძებნა:* `{query}`\n\nარაფერი იპოვა. სცადე სხვა სიტყვა."
SEARCH_TRUNCATED = "\n_…მაჩვენე ბოლო {hidden} შედეგი ცხრება. დააზუსტე ძებნა._"

# ─── Categories ──────────────────────────────────────────────────────────────

CATEGORIES_HEADER = "📁 *კატეგორიები* — `{count}` სულ\n\nტაპი კატეგორიის სახელზე → ნახე პროდუქცია\n"
CATEGORIES_ROW = "`{count:>3}`  ·  *{name}*\n"
CATEGORY_HEADER = "📁 *{category}* — `{count}` პროდუქცია (გვერდი `{page}/{pages}`)\n\n"
CATEGORIES_EMPTY = "კატეგორიები არ არის."

# ─── Toggle stock ────────────────────────────────────────────────────────────

TOGGLE_USAGE = "გამოყენება: `/toggle_stock კოდი`\n\nმაგ: `/toggle_stock 1`"
TOGGLE_NOT_FOUND = "❌ პროდუქცია კოდით `{code}` ვერ მოიძებნა."
TOGGLE_NOW_IN_STOCK = "🟢 `{code}` — {name}\nახლა მარაგშია."
TOGGLE_NOW_OUT_OF_STOCK = "🔴 `{code}` — {name}\nახლა მარაგი ამოწურულია."

# ─── Settings ────────────────────────────────────────────────────────────────

SETTINGS_VIEW = (
    "⚙ *პარამეტრები*\n\n"
    "• `agent_active` = `{agent_active}`\n"
    "• `post_gen_time` = `{gen_time}`\n"
    "• `post_publish_time` = `{publish_time}`\n"
    "• `monthly_budget_usd` = `{budget}`\n"
    "• `tone_mode` = `{tone}`\n"
    "• `paused_until` = `{paused_until}`\n\n"
    "*შესაცვლელად:*\n"
    "/set\\_active `true` ან `false`\n"
    "/set\\_gen\\_time `HH:MM`\n"
    "/set\\_publish\\_time `HH:MM`\n"
    "/set\\_budget `USD`\n"
    "/pause\\_until `YYYY-MM-DD`  ·  /resume"
)

SETTINGS_UPDATED = "✅ შენახულია: `{key}` = `{value}`"
SETTINGS_INVALID_TIME = "❌ არასწორი ფორმატი. გამოიყენე `HH:MM` (მაგ: `11:30`)."
SETTINGS_INVALID_BOOL = "❌ მიუთითე `true` ან `false`."
SETTINGS_INVALID_NUMBER = "❌ მიუთითე რიცხვი."
SETTINGS_INVALID_DATE = "❌ არასწორი ფორმატი. გამოიყენე `YYYY-MM-DD` (მაგ: `2026-06-15`)."
SETTINGS_DATE_IN_PAST = "❌ თარიღი მომავალში უნდა იყოს."
SETTINGS_USAGE = "გამოყენება: `{command}` `მნიშვნელობა`"

PAUSE_SET = (
    "🌴 *შვებულების რეჟიმი ჩართულია*\n\n"
    "ავტომატური გენერაცია შეჩერებულია `{date}`-მდე.\n"
    "ამ თარიღამდე არ მოგწერ პოსტის approval-ისთვის.\n\n"
    "_გასათიშად:_ /resume"
)
PAUSE_CLEARED = "✅ შვებულების რეჟიმი გათიშულია — ბოტი ისევ ნორმალურად მუშაობს."
PAUSE_NONE = "ℹ️ შვებულების რეჟიმი არ არის ჩართული."

# ─── Spend ───────────────────────────────────────────────────────────────────

SPEND_VIEW = (
    "💰 *API ხარჯი*\n\n"
    "{budget_bar}\n\n"
    "• თვის ხარჯი (MTD): `${spent:.4f}`\n"
    "• ლიმიტი: `${cap:.2f}`\n"
    "• გამოყენებული: `{pct:.1f}%`\n\n"
    "_ფაზა 8-ში დაემატება დეტალური სტატისტიკა._"
)

# ─── Reimport ────────────────────────────────────────────────────────────────

REIMPORT_STARTING = "📥 იმპორტი იწყება…"
REIMPORT_DONE = (
    "✅ *იმპორტი დასრულდა*\n\n"
    "🆕 ახალი: `{inserted}`\n"
    "🔄 განახლდა: `{updated}`\n"
    "✓ უცვლელი: `{unchanged}`\n"
    "⏭ გამოტოვებული: `{skipped}`\n"
)
REIMPORT_ERROR = "❌ იმპორტი ჩავარდა:\n`{error}`"

# ─── Stubs ───────────────────────────────────────────────────────────────────

STUB_COMING_SOON = "🚧 ეს სექცია მზადდება. ძალაში შემოვა შემდეგ ფაზაში."

# ─── Generic ────────────────────────────────────────────────────────────────

GENERIC_ERROR = "❌ შეცდომა მოხდა. დეტალები ლოგებშია."

# ─── Button labels ───────────────────────────────────────────────────────────

BTN_BACK = "⬅ უკან"
BTN_BACK_TO_MENU = "🏠 მთავარი მენიუ"
BTN_PREV = "◀ წინა"
BTN_NEXT = "შემდეგი ▶"
BTN_TOGGLE_STOCK = "🔄 მარაგის ცვლილება"
BTN_REFRESH = "🔃 განახლება"

# Main menu buttons
BTN_MENU_CHAT = "💬 ჩატი"
BTN_MENU_TIPS = "💡 რჩევები"
BTN_MENU_MEMORIES = "🧠 მახსოვრობა"
BTN_MENU_DASHBOARD = "📊 Dashboard"
BTN_MENU_PRODUCTS = "🏷 პროდუქცია"
BTN_MENU_INVENTORY = "📦 მარაგი"
BTN_MENU_SEARCH = "🔍 ძებნა"
BTN_MENU_CATEGORIES = "📁 კატეგორიები"
BTN_MENU_SETTINGS = "⚙ პარამეტრები"
BTN_MENU_SPEND = "💰 ხარჯი"
BTN_MENU_HELP = "❓ დახმარება"

BTN_TIPS_REFRESH = "🔃 ახალი რჩევები"
