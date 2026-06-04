# Uygun Georgia · Facebook AI Agent

A Telegram-controlled AI agent that runs the Uygun Georgia Facebook Page:
generates one Georgian-language post per day, sends it to the founder
for approval, and publishes it to Facebook after a tap. Plus an in-chat
SMM-manager mode, daily advisor tips, a bookkeeping module, and
auto-found product photos with brand overlay.

**Stack:** Python 3.11 · aiogram 3 · APScheduler · Claude + Gemini · SQLite · Meta Graph API.

---

## What it does

| Feature | Trigger | Notes |
|---|---|---|
| Daily auto-generate | Scheduler at `post_gen_time` (default 11:30 Asia/Tbilisi) | Same as typing `/generate` |
| Manual generate | `/generate` or `/generate B2B` | Picks topic + product per calendar slot |
| Preview + approval | `/generate` produces a card with ✅/✏️/❌ buttons | ✅ publishes if `DRY_RUN=false` |
| Edit feedback | Tap ✏️ → type "make it shorter" → bot regenerates | Free-text feedback injected into the writer |
| Chat with SMM manager | Just type anything | Powered by Gemini 2.5 Flash |
| Daily tips | `/tips` or menu | Cached for the day (≈$0.02 / regenerate) |
| Memory | `/remember <text>`, `/memories`, `/forget <id>` | Injected into every Claude/Gemini call |
| Sales bookkeeping | `/sale CODE QTY PRICE` or menu → FSM | Edit + delete via tap |
| Product photo | Auto-search (DuckDuckGo) + marketing overlay | Three tiers: real photo → web-found → text-card |
| Budget cap | Auto-tracked; alerts at 80%, auto-pauses at 100% | `/spend` shows month-to-date |
| Daily DB backup | Scheduler at 03:30 local | 14-day retention, `data/backups/` |

---

## Quickstart (local dev)

```bash
# 1. Install Python 3.11 (e.g. brew install python@3.11)
brew install python@3.11

# 2. Create venv + install deps
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Fill in .env (copy from .env.example first if missing)
cp .env.example .env
# … edit .env with your TELEGRAM_BOT_TOKEN, ANTHROPIC_API_KEY, etc.

# 4. Import the catalog
python -m src.catalog.importer

# 5. Run the bot
python -m src.telegram_bot.bot
```

Then open Telegram, search for your bot, send `/start`.

---

## Required environment variables

See [.env.example](.env.example) — they fall into four groups:

| Group | Keys | Where to get them |
|---|---|---|
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_CHAT_ID` | @BotFather + @userinfobot |
| Anthropic (Claude) | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | console.anthropic.com |
| Google (Gemini) | `GOOGLE_API_KEY`, `GEMINI_TEXT_MODEL` | aistudio.google.com |
| Meta (Facebook) | `META_APP_ID`, `META_APP_SECRET`, `FB_PAGE_ID`, `FB_PAGE_ACCESS_TOKEN` | developers.facebook.com (see §"Meta App setup" below) |
| Admin UI | `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `PUBLIC_BASE_URL` | pick a username + strong password; `PUBLIC_BASE_URL` is `http://localhost:8000` locally / your Railway URL in prod |

Plus runtime knobs: `DRY_RUN` (default `true` for safety), `TIMEZONE` (default `Asia/Tbilisi`), `MONTHLY_BUDGET_USD` (default `20`), `DATABASE_URL`, `LOG_LEVEL`.

---

## Project layout

```
src/
├── ai/
│   ├── advisor.py          # Daily tips (Claude)
│   ├── claude_client.py    # Claude SDK wrapper + budget guard
│   ├── conversation.py     # SMM-manager chat engine (Gemini)
│   ├── gemini_client.py    # Gemini SDK wrapper + budget guard
│   ├── generator.py        # 4-stage post pipeline
│   ├── image_gen.py        # PIL text card + marketing overlay
│   ├── photo_finder.py     # DuckDuckGo image search
│   └── prompts.py          # System prompts (strategist + writer + validator)
├── catalog/
│   └── importer.py         # products.xlsx → SQLite
├── facebook/
│   └── publisher.py        # Meta Graph API publisher
├── telegram_bot/
│   ├── admin.py            # All command handlers (40+)
│   ├── approval.py         # ✅/✏️/❌ post-approval flow + FSM
│   ├── bot.py              # Entrypoint, aiogram dispatcher
│   ├── chat.py             # Catch-all chat handler
│   └── messages.py         # Georgian message templates
├── brand.py                # Brand constants (mission, calendar, contact, palette)
├── budget.py               # Monthly cap + threshold alerts
├── config.py               # Env var loader
├── db.py                   # SQLAlchemy 2.x models + helpers (10 tables)
├── guardrails.py           # Post validators (10 checks)
├── logging_setup.py        # Structlog + secret redaction
└── scheduler.py            # APScheduler (generation + budget + backup)

assets/fonts/
├── NotoSans.ttf            # Latin
└── NotoSansGeorgian.ttf    # Georgian + Latin + digits + ₾

data/                       # gitignored runtime state
├── uygun.db                # SQLite (WAL mode)
├── backups/                # Daily snapshots, 14-day retention
├── photos/                 # Founder-uploaded product photos
├── found_photos/           # Web-search downloaded photos
├── overlaid_photos/        # Above + brand overlay
└── brand_assets/
    └── logo.png            # Used by image_gen.py marketing overlay

tests/
└── test_guardrails.py      # 31 unit tests for validators
```

---

## Telegram commands cheatsheet

```
/start            Show welcome + main menu
/menu             Re-show main menu
/help             Full command list

/generate [SLOT]  Trigger a post draft (SLOT optional: B2B/B2C/EDU/BTS/LITE/Promo)
/tips             Daily advisor tips (cached per day)
/dashboard        Stats + visual progress bars
/products         Paginated catalog
/inventory        Out-of-stock list with quick-toggle
/search QUERY     Search products (Georgian↔Latin synonyms supported)
/categories       Drill-down by category
/settings         View runtime settings
/spend            API budget month-to-date

/remember TEXT    Save a preference
/memories         List saved memories
/forget ID        Delete one
/forget_chat      Wipe conversation history

/sale CODE QTY PRICE   Record a sale (one-liner)
/sales            Recent sales, tappable
/sales_summary    Today + month totals + top products
/undo_sale ID     Delete a sale

/set_active true|false       Pause/resume agent
/set_gen_time HH:MM          Reschedule daily generation
/set_publish_time HH:MM
/set_budget USD              Change monthly cap
/toggle_stock CODE           Flip product in/out of stock

/refind_photo CODE           Clear cached photo + re-search
/cleanup_drafts              Delete pending/edited/rejected drafts
/reimport                    Re-run products.xlsx import
/test_fb                     Verify Meta token
/test_schedule               Manual fire of the daily job
/scheduler                   Show next run time

/upload                      Issue 30-min magic link to /admin/photos
```

---

## Public website

Runs on the same process as the bot (port 8000 locally, your Railway URL in prod). Routes:

| URL | Description |
|---|---|
| `/` | Homepage — hero, value pillars, featured products, latest FB posts |
| `/products` | Catalog with category + search + pagination |
| `/products/{code}` | Product detail (photo or typographic panel + price + CTA) |
| `/posts` | Published Facebook posts feed |
| `/posts/{id}` | Single post with full body + FB permalink |
| `/contact` | Phone, WhatsApp, address, Facebook, Instagram, hours, map |
| `/healthz` | Health check (returns `{"ok":true}`) |
| `/admin/photos` | **Protected** — per-product photo upload (Basic Auth + Telegram magic link) |

**Languages:** Georgian (default), English, Turkish. Switch via flag icons in the nav. Stored in a 1-year cookie.

**Dark mode:** Follows OS preference by default; toggle the sun/moon icon to override. Sticky via cookie.

**Motion:** Scroll-triggered reveals + ambient drift + slow background pulses, fully disabled if the visitor has `prefers-reduced-motion: reduce`.

### Admin photo upload (`/admin/photos`)

The site is public, but `/admin/photos` requires auth. Two ways in:

1. **Browser Basic Auth** — browser pops a username/password prompt the first time, keychain remembers it. Set `ADMIN_USERNAME` + `ADMIN_PASSWORD` in `.env`.
2. **Telegram magic link** — send `/upload` to the bot. It replies with a link valid for 30 minutes; tap it to bypass the password prompt.

What it does:
- Lists all 478 products with filter pills (missing / uploaded / all) and search by code or name.
- One file input per row. The selected photo is normalized to JPG (max 1600px, quality 85, EXIF stripped) and saved to `data/photos/{code}.jpg`.
- The bot's image pipeline (`src/ai/generator.py:resolve_image_path`) automatically prefers founder-uploaded photos over web-scraped fallbacks — no code change needed to wire bot integration.

Security: path-traversal blocked (DB lookup + resolved-path check), CSRF blocked (Origin/Referer must match `PUBLIC_BASE_URL`), decompression-bomb blocked (Pillow `MAX_IMAGE_PIXELS=40M`), constant-time password comparison.

---

## Meta App setup (one-time, ~30-60 min)

See `/Users/achilles/.claude/plans/project-uygun-georgia-compressed-clover.md` §8.4 for the full click-by-click. Summary:

1. https://developers.facebook.com → Create App (type: Business)
2. App Settings → Basic → copy App ID + App Secret
3. Get Page ID from your FB Page's About section
4. Graph API Explorer → select your app → select your Page → add scopes
   `pages_show_list`, `pages_manage_posts`, `pages_read_engagement` →
   Generate Access Token (short-lived)
5. Exchange short → long → never-expiring page token via two curl calls
6. Paste all 4 values in `.env`, restart bot, run `/test_fb` to verify

---

## Daily flow (what actually happens)

```
11:30  Scheduler fires → generator picks product per calendar slot
       → Gemini writes Georgian post, Claude validates
       → photo: real photo OR web-found+overlay OR PIL text card
       → preview message sent to founder's Telegram with ✅/✏️/❌

11:30-23:59  Founder taps ✅
       → approval handler marks draft as approved
       → if DRY_RUN=false: publisher hits Meta Graph API
       → post appears on Uygun Georgia FB page
       → fb_post_id saved to `posts` table

03:30  Daily DB backup → data/backups/uygun-YYYY-MM-DD.db
       (retention: 14 most recent)

every 30 min  Budget check
       → 80%: Telegram warning
       → 100%: auto-pause + Telegram block alert
```

---

## Costs

Realistic monthly spend (50 chat messages + 30 daily posts + tips):

| Provider | Operation | Cost/month |
|---|---|---|
| Claude Sonnet 4.6 | Topic strategist + validator + advisor tips | ~$1.50 |
| Gemini 2.5 Flash | Post writer + chat | ~$0.30 |
| Meta Graph API | Free | $0 |
| Railway hosting | Hobby plan | $5 |
| **Total** | | **~$7/month** |

Hard ceiling: `MONTHLY_BUDGET_USD` (default $20). 80%/100% alerts auto-fire.

---

## Deploying to Railway (production)

Single Railway service runs both the Telegram bot AND the brand website in one
process (`src/main.py` → `asyncio.gather(run_bot(), run_web())`). Hobby plan ($5/mo) is enough.

### 1. Push to GitHub

```bash
git push origin main
```

Private repo is fine; `.env` is gitignored so no secrets leak.

### 2. Create Railway project

1. https://railway.app → log in with GitHub.
2. **New Project** → **Deploy from GitHub repo** → select this repo.
3. Railway auto-detects `Procfile` (`worker: python -m src.main`) and `runtime.txt` (Python 3.11.10).

### 3. Paste environment variables

**Variables** tab → paste every key from `.env.example`:

- Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_CHAT_ID`
- Anthropic: `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`
- Google: `GOOGLE_API_KEY`, `GEMINI_TEXT_MODEL`, `GEMINI_IMAGE_MODEL`
- Meta: `META_APP_ID`, `META_APP_SECRET`, `FB_PAGE_ID`, `FB_PAGE_ACCESS_TOKEN`
- Admin UI: `ADMIN_USERNAME`, `ADMIN_PASSWORD` (pick a strong one), `PUBLIC_BASE_URL=https://<your-railway-domain>` (also used by `/upload` to build the Telegram magic-link)
- Runtime: `DRY_RUN=false`, `TIMEZONE=Asia/Tbilisi`, `MONTHLY_BUDGET_USD=20`, `LOG_LEVEL=INFO`
- DB: `DATABASE_URL=sqlite:////data/uygun.db` (absolute path inside the volume)

Railway injects `PORT` automatically — the web app already binds to it.

### 4. Mount a volume for SQLite

**Settings → Volumes → New Volume**:
- Mount path: `/data`
- The DB lives at `/data/uygun.db`, backups at `/data/backups/`, photos at `/data/photos/` and `/data/found_photos/`. All survive deploys.

### 5. Healthcheck

**Settings → Healthcheck**:
- Path: `/healthz`
- Timeout: 30s

Railway auto-restarts the service if the endpoint stops responding.

### 6. Generate public domain

**Settings → Networking → Generate Domain** → copy the `*.up.railway.app` URL.
Visit it to confirm the brand site loads.

### 7. Custom domain (uygungeorgia.com)

1. Railway → **Settings → Custom Domain** → add `uygungeorgia.com` AND `www.uygungeorgia.com`.
2. Railway shows you a CNAME target like `production.up.railway.app`.
3. At your registrar's DNS panel:
   - For root `uygungeorgia.com`: add an `ALIAS` or `ANAME` record pointing to the Railway target (or use the registrar's "redirect to www" if ALIAS isn't supported).
   - For `www.uygungeorgia.com`: add a `CNAME` record pointing to the Railway target.
4. Wait 5–60 min for DNS propagation; Railway auto-provisions Let's Encrypt HTTPS.
5. Visit `https://uygungeorgia.com` → green padlock.

### 8. Verify

```bash
# bot replies
# (open Telegram → /start)

# site loads
curl -sS -o /dev/null -w "%{http_code}\n" https://uygungeorgia.com/
curl -sS https://uygungeorgia.com/healthz   # → {"ok":true}
```

### Operational notes

- **Logs:** Railway dashboard → Deployments → Logs (tail in real time).
- **Restart:** Railway auto-restarts on push to `main` or on healthcheck failure.
- **Rollback:** Deployments tab → previous green deploy → "Redeploy".
- **DB access:** `railway run sqlite3 /data/uygun.db` (read-only inspection).
- **First post:** `/test_fb` from Telegram to verify Meta token works before relying on the scheduler.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Bot says nothing | Wrong bot OR wrong `TELEGRAM_ADMIN_CHAT_ID` | Check `@userinfobot` for your actual ID |
| `/generate` fails | Claude/Gemini key invalid OR budget hit | Check `/spend`; run `/test_fb` first |
| Posts don't publish | `DRY_RUN=true` still set | Edit `.env`, restart bot |
| `❌ Facebook ტოკენი ვერ მუშაობს` | Page token expired or wrong scopes | Regenerate via Graph API Explorer + exchange |
| Wrong photo chosen | Search picked unrelated product | `/refind_photo CODE` to clear cache + retry |
| Stale drafts piling up | Old `pending` rows in DB | `/cleanup_drafts` |
| Bot stops at night | Laptop sleeping | Deploy to Railway (see above) |

---

## License + credits

Internal project for Uygun Georgia. Built with Anthropic Claude + Google Gemini.
Brand voice and content rules follow the canonical `Uygun_Georgia_Brandbook_v3_0.pdf`.
