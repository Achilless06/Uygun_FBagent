"""Landing page route."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src import db
from src.web.render import render

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    featured = db.list_featured_products(limit=6)
    latest_posts = db.list_published_posts(limit=3)

    _, total_products = db.count_products_with_photo()

    return render(
        request,
        "home.html",
        {
            "featured": featured,
            "latest_posts": latest_posts,
            "stats": {
                "products": total_products,
            },
        },
    )
