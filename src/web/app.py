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

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config import DATA_DIR
from src.logging_setup import get_logger

log = get_logger(__name__)

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Make Gemini-generated copy module + brand constants globally available in templates.
from src import brand as _brand  # noqa: E402
from src.web import copy as _copy  # noqa: E402

templates.env.globals["copy"] = _copy
templates.env.globals["brand"] = _brand


def create_app() -> FastAPI:
    app = FastAPI(
        title="Uygun Georgia",
        description="ვულკანიზაცია · ავტოქიმია · ხელსაწყოები — ბათუმი",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
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
    from src.web.routes import contact, home, posts, products, seo

    app.include_router(home.router)
    app.include_router(products.router)
    app.include_router(posts.router)
    app.include_router(contact.router)
    app.include_router(seo.router)

    log.info("web_app_created", templates=str(TEMPLATES_DIR))
    return app


app = create_app()
