"""Contact page — phone, WhatsApp, address, map."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src.web.render import render

router = APIRouter()


@router.get("/contact", response_class=HTMLResponse)
async def contact(request: Request) -> HTMLResponse:
    return render(request, "contact.html", {})
