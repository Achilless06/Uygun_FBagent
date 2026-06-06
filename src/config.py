"""Centralized configuration: reads env vars and exposes a typed Config object.

There are two layers of config:

1. Static config (this file) — values that change only on deploy: API keys,
   model IDs, the admin chat ID. Loaded from environment (Railway dashboard
   in prod, .env file locally).

2. Runtime settings (db.py `settings` table) — values the founder edits via
   Telegram while the bot is running: posting time, agent paused/active,
   budget cap. Read at the moment they're needed, not cached here.

Anything from env that has a sensible default lives in DEFAULTS below.
Anything that is a secret has no default and raises on access if missing —
fail loudly at startup beats silent misbehavior in production.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root if present (no-op in Railway where vars come from the dashboard).
load_dotenv()

# Project root: this file lives at <root>/src/config.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PHOTOS_DIR = DATA_DIR / "photos"
BRAND_ASSETS_DIR = DATA_DIR / "brand_assets"


def _required(name: str) -> str:
    """Read a required env var; raise a clear error if missing."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Set it in your .env file (local) or Railway dashboard (prod). "
            f"See .env.example for the full list."
        )
    return value


def _optional(name: str, default: str) -> str:
    return os.getenv(name) or default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Config:
    # Telegram
    telegram_bot_token: str
    telegram_admin_chat_id: int

    # Anthropic
    anthropic_api_key: str
    anthropic_model: str

    # Google Gemini
    google_api_key: str
    gemini_text_model: str
    gemini_image_model: str

    # Meta / Facebook
    meta_app_id: str
    meta_app_secret: str
    fb_page_id: str
    fb_page_access_token: str

    # Admin upload UI (photos page)
    admin_username: str
    admin_password: str
    public_base_url: str

    # Airtable (Monthly Top Sellers — /import_sales handler)
    airtable_token: str
    airtable_base_id: str
    airtable_monthly_table_id: str

    # Runtime
    dry_run: bool
    timezone: str
    monthly_budget_usd: float
    database_url: str
    log_level: str


_cached: Config | None = None


def load() -> Config:
    """Load and return the runtime config. Cached after the first call so
    repeated load() calls inside hot paths (e.g. per-request auth) don't
    re-parse the .env file.

    Truly required vars (Telegram + Anthropic + Google) raise immediately on
    startup. Meta/Facebook vars are only validated when the publisher actually
    tries to post — this lets you run the bot for Phases 2-4 without yet
    having gone through the Meta App Review setup.
    """
    global _cached
    if _cached is not None:
        return _cached
    _cached = Config(
        telegram_bot_token=_required("TELEGRAM_BOT_TOKEN"),
        telegram_admin_chat_id=int(_required("TELEGRAM_ADMIN_CHAT_ID")),
        anthropic_api_key=_required("ANTHROPIC_API_KEY"),
        anthropic_model=_optional("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        google_api_key=_required("GOOGLE_API_KEY"),
        gemini_text_model=_optional("GEMINI_TEXT_MODEL", "gemini-3.5-flash"),
        gemini_image_model=_optional("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image-preview"),
        # Meta vars: optional at load time; src/facebook/publisher.py validates
        # them when DRY_RUN=false and a publish is attempted.
        meta_app_id=_optional("META_APP_ID", ""),
        meta_app_secret=_optional("META_APP_SECRET", ""),
        fb_page_id=_optional("FB_PAGE_ID", ""),
        fb_page_access_token=_optional("FB_PAGE_ACCESS_TOKEN", ""),
        # Admin upload UI: username + password protect /admin/photos. Defaults
        # are intentionally weak to fail an obvious smoke-test if you forget to
        # set them in .env — change ADMIN_PASSWORD before exposing publicly.
        admin_username=_optional("ADMIN_USERNAME", "admin"),
        admin_password=_optional("ADMIN_PASSWORD", "change-me"),
        public_base_url=_optional("PUBLIC_BASE_URL", "http://localhost:8000"),
        # Airtable PAT — empty until founder generates one. /import_sales
        # raises a clear setup-instruction error when missing.
        airtable_token=_optional("AIRTABLE_TOKEN", ""),
        airtable_base_id=_optional("AIRTABLE_BASE_ID", "appWU0o0Xxz44L6Xo"),
        airtable_monthly_table_id=_optional(
            "AIRTABLE_MONTHLY_TABLE_ID", "tblptYd9f06LUdRMp"
        ),
        dry_run=_bool("DRY_RUN", True),
        timezone=_optional("TIMEZONE", "Asia/Tbilisi"),
        monthly_budget_usd=float(_optional("MONTHLY_BUDGET_USD", "20")),
        database_url=_optional("DATABASE_URL", f"sqlite:///{DATA_DIR}/uygun.db"),
        log_level=_optional("LOG_LEVEL", "INFO"),
    )
    return _cached
