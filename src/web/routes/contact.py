"""Contact page — phone, WhatsApp, address, map."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src import brand
from src.web.app import templates

router = APIRouter()


@router.get("/contact", response_class=HTMLResponse)
async def contact(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "contact.html",
        {
            "phone": brand.CONTACT_PHONE,
            "whatsapp": brand.CONTACT_WHATSAPP,
            "address": brand.CONTACT_ADDRESS,
            "hours": brand.WORKING_HOURS,
            "delivery_note": brand.DELIVERY_NOTE,
        },
    )
