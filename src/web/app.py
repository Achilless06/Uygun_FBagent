"""FastAPI application for the brand landing site.

Mounted onto the same event loop as the Telegram bot via `src/main.py`.
The website only reads from the SQLite — the bot owns all writes.

Static assets:
  - /assets/brand/*  → data/brand_assets/ (logo, hero image if uploaded)
  - /assets/photos/* → data/found_photos/ (web-found product photos)
  - /assets/uploaded/* → data/photos/ (founder-uploaded product photos)
  - /static/*        → src/web/static/ (CSS/JS shipped with the code)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src import config, db
from src.config import DATA_DIR
from src.logging_setup import get_logger

log = get_logger(__name__)

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# `brand` stays a Jinja global for language-invariant constants (phone number).
# Translatable strings (`t`) and lang metadata are injected per request by
# `src/web/render.py` so each visitor sees their chosen language.
from datetime import datetime  # noqa: E402

from src import brand as _brand  # noqa: E402

templates.env.globals["brand"] = _brand


def _int_ts(value) -> int:
    """Cache-bust filter: turn a datetime into a unix int. Used in image URLs
    like `/assets/uploaded/{code}.jpg?v={{ p.updated_at | int_ts }}` so that
    re-uploaded photos override stale browser cache."""
    if isinstance(value, datetime):
        return int(value.timestamp())
    return 0


templates.env.filters["int_ts"] = _int_ts


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Initialize the DB engine if it hasn't already been (standalone uvicorn case).

    When the web app runs alongside the bot via `src/main.py`, init_engine has
    already been called. When run standalone (`uvicorn src.web.app:app`), we
    need to do it ourselves so DB queries work.
    """
    if db._engine is None:
        cfg = config.load()
        db.init_engine(cfg.database_url)
        db.create_all()
        log.info("web_app_initialized_db_standalone")
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Uygun Georgia",
        description="ვულკანიზაცია · ავტოქიმია · ხელსაწყოები — ბათუმი",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan,
    )

    # Static — code-shipped CSS/JS.
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Static — brand assets (logo, hero image).
    brand_dir = DATA_DIR / "brand_assets"
    brand_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/assets/brand", StaticFiles(directory=str(brand_dir)), name="brand")

    # Static — product photos (web-found + founder-uploaded).
    found_dir = DATA_DIR / "found_photos"
    found_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/assets/photos", StaticFiles(directory=str(found_dir)), name="photos")

    uploaded_dir = DATA_DIR / "photos"
    uploaded_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/assets/uploaded", StaticFiles(directory=str(uploaded_dir)), name="uploaded")

    # Overlaid photos (post images after marketing overlay applied).
    overlaid_dir = DATA_DIR / "overlaid_photos"
    overlaid_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/assets/overlaid", StaticFiles(directory=str(overlaid_dir)), name="overlaid")

    # Routes.
    from src.web.routes import (
        admin,
        admin_content,
        admin_dashboard,
        admin_memories,
        admin_posts,
        admin_products,
        admin_sales,
        admin_settings,
        contact,
        home,
        posts,
        products,
        seo,
    )

    app.include_router(home.router)
    app.include_router(products.router)
    app.include_router(posts.router)
    app.include_router(contact.router)
    app.include_router(seo.router)
    # Admin: dashboard first (mounts /admin), then specific sub-prefixes.
    app.include_router(admin_dashboard.router)
    app.include_router(admin_products.router)
    app.include_router(admin_posts.router)
    app.include_router(admin_memories.router)
    app.include_router(admin_sales.router)
    app.include_router(admin_content.router)
    app.include_router(admin_settings.router)
    app.include_router(admin.router)  # /admin/photos (existing)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    log.info("web_app_created", templates=str(TEMPLATES_DIR))
    return app


app = create_app()
