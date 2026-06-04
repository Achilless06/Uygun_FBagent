"""Catalog browse + single product pages."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from src import db
from src.web.render import render

router = APIRouter()

PER_PAGE = 24


@router.get("/products", response_class=HTMLResponse)
async def list_products(
    request: Request,
    category: str | None = None,
    search: str | None = None,
    page: int = 1,
) -> HTMLResponse:
    page = max(1, page)
    rows, total = db.list_products_paginated(
        category=category, search=search, page=page, per_page=PER_PAGE
    )
    categories = db.list_categories()
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    return render(
        request,
        "products/list.html",
        {
            "products": rows,
            "total": total,
            "categories": categories,
            "category": category,
            "search": search or "",
            "page": page,
            "total_pages": total_pages,
        },
    )


@router.get("/products/{code}", response_class=HTMLResponse)
async def product_detail(request: Request, code: str) -> HTMLResponse:
    p = db.get_product(code)
    if p is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return render(request, "products/detail.html", {"product": p})
