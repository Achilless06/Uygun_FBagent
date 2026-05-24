"""Landing page route."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src import brand, db
from src.web.app import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    featured = db.list_featured_products(limit=6)
    latest_posts = db.list_published_posts(limit=3)

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "featured": featured,
            "latest_posts": latest_posts,
            "values": brand.VALUES,
            "mission": brand.MISSION,
            "contact_phone": brand.CONTACT_PHONE,
            "contact_address": brand.CONTACT_ADDRESS,
            "delivery_note": brand.DELIVERY_NOTE,
        },
    )
