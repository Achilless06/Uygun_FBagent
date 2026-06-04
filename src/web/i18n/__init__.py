"""i18n dispatcher.

Supported languages: `ka` (Georgian, default), `en` (English), `tr` (Turkish).
Each language is a Python module with flat top-level constants. The dispatcher
returns the module so templates can use `t.NAV_HOME` etc.

Lang detection order:
  1. ?lang=xx query parameter
  2. `lang` cookie
  3. default = ka
"""

from __future__ import annotations

from types import ModuleType
from typing import Final

from src.web.i18n import en, ka, ru, tr

SUPPORTED: Final[dict[str, ModuleType]] = {
    "ka": ka,
    "en": en,
    "ru": ru,
    "tr": tr,
}

DEFAULT_LANG: Final[str] = "ka"

# Display metadata for the language switcher (order matters — UI rendering).
LANG_META: Final[list[dict[str, str]]] = [
    {"code": "ka", "name": "ქართული",  "flag": "🇬🇪"},
    {"code": "en", "name": "English",   "flag": "🇺🇸"},
    {"code": "tr", "name": "Türkçe",    "flag": "🇹🇷"},
    {"code": "ru", "name": "Русский",   "flag": "🇷🇺"},
]


def get_strings(lang: str) -> ModuleType:
    """Return the i18n module for `lang`, falling back to the default."""
    return SUPPORTED.get(lang, SUPPORTED[DEFAULT_LANG])


def detect_lang(query_lang: str | None, cookie_lang: str | None) -> str:
    """Resolve the active language from query param + cookie + default."""
    if query_lang and query_lang in SUPPORTED:
        return query_lang
    if cookie_lang and cookie_lang in SUPPORTED:
        return cookie_lang
    return DEFAULT_LANG
