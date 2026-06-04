"""Helper to render templates with i18n context + lang cookie persistence.

Routes call `render(request, template, ctx)` instead of TemplateResponse directly.
The helper:
  1. Resolves the active language (query → cookie → default ka).
  2. Injects `t` (strings module), `lang` (code), `langs` (switcher metadata).
  3. Persists the language choice in a cookie when `?lang=` is set.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse

from src.web import i18n
from src.web.app import templates

COOKIE_NAME = "lang"
COOKIE_MAX_AGE = 365 * 24 * 3600  # 1 year


def render(request: Request, template: str, ctx: dict[str, Any]) -> HTMLResponse:
    query_lang = request.query_params.get("lang")
    cookie_lang = request.cookies.get(COOKIE_NAME)
    lang = i18n.detect_lang(query_lang, cookie_lang)
    t = i18n.get_strings(lang)

    full_ctx: dict[str, Any] = {
        **ctx,
        "t": t,
        "lang": lang,
        "langs": i18n.LANG_META,
    }
    response = templates.TemplateResponse(request, template, full_ctx)
    if query_lang and query_lang in i18n.SUPPORTED:
        response.set_cookie(
            COOKIE_NAME,
            lang,
            max_age=COOKIE_MAX_AGE,
            samesite="lax",
            httponly=False,
        )
    return response
