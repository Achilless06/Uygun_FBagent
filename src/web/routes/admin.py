"""Admin upload UI routes (gated by `src.web.auth.admin_auth`).

  GET    /admin/photos             — paginated list with filter + search
  POST   /admin/photos/{code}      — upload (multipart file → data/photos/{code}.jpg)
  POST   /admin/photos/{code}/delete — remove the photo + flip has_photo=False

Pillow normalizes every upload to JPG (max 1600px, quality 85). The bot's
`resolve_image_path()` (src/ai/generator.py) picks the file up automatically
on the next post generation — no bot-side changes are needed.
"""

from __future__ import annotations

import io
from pathlib import Path
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from PIL import Image

from src import config, db
from src.config import PHOTOS_DIR
from src.logging_setup import get_logger
from src.web.auth import COOKIE_NAME, TOKEN_TTL, admin_auth
from src.web.render import render

router = APIRouter(prefix="/admin", tags=["admin"])
log = get_logger(__name__)

PER_PAGE = 24
MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MB
MAX_DIMENSION = 1600  # px, longest edge
JPEG_QUALITY = 85
# Hard cap on Pillow decode size to prevent decompression-bomb DoS.
# Default Pillow MAX_IMAGE_PIXELS is ~178M; we shrink to 40M (≈6300x6300).
Image.MAX_IMAGE_PIXELS = 40_000_000


def _photo_path(code: str) -> Path:
    """Resolve and return the on-disk path for a product code, refusing any
    path that would escape PHOTOS_DIR (defends against traversal via the
    `{code}` URL parameter)."""
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    candidate = (PHOTOS_DIR / f"{code}.jpg").resolve()
    photos_root = PHOTOS_DIR.resolve()
    # candidate must equal photos_root/<file>.jpg with NO intermediate dirs.
    if candidate.parent != photos_root or candidate.suffix != ".jpg":
        raise HTTPException(status_code=400, detail="invalid product code")
    return candidate


def _check_csrf(request: Request) -> None:
    """Verify the request's Origin/Referer matches our PUBLIC_BASE_URL host.
    Basic Auth alone doesn't protect against CSRF since browsers send the
    Authorization header on any cross-origin request to the authenticated
    realm. Origin check is what closes that gap for state-changing routes.

    Logic:
      • If Origin OR Referer is present → it MUST match PUBLIC_BASE_URL,
        otherwise reject (this is the CSRF case browsers always populate).
      • If NEITHER is present → fall back to Host-header equality (covers
        curl smoke tests and server-to-server calls without Origin).
    """
    cfg = config.load()
    expected_host = urlparse(cfg.public_base_url).netloc.lower()
    if not expected_host:
        return  # misconfigured base URL; fail open to avoid lockout

    origin = request.headers.get("origin")
    referer = request.headers.get("referer")

    if origin or referer:
        for raw in (origin, referer):
            if raw and urlparse(raw).netloc.lower() == expected_host:
                return
        raise HTTPException(status_code=403, detail="cross-origin request blocked")

    # No Origin / Referer — accept iff Host matches (curl / same-host server).
    if request.headers.get("host", "").lower() == expected_host:
        return
    raise HTTPException(status_code=403, detail="cross-origin request blocked")


def _persist_cookie(response, request: Request) -> None:
    """If this request authenticated via a fresh `?token=` query, drop the
    token into a cookie so subsequent admin nav works without re-attaching
    it. No-op for Basic Auth or already-cookied requests."""
    token = getattr(request.state, "token_to_persist", None)
    if token:
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=int(TOKEN_TTL.total_seconds()),
            samesite="lax",
            httponly=True,
        )


@router.get("/photos", response_class=HTMLResponse)
async def photos_list(
    request: Request,
    filter: str = "missing",
    search: str = "",
    page: int = 1,
    _auth: str = Depends(admin_auth),
) -> HTMLResponse:
    page = max(1, page)
    has_photo_filter: bool | None
    if filter == "missing":
        has_photo_filter = False
    elif filter == "uploaded":
        has_photo_filter = True
    else:  # "all"
        has_photo_filter = None

    rows, total = db.list_products_paginated(
        search=search or None,
        has_photo=has_photo_filter,
        page=page,
        per_page=PER_PAGE,
    )
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    with_photo, all_total = db.count_products_with_photo()

    # Preserve filter+search in pagination links.
    base_qs = {"filter": filter}
    if search:
        base_qs["search"] = search

    ctx = {
        "admin_page": "photos",
        "products": rows,
        "total": total,
        "with_photo": with_photo,
        "all_total": all_total,
        "filter": filter,
        "search": search,
        "page": page,
        "total_pages": total_pages,
        "base_qs": urlencode(base_qs),
    }
    response = render(request, "admin/photos.html", ctx)
    _persist_cookie(response, request)
    return response


@router.post("/photos/{code}", response_class=HTMLResponse)
async def photos_upload(
    request: Request,
    code: str,
    photo: UploadFile = File(...),
    filter: str = Form("missing"),
    search: str = Form(""),
    page: int = Form(1),
    _auth: str = Depends(admin_auth),
) -> RedirectResponse:
    # 0. CSRF: cross-origin POSTs are blocked even if creds are present.
    _check_csrf(request)

    # 1. Product must exist (also validates the code via DB).
    product = db.get_product(code)
    if product is None:
        raise HTTPException(status_code=404, detail="unknown product code")

    # 2. Read upload bounded by max size.
    content = await photo.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"upload exceeds {MAX_UPLOAD_BYTES // 1024 // 1024} MB",
        )
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="empty upload")

    # 3. Validate + normalize via Pillow.
    try:
        img = Image.open(io.BytesIO(content))
        img.load()  # forces decode, so corrupt files / bombs fail here
    except Image.DecompressionBombError as e:
        log.warning("photo_upload_bomb", code=code)
        raise HTTPException(status_code=413, detail="image too large to decode") from e
    except Exception as e:
        log.warning("photo_upload_invalid", code=code, error=str(e))
        raise HTTPException(status_code=400, detail="not a valid image") from e

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)

    # 4. Save to disk + flip the DB flag. Strip EXIF/ICC profiles for privacy
    # (uploaded photos may carry GPS / camera info — we don't want to leak it).
    dest = _photo_path(code)
    img.save(dest, format="JPEG", quality=JPEG_QUALITY, optimize=True, exif=b"")
    ok = db.set_product_photo(code, has_photo=True)
    if not ok:  # should never happen since get_product passed above
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="failed to update product row")

    log.info("photo_upload_saved", code=code, bytes=dest.stat().st_size,
             auth=getattr(request.state, "auth_method", "?"))

    # 5. Redirect back to the list with the same filter state.
    qs = urlencode({"filter": filter, "search": search, "page": page})
    response = RedirectResponse(url=f"/admin/photos?{qs}", status_code=303)
    _persist_cookie(response, request)
    return response


@router.post("/photos/{code}/delete", response_class=HTMLResponse)
async def photos_delete(
    request: Request,
    code: str,
    filter: str = Form("missing"),
    search: str = Form(""),
    page: int = Form(1),
    _auth: str = Depends(admin_auth),
) -> RedirectResponse:
    _check_csrf(request)
    if db.get_product(code) is None:
        raise HTTPException(status_code=404, detail="unknown product code")
    _photo_path(code).unlink(missing_ok=True)
    db.set_product_photo(code, has_photo=False)
    log.info("photo_upload_deleted", code=code)
    qs = urlencode({"filter": filter, "search": search, "page": page})
    response = RedirectResponse(url=f"/admin/photos?{qs}", status_code=303)
    _persist_cookie(response, request)
    return response
