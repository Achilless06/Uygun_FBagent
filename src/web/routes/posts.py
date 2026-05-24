"""Published-post feed pages (auto-syncs with bot's FB output)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from src import db
from src.web.app import templates

router = APIRouter()

PER_PAGE = 12


@router.get("/posts", response_class=HTMLResponse)
async def list_posts(request: Request, page: int = 1) -> HTMLResponse:
    page = max(1, page)
    rows = db.list_published_posts(limit=PER_PAGE, offset=(page - 1) * PER_PAGE)
    total = db.count_published_posts()
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    return templates.TemplateResponse(
        request,
        "posts/list.html",
        {
            "posts": rows,
            "total": total,
            "page": page,
            "total_pages": total_pages,
        },
    )


@router.get("/posts/{post_id}", response_class=HTMLResponse)
async def post_detail(request: Request, post_id: int) -> HTMLResponse:
    p = db.get_published_post(post_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return templates.TemplateResponse(request, "posts/detail.html", {"post": p})
