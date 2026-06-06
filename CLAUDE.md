# CLAUDE.md — briefing for future Claude Code sessions

## What this is
Uygun Georgia (Batumi vulcanization + car-wash chemical supplier) runs its
Facebook Page through a Telegram-controlled AI agent. Same SQLite DB also
backs a public brand site (`src/web/`). **Founder:** non-technical solo founder
(Achi). Speaks Georgian. Wants short replies, concrete actions. Brandbook
(`Uygun_Georgia_Brandbook_v3_0.pdf`) is canonical — if founder feedback
contradicts it, founder wins.

## Two hard rules — never break
1. **Human-in-the-loop publishing.** Every FB post requires a manual ✅ tap
   in Telegram. No autopublish, no timeout fallback.
2. **No invented data.** Prices/stock come from `products` only.
   `src/guardrails.py` enforces this — never weaken it.

## Tech stack (versions matter)
Python **3.11** (Railway pinned) · aiogram **3.13** (new dispatcher/router/FSM)
· APScheduler **3.10** · google-genai **2.4** (≥1.0 for `ThinkingConfig`)
· anthropic **0.40** · SQLAlchemy **2.x** (`Mapped[...]`) · Pillow **10.4**
· ddgs **9.x** (was `duckduckgo-search`) · FastAPI **0.115** + Jinja2 **3.1**.
Fonts: `assets/fonts/NotoSansGeorgian.ttf` — Georgian + Latin + digits + ₾;
don't switch to system fonts.

**Gemini `thinking_budget=0` gotcha:** always set in `gemini_client.py`.
Otherwise the model burns `max_output_tokens` on hidden chain-of-thought and
JSON output truncates. Most subtle landmine in the codebase.

## Architecture
`telegram_bot/*` (aiogram polling) + `scheduler.py` → `ai/generator.py`
4-stage pipeline (Claude strategist → Gemini writer → regex guardrails →
Claude validator) + `photo_finder` → `image_gen` overlay → `facebook/publisher.py`.
Same process also runs `web/app.py` (FastAPI) via `src/main.py asyncio.gather`.

**Import rule:** `telegram_bot/*` → `ai/*` → `db.py` + `guardrails.py` + `brand.py`.
Never reach upward — deferred imports inside functions break cycles.

## Web (`src/web/`)
Public brand site reads same SQLite (read-only — bot owns writes). 6 public
routes (`/`, `/products`, `/products/{code}`, `/posts`, `/posts/{id}`, `/contact`)
+ admin upload UI.

- **i18n:** `src/web/i18n/{ka,en,tr}.py` — 93 keys, strict parity. `render()`
  picks lang from `?lang=` → cookie → default `ka`; add a key to all three or
  the renderer raises.
- **Dark mode:** class-based (`class="dark"` on `<html>`, pre-paint to prevent
  flash), OS default + manual toggle via `theme=` cookie.
- **Motion layer (`_motion.html`):** IntersectionObserver + CSS keyframes drive
  `[data-reveal]`, ambient grid/glow, `[data-counter]` rolls. Honors
  `prefers-reduced-motion`.
- **Admin photo upload (`/admin/photos`):** `src/web/auth.py` HTTP Basic +
  `ADMIN_USERNAME`/`ADMIN_PASSWORD`, OR magic-link via Telegram `/upload`
  (30-min TTL). Uploads → `data/photos/{code}.jpg`; bot's `resolve_image_path()`
  picks them up on next post.
- **Admin security:** `_check_csrf()` enforces Origin/Referer against
  `PUBLIC_BASE_URL`; `_photo_path()` blocks `{code}` traversal;
  `Image.MAX_IMAGE_PIXELS = 40_000_000` blocks decompression-bomb DoS; uploads
  saved with `exif=b""`.
- **Phone/WhatsApp** via `{{ brand.CONTACT_PHONE_TEL }}` / `{{ brand.CONTACT_WHATSAPP_URL }}`,
  never inline literals. **Tailwind via CDN, pinned `3.4.16`** in `base.html`.

## Database (10 tables, `src/db.py`, Postgres-portable)
`products` (478, `code_sort` natural order) · `post_drafts` (pending/approved/
edited/rejected/published) · `posts` (1:1 FB) · `post_metrics` + `page_metrics`
(Phase 7, unwired) · `api_spend` · `settings` · `memories` (founder corrections
into every prompt) · `conversation_messages` (last 20 → Gemini multi-turn) ·
`sales`. No Alembic — edit model + drop `data/uygun.db` for dev schema changes.

## Brand voice — non-negotiable
Encoded in `src/ai/prompts.py` + `src/ai/conversation.py`:

- **"თქვენ" form in FB posts** (Phase 18, 2026-06 — reversed Phase 13's "შენ"
  per founder request). `guardrails.check_address_form()` flags informal "შენ"
  markers (`brand.SHEN_MARKERS`: შენ, შენი, შემოგვიარე, მოგვწერე, დაგვირეკე,
  გვითხარი, გაქვს, გჭირდება, …) via `\b`-anchored regex (so formal
  `შემოგვიარეთ` doesn't false-match its informal prefix). Required formal:
  გთავაზობთ, გიდასტურებთ, შემოგვიერთდით, შემოგვიარეთ, მოგვწერეთ, დაგვირეკეთ,
  გვითხარით. The Telegram **chat persona** (peer-to-founder) stays "შენ" —
  only customer-facing FB content flipped. Banned phrases (ფანტასტიკური
  შემოთავაზება, შესანიშნავი შესაძლებლობა, …) live in `brand.BANNED_PHRASES`.
- **"საბურავი" not "სალტე"** (brandbook p.11). Real numbers only:
  `+995 568 90 90 87` · `ბათუმი, მამია ვარშანიძის 189`; guardrail flags `[placeholder]`.
- **Code (#N) never in post body** — internal only.
- **Minimal 5-line format** (Phase 17, 2026-06): `[name]` / `[N] ლარი` /
  `[1 short descriptive sentence]` / `📞 phone` / `📍 address`. No emoji bullets,
  benefits list, WhatsApp line, CTA arrow, or question-hooks ("ცემენტი
  დაგიმთავრდათ?" — ❌). Middle line varies descriptive/functional/stock.
  2-3 hashtags (was 3-5).
- **Daily-only slot** (Phase 18, 2026-06): weekday rotation (`WEEKLY_CALENDAR`)
  removed. Scheduler + `/generate` (no-arg) → `brand.DEFAULT_SLOT = "Daily"` →
  top-seller from last 30 days (`db.list_top_selling_codes`), falls back to
  in-stock + priced if sales history thin. Legacy B2B/B2C/EDU/BTS/LITE/Promo
  survive as `/generate <slot>` manual overrides.
- **Turkish → Georgian product names** (Phase 17.1): writer prompt glossary
  (CIVI=ლურსმანი, YAMA=ფირფიტა, RADYAL=რადიალური, TABAKA=ფურცელი, OZEL=სპეციალური,
  MAVI/YESIL/KIRMIZI=ფერები, SOLUSYON=ხსნარი). Brand codes (VALCARN/MLX/MR/MU/BP/
  BARS/DIVORTEX/AERO) + units (CC/ML/GR/L/KG) verbatim. See `POST_WRITER_SYSTEM`.

**Georgian gotchas:** ❌ `საბურავი გაიბერა` → ✅ `გაიჭრა`/`ლურსმანი ჩავარდა` ·
❌ `გათავდა მარაგი` → ✅ `მარაგი დაგიმთავრდათ` · ❌ `6 ლარის ღირებულების` → ✅ `6 ლარი`.

## Memories (founder's training signal)
`db.list_memories()` injects every row into every Claude/Gemini system prompt.
Founder edits via `/remember <correction>` → sticks forever. **When in doubt:
add a memory, don't rewrite the prompt** — prompts get swept, memories survive.

## Running it
```bash
source .venv/bin/activate
python -m src.main                                       # bot + web (prod)
python -m src.telegram_bot.bot                           # bot only
python -m uvicorn src.web.app:app --reload --port 8000  # web only
python -m pytest tests/ -q
python -m src.ai.generator --slot=Daily --dry-run        # smoke test
```

## Budget circuit breaker
`src/budget.py` tracks every Claude/Gemini call via `api_spend`. Per-month state
so alerts don't spam: **80%** → Telegram warning, keeps working. **100%** →
alert + `agent_active=false`, raises `BudgetExhausted` until `/set_budget X` or
`/set_active true`. Disable: `MONTHLY_BUDGET_USD=99999`.

## Files you'll touch most often
1. `src/ai/prompts.py` — `TOPIC_STRATEGIST_SYSTEM`, `POST_WRITER_SYSTEM`, `POST_VALIDATOR_SYSTEM`
2. `src/ai/conversation.py` — chat-mode persona (peer-to-founder, "შენ")
3. `src/brand.py` — contact, slots, banned phrases, hashtags, social URLs
4. `src/telegram_bot/messages.py` — Georgian founder-facing strings ("შენ")
5. `src/guardrails.py` — validators + 32 unit tests
6. `src/web/templates/*` — public site (Jinja2 + Tailwind CDN, "თქვენ")
7. `src/web/i18n/{ka,en,tr}.py` — 93 keys × 3 langs
8. `src/web/routes/admin.py` + `src/web/auth.py` — photo upload UI

## Things to never do
- **Never `git push --force` to main.** **Never commit `.env`** (gitignored).
- **Never log access tokens** — `logging_setup.py` redacts Telegram/Anthropic/Google/Meta.
- **Never bypass guardrails for "just this one post"** — add a memory or update `brand.BANNED_PHRASES`.
- **Never silently swallow exceptions** — `log.exception` or re-raise.
- **Never let FB posts use "შენ"** (Phase 18 formal "თქვენ"). The Telegram chat
  persona in `conversation.py` is the only "შენ" speaker — don't unify either way.
- **Never weaken `_check_csrf()` or `_photo_path()` in `routes/admin.py`** —
  Basic Auth doesn't cover CSRF; cross-origin POST + path traversal are the
  two real attack surfaces.
- **Never inline phone/WhatsApp URLs in templates** — use `brand.CONTACT_PHONE_TEL` / `brand.CONTACT_WHATSAPP_URL`.
- **Never add an i18n key to one language file only** — ka/en/tr must stay 93/93/93.
