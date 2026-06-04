"""Admin memories — list, add, delete the founder's long-term corrections."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src import db
from src.logging_setup import get_logger
from src.web.auth import admin_auth
from src.web.render import render
from src.web.routes.admin import _check_csrf, _persist_cookie

router = APIRouter(prefix="/admin/memories", tags=["admin"])
log = get_logger(__name__)

ALLOWED_CATEGORIES = ["preference", "style", "dislike", "fact", "learned"]


@router.get("", response_class=HTMLResponse)
async def memories_list(
    request: Request,
    _auth: str = Depends(admin_auth),
) -> HTMLResponse:
    memories = db.list_memories(limit=500)
    ctx = {
        "admin_page": "memories",
        "memories": memories,
        "categories": ALLOWED_CATEGORIES,
    }
    response = render(request, "admin/memories.html", ctx)
    _persist_cookie(response, request)
    return response


@router.post("", response_class=HTMLResponse)
async def memories_add(
    request: Request,
    content: str = Form(...),
    category: str = Form("preference"),
    _auth: str = Depends(admin_auth),
) -> RedirectResponse:
    _check_csrf(request)
    content = content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="empty memory")
    if category not in ALLOWED_CATEGORIES:
        category = "preference"
    memory_id = db.add_memory(content=content, category=category, source="manual")
    log.info("admin_memory_added", id=memory_id, category=category)
    response = RedirectResponse(url="/admin/memories", status_code=303)
    _persist_cookie(response, request)
    return response


@router.post("/{memory_id}/delete", response_class=HTMLResponse)
async def memories_delete(
    request: Request,
    memory_id: int,
    _auth: str = Depends(admin_auth),
) -> RedirectResponse:
    _check_csrf(request)
    ok = db.delete_memory(memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="memory not found")
    log.info("admin_memory_deleted", id=memory_id)
    response = RedirectResponse(url="/admin/memories", status_code=303)
    _persist_cookie(response, request)
    return response
