"""Admin posts — list drafts (all statuses) + published, view detail, delete drafts."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src import db
from src.logging_setup import get_logger
from src.web.auth import admin_auth
from src.web.render import render
from src.web.routes.admin import _check_csrf, _persist_cookie

router = APIRouter(prefix="/admin/posts", tags=["admin"])
log = get_logger(__name__)

PER_PAGE = 20
STATUSES = ["pending", "approved", "edited", "rejected", "published"]


@router.get("", response_class=HTMLResponse)
async def posts_list(
    request: Request,
    status: str = "",
    page: int = 1,
    _auth: str = Depends(admin_auth),
) -> HTMLResponse:
    page = max(1, page)
    status_filter = status if status in STATUSES else None

    drafts, total = db.list_post_drafts(
        status=status_filter,
        limit=PER_PAGE,
        offset=(page - 1) * PER_PAGE,
    )
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

    base_qs = {}
    if status_filter:
        base_qs["status"] = status_filter

    ctx = {
        "admin_page": "posts",
        "drafts": drafts,
        "total": total,
        "status": status_filter or "",
        "statuses": STATUSES,
        "page": page,
        "total_pages": total_pages,
        "base_qs": urlencode(base_qs),
    }
    response = render(request, "admin/posts.html", ctx)
    _persist_cookie(response, request)
    return response


@router.get("/{draft_id}", response_class=HTMLResponse)
async def post_detail(
    request: Request,
    draft_id: int,
    _auth: str = Depends(admin_auth),
) -> HTMLResponse:
    draft = db.get_post_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="draft not found")
    ctx = {
        "admin_page": "posts",
        "draft": draft,
    }
    response = render(request, "admin/post_detail.html", ctx)
    _persist_cookie(response, request)
    return response


@router.post("/{draft_id}/delete", response_class=HTMLResponse)
async def post_delete(
    request: Request,
    draft_id: int,
    _auth: str = Depends(admin_auth),
) -> RedirectResponse:
    _check_csrf(request)
    ok = db.delete_post_draft(draft_id)
    if not ok:
        raise HTTPException(status_code=400, detail="cannot delete (published or missing)")
    log.info("admin_draft_deleted", id=draft_id)
    response = RedirectResponse(url="/admin/posts", status_code=303)
    _persist_cookie(response, request)
    return response
