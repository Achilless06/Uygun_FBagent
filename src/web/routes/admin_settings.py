"""Admin settings — monthly budget, agent active toggle, posting times."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src import budget, db
from src.logging_setup import get_logger
from src.web.auth import admin_auth
from src.web.render import render
from src.web.routes.admin import _check_csrf, _persist_cookie

router = APIRouter(prefix="/admin/settings", tags=["admin"])
log = get_logger(__name__)


@router.get("", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    _auth: str = Depends(admin_auth),
) -> HTMLResponse:
    ctx = {
        "admin_page": "settings",
        "agent_active": db.get_setting("agent_active", "true") == "true",
        "monthly_budget": db.get_setting("monthly_budget_usd", "20"),
        "post_gen_time": db.get_setting("post_gen_time", "11:30"),
        "post_publish_time": db.get_setting("post_publish_time", "12:00"),
        "tone_mode": db.get_setting("tone_mode", "default"),
        "inventory_threshold": db.get_setting("inventory_alert_threshold", "5"),
        "spend": budget.status(),
    }
    response = render(request, "admin/settings.html", ctx)
    _persist_cookie(response, request)
    return response


@router.post("", response_class=HTMLResponse)
async def settings_save(
    request: Request,
    agent_active: str = Form("false"),
    monthly_budget_usd: str = Form("20"),
    post_gen_time: str = Form("11:30"),
    post_publish_time: str = Form("12:00"),
    tone_mode: str = Form("default"),
    inventory_alert_threshold: int = Form(5),
    _auth: str = Depends(admin_auth),
) -> RedirectResponse:
    _check_csrf(request)

    try:
        budget_val = float(monthly_budget_usd)
        if budget_val <= 0:
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid budget") from None

    db.set_setting("agent_active", "true" if agent_active == "true" else "false")
    db.set_setting("monthly_budget_usd", str(budget_val))
    db.set_setting("post_gen_time", post_gen_time.strip() or "11:30")
    db.set_setting("post_publish_time", post_publish_time.strip() or "12:00")
    db.set_setting("tone_mode", tone_mode.strip() or "default")
    db.set_setting("inventory_alert_threshold", str(max(0, inventory_alert_threshold)))

    log.info("admin_settings_saved", agent_active=agent_active, budget=budget_val,
             inventory_threshold=inventory_alert_threshold)
    response = RedirectResponse(url="/admin/settings", status_code=303)
    _persist_cookie(response, request)
    return response
