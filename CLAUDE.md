# CLAUDE.md — briefing for future Claude Code sessions

## What this is

Uygun Georgia (Batumi vulcanization + car-wash chemical supplier) runs its
Facebook Page through a Telegram-controlled AI agent. Same SQLite DB also
backs a public brand website (`src/web/`).

**Founder:** non-technical solo founder (Achi). Speaks Georgian. Wants short
replies, concrete actions. Brandbook (`Uygun_Georgia_Brandbook_v3_0.pdf`) is
canonical — if founder feedback contradicts it, founder wins.

---

## Two hard rules — never break

1. **Human-in-the-loop publishing.** Every FB post requires a manual ✅ tap
   in Telegram. No autopublish, no timeout fallback.
2. **No invented data.** Prices/stock come from `products` table only.
   `src/guardrails.py` enforces this — never weaken it.

---

## Tech stack — exact versions matter

- Python **3.11** (Railway pinned; not 3.12+)
- aiogram **3.13** (new dispatcher/router/FSM API — very different from v2)
- APScheduler **3.10** (AsyncIO, runs in bot's event loop)
- google-genai **2.4** (≥1.0 needed for `ThinkingConfig`)
- anthropic **0.40** · SQLAlchemy **2.x** (`Mapped[...]`) · Pillow **10.4**
- ddgs **9.x** (DuckDuckGo image search — renamed from `duckduckgo-search`)
- FastAPI **0.115** + uvicorn + Jinja2 **3.1** (web)

Bundled fonts in `assets/fonts/` — `NotoSansGeorgian.ttf` handles Georgian +
Latin + digits + ₾ together. Don't switch to system fonts.

**Gemini `thinking_budget=0` gotcha:** always set it in `gemini_client.py`.
Otherwise the model spends `max_output_tokens` on hidden chain-of-thought
and JSON output gets truncated. Most subtle landmine in the codebase.

---

## Architecture

`telegram_bot/*` (aiogram polling) + `scheduler.py` → `ai/generator.py`
4-stage pipeline (Claude strategist → Gemini writer → regex guardrails →
Claude validator) + `photo_finder` → `image_gen` overlay → `facebook/publisher.py`.
Same process also runs `web/app.py` (FastAPI) via `src/main.py` `asyncio.gather`.

**Import rule:** `telegram_bot/*` → `ai/*` → `db.py` + `guardrails.py` + `brand.py`.
Never reach upward — use deferred imports inside functions to break cycles.

---

## Web (`src/web/`)

Public brand site that reads from the same SQLite (read path only — bot
owns writes). Mounted as 6 public routes (`/`, `/products`, `/products/{code}`,
`/posts`, `/posts/{id}`, `/contact`) + admin upload UI.

- **i18n:** `src/web/i18n/{ka,en,tr}.py` — 93 keys each, strict parity. `render()`
  in `src/web/render.py` picks lang from `?lang=` query → cookie → default `ka`.
  Add a key to ALL THREE files at once or the renderer raises.
- **Dark mode:** class-based (`class="dark"` on `<html>`, set pre-paint to
  prevent flash). OS default + manual toggle, persisted via `theme=` cookie.
- **Motion layer:** `_motion.html` partial — IntersectionObserver + CSS
  keyframes drive `[data-reveal]` reveals, ambient grid/glow drift,
  `[data-counter]` number rolls. Honors `prefers-reduced-motion: reduce`.
- **Admin photo upload UI:** `/admin/photos` gated by `src/web/auth.py`
  (HTTP Basic with `ADMIN_USERNAME`/`ADMIN_PASSWORD` env vars, OR magic-link
  token issued by Telegram `/upload` command, 30-min TTL). Uploads land in
  `data/photos/{code}.jpg` and the bot's `resolve_image_path()` picks them
  up automatically on the next post — no bot-side wiring needed.
- **Security (admin routes):** `_check_csrf()` enforces Origin/Referer match
  against `PUBLIC_BASE_URL`; `_photo_path()` blocks path traversal via the
  `{code}` URL param; `Image.MAX_IMAGE_PIXELS = 40_000_000` blocks Pillow
  decompression-bomb DoS; uploads are saved with `exif=b""` to strip GPS/EXIF.
- **Brand voice split:** website renders in **"თქვენ" (formal)**, bot stays in
  **"შენ"** (Phase 13 deliberate decision). Don't unify them.
- **Phone/WhatsApp URLs** live in `brand.CONTACT_PHONE_TEL` and
  `brand.CONTACT_WHATSAPP_URL` — templates render `{{ brand.X }}`, never
  inline literals.
- **Tailwind via CDN, pinned to `3.4.16`** in `base.html`. CDN warns in
  production console; acceptable at current traffic. Don't unpin.

---

## Database (10 tables, all in `src/db.py`, Postgres-portable)

`products` (478 rows, `code_sort` for natural order) · `post_drafts` (status:
pending/approved/edited/rejected/published) · `posts` (1:1 with FB) ·
`post_metrics` + `page_metrics` (Phase 7, unwired) · `api_spend` (budget) ·
`settings` · `memories` (founder corrections injected into every prompt) ·
`conversation_messages` (last 20 → Gemini multi-turn) · `sales`.

No Alembic — for dev schema changes, edit model + drop `data/uygun.db`.

---

## Brand voice — non-negotiable

Encoded in `src/ai/prompts.py` + `src/ai/conversation.py`:

- **"შენ" form always.** Never "თქვენ". Guardrail catches formal verbs
  (გთავაზობთ, გიდასტურებთ, შემოგვიერთდით).
- **Banned phrases:** "მაღალი ხარისხის", "ფანტასტიკური შემოთავაზება",
  "სანდო მიმწოდებელი", "შესანიშნავი შესაძლებლობა". Full list in `brand.BANNED_PHRASES`.
- **"საბურავი" not "სალტე"** (brandbook p.11).
- **Real numbers only.** Phone `+995 568 90 90 87`, address `ბათუმი, მამია ვარშანიძის 189`.
  No `[placeholder]` text — guardrail flags `[...]`.
- **Code (#N) never in post body** — internal only.
- **Minimal 5-line format** (Phase 17, 2026-06): every post is exactly
  `[product name]` / `[price] ლარი` / `[1 short descriptive sentence]` /
  `📞 phone` / `📍 address`. No emoji bullets, no benefits list, no WhatsApp
  line, no CTA arrow, **no question-hooks** ("ცემენტი დაგიმთავრდა?" — ❌).
  Middle line = plain descriptive/functional/stock-availability sentence,
  varied each post. Hashtags reduced to 2-3 (was 3-5).
- **Turkish → Georgian product names** (Phase 17.1): products import from
  Turkish supplier with mixed names ("საბურავის ლატკა MU A0 CIVI DELIGI YAMASI").
  Writer prompt has a glossary (CIVI=ლურსმანი, YAMA=ფირფიტა, RADYAL=რადიალური,
  TABAKA=ფურცელი, OZEL=სპეციალური, MAVI=ლურჯი, YESIL=მწვანე, SOLUSYON=ხსნარი)
  and translates these to Georgian. Brand codes (VALCARN, MLX, MR, MU, BP, BARS,
  DIVORTEX, AERO, BETA) and units (CC/ML/GR/L/KG) are kept verbatim.
  See `POST_WRITER_SYSTEM` in `src/ai/prompts.py`.

**Georgian gotchas covered in prompts:** ❌ `საბურავი გაიბერა` → ✅ `გაიჭრა` /
`ლურსმანი ჩავარდა` · ❌ `გათავდა მარაგი` → ✅ `მარაგი დაგიმთავრდა` ·
❌ `6 ლარის ღირებულების` → ✅ `6 ლარი`.

---

## Memories (founder's training signal)

`db.list_memories()` injects every row into every Claude/Gemini system prompt.
Founder corrects via `/remember <correction>` → sticks forever. **When in
doubt: add a memory, don't rewrite the prompt** — prompts get swept, memories survive.

---

## Running it

```bash
source .venv/bin/activate
python -m src.main                    # bot + web together (production)
python -m src.telegram_bot.bot        # bot only
python -m uvicorn src.web.app:app --reload --port 8000   # web only
python -m pytest tests/ -q
python -m src.ai.generator --slot=B2B --dry-run          # smoke test
```

---

## Budget circuit breaker

`src/budget.py` tracks every Claude/Gemini call via `api_spend`. Per-month
state so alerts don't spam: **80%** → Telegram warning, keeps working.
**100%** → alert + `agent_active=false`, raises `BudgetExhausted` until
`/set_budget X` or `/set_active true`. Disable: `MONTHLY_BUDGET_USD=99999`.

---

## Files you'll touch most often

1. `src/ai/prompts.py` — `TOPIC_STRATEGIST_SYSTEM`, `POST_WRITER_SYSTEM`, `POST_VALIDATOR_SYSTEM`
2. `src/ai/conversation.py` — chat-mode persona
3. `src/brand.py` — contact, calendar, banned phrases, hashtag pools, social URLs
4. `src/telegram_bot/messages.py` — all Georgian user-facing strings (bot, "შენ")
5. `src/guardrails.py` — validators + 31 unit tests
6. `src/web/templates/*` — public website (Jinja2 + Tailwind CDN, "თქვენ")
7. `src/web/i18n/{ka,en,tr}.py` — translatable strings, 93 keys × 3 langs
8. `src/web/routes/admin.py` + `src/web/auth.py` — photo upload UI (auth-gated)

---

## Things to never do

- **Never `git push --force` to main.**
- **Never commit `.env`.** Gitignored — keep it that way.
- **Never log access tokens.** `logging_setup.py` redacts Telegram/Anthropic/Google/Meta shapes.
- **Never bypass guardrails for "just this one post".** Add a memory or update `brand.BANNED_PHRASES`.
- **Never silently swallow exceptions.** Either `log.exception` or re-raise.
- **Never unify bot + website voice.** Bot speaks "შენ", site speaks "თქვენ" — Phase 13 decision.
- **Never weaken `_check_csrf()` or `_photo_path()` in `routes/admin.py`** — Basic Auth alone does not protect against CSRF; cross-origin POST + path traversal are the two real attack surfaces.
- **Never inline phone/WhatsApp URLs in templates** — always `{{ brand.CONTACT_PHONE_TEL }}` / `{{ brand.CONTACT_WHATSAPP_URL }}`.
- **Never add an i18n key to one language file only** — `ka.py` / `en.py` / `tr.py` must stay at 93/93/93 parity (the renderer will raise on missing keys).
