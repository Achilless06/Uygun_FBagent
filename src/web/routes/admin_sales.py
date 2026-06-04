"""Admin sales — list, add, edit, delete sales records."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src import db
from src.logging_setup import get_logger
from src.web.auth import admin_auth
from src.web.render import render
from src.web.routes.admin import _check_csrf, _persist_cookie

router = APIRouter(prefix="/admin/sales", tags=["admin"])
log = get_logger(__name__)


@router.get("", response_class=HTMLResponse)
async def sales_list(
    request: Request,
    _auth: str = Depends(admin_auth),
) -> HTMLResponse:
    sales = db.list_sales(limit=200)
    ctx = {
        "admin_page": "sales",
        "sales": sales,
    }
    response = render(request, "admin/sales.html", ctx)
    _persist_cookie(response, request)
    return response


@router.post("", response_class=HTMLResponse)
async def sales_add(
    request: Request,
    product_code: str = Form(...),
    quantity: float = Form(...),
    unit_price: float = Form(...),
    notes: str = Form(""),
    _auth: str = Depends(admin_auth),
) -> RedirectResponse:
    _check_csrf(request)
    if quantity <= 0 or unit_price < 0:
        raise HTTPException(status_code=400, detail="invalid quantity or price")
    try:
        db.add_sale(
            product_code=product_code.strip(),
            quantity=quantity,
            unit_price=unit_price,
            notes=notes.strip() or None,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    log.info("admin_sale_added", code=product_code, qty=quantity, price=unit_price)
    response = RedirectResponse(url="/admin/sales", status_code=303)
    _persist_cookie(response, request)
    return response


@router.get("/{sale_id}/invoice", response_class=HTMLResponse)
async def sale_invoice(
    request: Request,
    sale_id: int,
    _auth: str = Depends(admin_auth),
) -> HTMLResponse:
    sale = db.get_sale(sale_id)
    if sale is None:
        raise HTTPException(status_code=404, detail="sale not found")
    ctx = {
        "admin_page": "sales",
        "sale": sale,
    }
    response = render(request, "admin/invoice.html", ctx)
    _persist_cookie(response, request)
    return response


@router.get("/{sale_id}/edit", response_class=HTMLResponse)
async def sale_edit_form(
    request: Request,
    sale_id: int,
    _auth: str = Depends(admin_auth),
) -> HTMLResponse:
    sale = db.get_sale(sale_id)
    if sale is None:
        raise HTTPException(status_code=404, detail="sale not found")
    ctx = {
        "admin_page": "sales",
        "sale": sale,
    }
    response = render(request, "admin/sale_edit.html", ctx)
    _persist_cookie(response, request)
    return response


@router.post("/{sale_id}/edit", response_class=HTMLResponse)
async def sale_edit_submit(
    request: Request,
    sale_id: int,
    quantity: float = Form(...),
    unit_price: float = Form(...),
    notes: str = Form(""),
    _auth: str = Depends(admin_auth),
) -> RedirectResponse:
    _check_csrf(request)
    if quantity <= 0 or unit_price < 0:
        raise HTTPException(status_code=400, detail="invalid quantity or price")
    updated = db.update_sale(
        sale_id,
        quantity=quantity,
        unit_price=unit_price,
        notes=notes,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="sale not found")
    log.info("admin_sale_updated", id=sale_id)
    response = RedirectResponse(url="/admin/sales", status_code=303)
    _persist_cookie(response, request)
    return response


@router.post("/{sale_id}/delete", response_class=HTMLResponse)
async def sale_delete(
    request: Request,
    sale_id: int,
    _auth: str = Depends(admin_auth),
) -> RedirectResponse:
    _check_csrf(request)
    ok = db.delete_sale(sale_id)
    if not ok:
        raise HTTPException(status_code=404, detail="sale not found")
    log.info("admin_sale_deleted", id=sale_id)
    response = RedirectResponse(url="/admin/sales", status_code=303)
    _persist_cookie(response, request)
    return response
