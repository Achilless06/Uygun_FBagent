# CLAUDE.md — context for future Claude Code sessions

This file is loaded automatically when you open a new Claude Code session in
this project directory. It captures things that aren't obvious from the code
but matter for getting work done quickly.

If you're a human reading this: the README is for you. This file is the
AI-assistant briefing. Both stay in sync — when an architectural detail
changes, update both.

---

## What this project is

Uygun Georgia (a vulcanization / car-wash chemical supplier in Batumi)
runs its Facebook Page through this Telegram-controlled AI agent.

**Founder profile:** non-technical solo founder (Achi). Speaks Georgian
primarily. Writes commit-style instructions in chat. Wants short replies
with concrete actions, not long explanations. Values brand voice
consistency above feature breadth.

**Scope discipline:** the brandbook (`Uygun_Georgia_Brandbook_v3_0.pdf`)
is the canonical source for brand identity. Every behavioral decision
traces back to a brandbook page. When the founder gives feedback that
contradicts the brandbook, the founder wins — but ask why before changing.

---

## Two hard rules — never break

1. **Human-in-the-loop for publishing.** Every post that goes to Facebook
   is approved manually by the founder tapping ✅ in Telegram. No
   autopublish-on-timer, no fallback that skips approval. The agent
   generates, the founder decides.

2. **No invented data.** Prices and stock come from `products.xlsx` (via
   the `products` table). If the data isn't there, the post doesn't
   mention it. `src/guardrails.py` enforces this — never weaken it.

---

## Tech stack — exact versions matter

- Python **3.11** (not 3.12+; Railway runtime pinned in `runtime.txt`)
- aiogram **3.13** (uses the new dispatcher/router/FSM API; very different from v2)
- APScheduler **3.10** (AsyncIO scheduler runs in the bot's event loop)
- google-genai **2.4** (≥1.0 required for `ThinkingConfig` — older versions don't have it)
- anthropic **0.40**
- SQLAlchemy **2.x** (with type-annotated `Mapped[...]` syntax)
- Pillow **10.4** (image overlays)
- ddgs **9.x** (DuckDuckGo image search — the package was renamed from `duckduckgo-search`)

Bundled fonts in `assets/fonts/` — `NotoSansGeorgian.ttf` handles Georgian,
Latin, digits, AND the ₾ symbol all at once. Don't switch to system fonts
(SFGeorgian.ttf misses digits and produces ≡≡≡ placeholders).

Gemini 3.5 Flash quirk: **always set `thinking_budget=0`** in `gemini_client.py`.
Otherwise the model spends its `max_output_tokens` on hidden chain-of-thought
and the JSON output gets truncated. This is the most subtle gotcha in the codebase.
(Same gotcha applies to 2.5 Flash — the `thinking_config` API is the standard
way Google exposes this control across 2.5/3.0/3.5/3.1 generations.)

---

## Architecture in one diagram

```
                      ┌─────────────────────┐
                      │  Telegram bot       │
   founder DMs   ─────│  (aiogram polling)  │  ←──  scheduler.py fires
                      └──────────┬──────────┘       daily generation
                                 │
              ┌──────────────────┼─────────────────────┐
              ▼                  ▼                     ▼
      ┌──────────────┐  ┌────────────────┐   ┌──────────────────┐
      │ admin.py     │  │ approval.py    │   │ chat.py          │
      │ (commands)   │  │ (✅/✏️/❌ FSM) │   │ (catch-all text)│
      └──────┬───────┘  └────────┬───────┘   └──────────┬───────┘
             │                   │                       │
             └───────────┬───────┴───────────────────────┘
                         ▼
                ┌────────────────────────┐
                │  src/ai/generator.py   │  ← 4-stage pipeline:
                │  src/ai/conversation.py│    1. Claude strategist (pick topic)
                │  src/ai/advisor.py     │    2. Gemini writer (Georgian text)
                └─────┬────────────────┬─┘    3. Regex guardrails
                      │                │      4. Claude validator (tone)
                      ▼                ▼      +photo_finder → image_gen overlay
                Anthropic API     Google API
                  (Claude)          (Gemini)            │
                                                        ▼
                                                ┌──────────────────┐
                                                │ src/facebook/    │
                                                │ publisher.py     │
                                                │ (Meta Graph API) │
                                                └──────────────────┘
                         ▲
                         │
              src/db.py (SQLite, WAL mode, 10 tables)
```

**Imports flow:** `telegram_bot/*` → `ai/*` → `db.py` + `guardrails.py` + `brand.py`.
Never reach upward (e.g. `ai/*` must not import `telegram_bot/*` at module level —
use deferred imports inside functions to break cycles, like `scheduler.py` does).

---

## Database schema (10 tables)

All in `src/db.py`. Schema is Postgres-portable.

| Table | Purpose |
|---|---|
| `products` | Catalog (478 rows from xlsx). `code_sort` enables natural-order sort. |
| `post_drafts` | Generated posts pre-approval. `status` enum: pending/approved/edited/rejected/published. |
| `posts` | Published posts (1:1 with FB). Has `fb_post_id` + permalink. |
| `post_metrics` | Daily Insights snapshot per post (Phase 7, not wired yet). |
| `page_metrics` | Daily follower count (Phase 7). |
| `api_spend` | Every Claude/Gemini call. Used by `budget.py` circuit breaker. |
| `settings` | Runtime config: `agent_active`, `post_gen_time`, `monthly_budget_usd`, `tips:YYYY-MM-DD` (cache). |
| `memories` | Long-term founder preferences. Categories: `preference`/`style`/`language`/`dislike`/`fact`. |
| `conversation_messages` | Chat history (last 20 injected into Gemini's multi-turn). |
| `sales` | Manual bookkeeping. |

Adding a column: edit the model in `db.py`, drop `data/uygun.db` in dev (or
ALTER TABLE in prod), restart bot. There's no Alembic yet — would be the
right add when Postgres migration happens.

---

## Brand voice — non-negotiable rules

From the brandbook §4 (encoded in `src/ai/prompts.py` + `src/ai/conversation.py`):

- **"შენ" form always.** Never "თქვენ". The regex guardrail catches common
  formal verbs (გთავაზობთ, გიდასტურებთ, შემოგვიერთდით).
- **No banned phrases:** "მაღალი ხარისხის", "ფანტასტიკური შემოთავაზება",
  "სანდო მიმწოდებელი", "შესანიშნავი შესაძლებლობა". Full list in `brand.BANNED_PHRASES`.
- **"საბურავი" not "სალტე"** — explicitly forbidden. See brandbook p.11.
- **Real numbers only.** Phone: `+995 568 90 90 87`. Address: `ბათუმი, მამია ვარშანიძის 189`.
  No `[placeholder]` text — guardrail flags `[...]` regex.
- **Code (#N) never in post body** — internal only, founder sees in admin preview.
- **Wish Motors-style format** is the default post layout (emoji-bullet vertical
  structure). See `POST_WRITER_SYSTEM` in `src/ai/prompts.py` for the concrete
  example.

Common Georgian language gotchas the bot has historically tripped on (now
covered in prompts):

- ❌ `საბურავი გაიბერა` = "tire inflated" (semantically wrong direction).
  ✅ Use `დაგიფეთქდა` / `ლურსმანი ჩავარდა` / `დასკდა`.
- ❌ `გათავდა მარაგი` → ✅ `მარაგი დაგიმთავრდა`.
- ❌ `6 ლარის ღირებულების` → ✅ `6 ლარი` or `6 ლარად`.

---

## How memories work (and why they matter)

`src/db.py:list_memories()` is called inside both the chat engine and the
post generator. Every memory row is injected into the system prompt of every
Claude/Gemini call. This is the founder's training signal — when the bot
makes a mistake, the founder corrects it once with `/remember <correction>`
and the correction sticks forever.

When in doubt: add a memory rather than rewriting a prompt. Prompts can be
swept; memories survive.

Existing seed memories (as of last audit):

1. style: Wish Motors emoji-bullet format is default.
2. style: Product code (#N) never in post body.
3. language: vulcanization vocabulary (`გაიბერა` is wrong, etc.).
4. language: cement/price vocabulary corrections.

---

## Running it

```bash
# venv
source .venv/bin/activate

# bot (foreground; Ctrl+C stops both bot + scheduler)
python -m src.telegram_bot.bot

# tests
python -m pytest tests/ -q

# lint
python -m ruff check src/ tests/

# CLI smoke-test the generator (doesn't touch Telegram)
python -m src.ai.generator --slot=B2B --dry-run
```

**Bot doesn't have a daemon mode locally** — for 24/7 use, deploy to Railway
per the README. The bot polls (long-polling), so it works behind NAT without
webhooks.

---

## Costs + budget circuit breaker

`src/budget.py` tracks every Claude/Gemini call via `api_spend` table.
Two thresholds, both stateful per-month so alerts don't spam:

- **80%**: Telegram warning. Agent keeps working.
- **100%**: Telegram alert + sets `agent_active=false` (auto-pause).
  All `claude_client.generate*` and `gemini_client.generate*` calls raise
  `BudgetExhausted` until founder runs `/set_budget X` (raise cap) or
  `/set_active true` (override).

If the user wants to disable: set `MONTHLY_BUDGET_USD=99999` in `.env`.

---

## Files you'll touch most often

1. **`src/ai/prompts.py`** — when brand voice or post format needs tuning.
   Three system prompts: `TOPIC_STRATEGIST_SYSTEM` (Claude),
   `POST_WRITER_SYSTEM` (Gemini), `POST_VALIDATOR_SYSTEM` (Claude).
2. **`src/ai/conversation.py`** — chat-mode system prompt + persona.
3. **`src/brand.py`** — contact info, calendar, banned phrases, hashtag pools.
4. **`src/telegram_bot/messages.py`** — all Georgian user-facing strings.
5. **`src/guardrails.py`** — validators + their 31 unit tests.

---

## Open work (as of last session)

Done: Phases 1–6 + bonus features (chat, memory, sales, photo pipeline,
budget breaker, DB backups, docs).

Pending: Phase 7 (analytics + weekly report), Phase 9 (Railway deploy).
See README §"Deploying to Railway" for the deploy walkthrough.

---

## Things to never do

- **Never `git push --force` to main.** Force-push history loss is irreversible.
- **Never commit `.env`.** It's gitignored — keep it that way.
- **Never log access tokens.** `logging_setup.py` has a regex-based redactor
  for Telegram/Anthropic/Google/Meta token shapes. Don't bypass it.
- **Never bypass guardrails for "just this one post".** If a real edge case
  forces it, add a memory or update `brand.BANNED_PHRASES` instead.
- **Never silently swallow exceptions.** Either log.exception or re-raise.
  Errors that disappear lead to "the bot doesn't post and we don't know why".
