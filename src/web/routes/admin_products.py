"""Admin products — list, search, edit price/stock/category/name."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src import db
from src.logging_setup import get_logger
from src.web.auth import admin_auth
from src.web.render import render
from src.web.routes.admin import _check_csrf, _persist_cookie

router = APIRouter(prefix="/admin/products", tags=["admin"])
log = get_logger(__name__)

PER_PAGE = 30


@router.get("", response_class=HTMLResponse)
async def products_list(
    request: Request,
    search: str = "",
    category: str = "",
    page: int = 1,
    _auth: str = Depends(admin_auth),
) -> HTMLResponse:
    page = max(1, page)
    rows, total = db.list_products_paginated(
        category=category or None,
        search=search or None,
        page=page,
        per_page=PER_PAGE,
    )
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    categories = db.list_categories()

    base_qs = {}
    if search:
        base_qs["search"] = search
    if category:
        base_qs["category"] = category

    ctx = {
        "admin_page": "products",
        "products": rows,
        "total": total,
        "search": search,
        "category": category,
        "categories": categories,
        "page": page,
        "total_pages": total_pages,
        "base_qs": urlencode(base_qs),
    }
    response = render(request, "admin/products.html", ctx)
    _persist_cookie(response, request)
    return response


@router.get("/{code}/edit", response_class=HTMLResponse)
async def product_edit_form(
    request: Request,
    code: str,
    _auth: str = Depends(admin_auth),
) -> HTMLResponse:
    product = db.get_product(code)
    if product is None:
        raise HTTPException(status_code=404, detail="unknown product code")
    ctx = {
        "admin_page": "products",
        "product": product,
        "categories": db.list_categories(),
    }
    response = render(request, "admin/product_edit.html", ctx)
    _persist_cookie(response, request)
    return response


@router.post("/{code}/edit", response_class=HTMLResponse)
async def product_edit_submit(
    request: Request,
    code: str,
    name: str = Form(...),
    price: str = Form(""),
    stock_qty: int = Form(0),
    category: str = Form(""),
    _auth: str = Depends(admin_auth),
) -> RedirectResponse:
    _check_csrf(request)

    if db.get_product(code) is None:
        raise HTTPException(status_code=404, detail="unknown product code")

    try:
        parsed_price = float(price) if price.strip() else 0.0
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid price") from None

    ok = db.update_product(
        code,
        name=name,
        price=parsed_price,
        stock_qty=stock_qty,
        category=category,
    )
    if not ok:
        raise HTTPException(status_code=500, detail="update failed")

    log.info("admin_product_updated", code=code, auth=getattr(request.state, "auth_method", "?"))
    response = RedirectResponse(url="/admin/products", status_code=303)
    _persist_cookie(response, request)
    return response
