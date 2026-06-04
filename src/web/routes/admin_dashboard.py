"""Admin dashboard — at-a-glance overview at /admin."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from src import budget, db
from src.web.auth import admin_auth
from src.web.render import render
from src.web.routes.admin import _persist_cookie

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    _auth: str = Depends(admin_auth),
) -> HTMLResponse:
    with_photo, total_products = db.count_products_with_photo()
    posts_total = db.count_published_posts()
    drafts_by_status = db.count_post_drafts_by_status()
    spend = budget.status()
    agent_active = db.get_setting("agent_active", "true") == "true"

    latest_posts = db.list_published_posts(limit=5)
    latest_sales = db.list_sales(limit=5)

    sales_7d = db.sales_summary(start=datetime.utcnow() - timedelta(days=7))
    sales_30d = db.sales_summary(start=datetime.utcnow() - timedelta(days=30))

    ctx = {
        "admin_page": "dashboard",
        "with_photo": with_photo,
        "total_products": total_products,
        "photo_pct": (with_photo / total_products * 100) if total_products else 0,
        "posts_total": posts_total,
        "drafts_pending": drafts_by_status.get("pending", 0),
        "drafts_total": sum(drafts_by_status.values()),
        "spend": spend,
        "agent_active": agent_active,
        "latest_posts": latest_posts,
        "latest_sales": latest_sales,
        "sales_7d": sales_7d,
        "sales_30d": sales_30d,
    }
    response = render(request, "admin/dashboard.html", ctx)
    _persist_cookie(response, request)
    return response
