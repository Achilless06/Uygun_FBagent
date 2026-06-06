"""Admin content analysis tools.

Wraps the `content-creator` skill's two analyzers (brand voice + SEO) and
extends them with Uygun-specific brand checks from `src/brand.py`:

  • Detects informal "შენ" markers that violate the bot's formal "თქვენ" rule
    (Phase 18, 2026-06 — both bot drafts and the website now use "თქვენ")
  • Flags BANNED_PHRASES the brand explicitly avoids
  • Flags the forbidden "სალტე" (must be "საბურავი")
  • Surfaces LOVED_PHRASES present (positive signal)

Generic scripts handle: readability (English), structure (any lang),
sentence variety, SEO score, keyword density.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from src import brand
from src.web.analyzers.brand_voice_analyzer import BrandVoiceAnalyzer
from src.web.analyzers.seo_optimizer import SEOOptimizer
from src.web.auth import admin_auth
from src.web.render import render
from src.web.routes.admin import _check_csrf, _persist_cookie

router = APIRouter(prefix="/admin/content", tags=["admin"])

_voice = BrandVoiceAnalyzer()
_seo = SEOOptimizer()

# Word-boundary regex so e.g. "შემოგვიარე" doesn't false-match the formal
# "შემოგვიარეთ" (same prefix). Mirrors guardrails._SHEN_PATTERNS.
_SHEN_PATTERNS = tuple(
    re.compile(rf"\b{re.escape(m)}\b") for m in brand.SHEN_MARKERS
)


def _uygun_brand_check(text: str) -> dict:
    """Layer Uygun-specific checks on top of the generic analyzer.

    Phase 18 (2026-06): both bot drafts and the public site speak "თქვენ".
    This check flags informal "შენ" markers that the founder needs to clean up.
    """
    banned_found = [p for p in brand.BANNED_PHRASES if p in text]
    shen_found: list[str] = []
    for pattern in _SHEN_PATTERNS:
        m = pattern.search(text)
        if m:
            shen_found.append(m.group(0))
    loved_found = [p for p in brand.LOVED_PHRASES if p in text]
    has_forbidden_tire = brand.TIRE_FORBIDDEN in text

    # Compute a 0-100 brand compliance score.
    score = 100
    score -= len(banned_found) * 25      # each banned phrase = -25
    score -= len(shen_found) * 10        # each informal marker = -10
    score -= 25 if has_forbidden_tire else 0
    score += min(len(loved_found) * 5, 15)  # cap +15 bonus
    score = max(0, min(100, score))

    return {
        "score": score,
        "banned_found": banned_found,
        "shen_found": shen_found,
        "loved_found": loved_found,
        "has_forbidden_tire": has_forbidden_tire,
    }


@router.get("", response_class=HTMLResponse)
async def content_tools(
    request: Request,
    _auth: str = Depends(admin_auth),
) -> HTMLResponse:
    ctx = {"admin_page": "content", "voice": None, "seo": None, "voice_text": "", "seo_text": "", "seo_keyword": ""}
    response = render(request, "admin/content_tools.html", ctx)
    _persist_cookie(response, request)
    return response


@router.post("/voice", response_class=HTMLResponse)
async def analyze_voice(
    request: Request,
    text: str = Form(...),
    _auth: str = Depends(admin_auth),
) -> HTMLResponse:
    _check_csrf(request)
    generic = _voice.analyze_text(text)
    uygun = _uygun_brand_check(text)
    ctx = {
        "admin_page": "content",
        "voice": {"generic": generic, "uygun": uygun},
        "voice_text": text,
        "seo": None,
        "seo_text": "",
        "seo_keyword": "",
    }
    response = render(request, "admin/content_tools.html", ctx)
    _persist_cookie(response, request)
    return response


@router.post("/seo", response_class=HTMLResponse)
async def analyze_seo(
    request: Request,
    text: str = Form(...),
    keyword: str = Form(""),
    _auth: str = Depends(admin_auth),
) -> HTMLResponse:
    _check_csrf(request)
    seo = _seo.analyze(text, keyword.strip() or None)
    ctx = {
        "admin_page": "content",
        "seo": seo,
        "seo_text": text,
        "seo_keyword": keyword,
        "voice": None,
        "voice_text": "",
    }
    response = render(request, "admin/content_tools.html", ctx)
    _persist_cookie(response, request)
    return response
