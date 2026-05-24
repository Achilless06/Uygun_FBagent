"""robots.txt and sitemap.xml — auto-generated from DB."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response

from src import db

router = APIRouter()


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots(request: Request) -> str:
    base = str(request.base_url).rstrip("/")
    return f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n"


@router.get("/sitemap.xml")
async def sitemap(request: Request) -> Response:
    base = str(request.base_url).rstrip("/")
    now = datetime.now(timezone.utc).date().isoformat()

    urls: list[tuple[str, str]] = [
        (f"{base}/", "1.0"),
        (f"{base}/products", "0.9"),
        (f"{base}/posts", "0.8"),
        (f"{base}/contact", "0.7"),
    ]

    catalog, _ = db.list_products_paginated(page=1, per_page=10000)
    for p in catalog:
        urls.append((f"{base}/products/{p.code}", "0.5"))

    posts = db.list_published_posts(limit=1000)
    for post in posts:
        urls.append((f"{base}/posts/{post.id}", "0.6"))

    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, prio in urls:
        body.append(
            f"  <url><loc>{loc}</loc><lastmod>{now}</lastmod>"
            f"<priority>{prio}</priority></url>"
        )
    body.append("</urlset>")
    return Response(content="\n".join(body), media_type="application/xml")
