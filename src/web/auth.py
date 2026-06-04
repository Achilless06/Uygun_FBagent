"""Admin auth for the /admin/photos upload page.

Two parallel credential paths — either succeeds:

1. **HTTP Basic Auth** with `ADMIN_USERNAME` + `ADMIN_PASSWORD` from .env.
   Standard 401 + `WWW-Authenticate: Basic` challenge so the browser
   pops the password prompt; saved by the browser's keychain after first
   success. `secrets.compare_digest` for constant-time comparison.

2. **Magic-link token** issued by the Telegram bot's `/upload` command.
   Token format: `secrets.token_urlsafe(24)`, valid 30 minutes, stored
   in the process-local dict `_TOKENS`. After verification on
   `?token=<...>`, a `upload_token` cookie is set so the user can
   navigate inside `/admin/photos/*` without re-attaching the query
   parameter.

Token storage is in-memory and lost on bot restart — that's fine; the
founder rarely restarts, and they can always re-issue via `/upload`.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from src import config

# {token: expires_at_utc}
_TOKENS: dict[str, datetime] = {}
TOKEN_TTL = timedelta(minutes=30)
COOKIE_NAME = "upload_token"

# Use `auto_error=False` so missing credentials produce None instead of 401 —
# we handle the response ourselves so we can also try the token first.
_basic = HTTPBasic(auto_error=False)


def issue_token() -> tuple[str, datetime]:
    """Generate a fresh magic-link token. Called by the Telegram `/upload` cmd."""
    _gc_expired()
    token = secrets.token_urlsafe(24)
    expires = datetime.now(timezone.utc) + TOKEN_TTL
    _TOKENS[token] = expires
    return token, expires


def _gc_expired() -> None:
    now = datetime.now(timezone.utc)
    expired = [t for t, exp in _TOKENS.items() if exp <= now]
    for t in expired:
        _TOKENS.pop(t, None)


def _token_valid(token: str | None) -> bool:
    if not token:
        return False
    exp = _TOKENS.get(token)
    return exp is not None and exp > datetime.now(timezone.utc)


def _basic_ok(creds: HTTPBasicCredentials | None) -> bool:
    if creds is None:
        return False
    cfg = config.load()
    user_ok = secrets.compare_digest(creds.username, cfg.admin_username)
    pass_ok = secrets.compare_digest(creds.password, cfg.admin_password)
    return user_ok and pass_ok


def admin_auth(
    request: Request,
    creds: HTTPBasicCredentials | None = Depends(_basic),
) -> str:
    """FastAPI dependency for `/admin/*` routes.

    Returns the auth method name on success ("token" or "basic"); raises
    401 with WWW-Authenticate on failure.
    """
    # 1. Token via query param (fresh magic link).
    query_token = request.query_params.get("token")
    if _token_valid(query_token):
        request.state.auth_method = "token"
        request.state.token_to_persist = query_token
        return "token"

    # 2. Token via cookie (sticky after first magic-link hit).
    cookie_token = request.cookies.get(COOKIE_NAME)
    if _token_valid(cookie_token):
        request.state.auth_method = "token"
        return "token"

    # 3. HTTP Basic Auth.
    if _basic_ok(creds):
        request.state.auth_method = "basic"
        return "basic"

    raise HTTPException(
        status_code=401,
        detail="Unauthorized",
        headers={"WWW-Authenticate": 'Basic realm="Uygun Georgia admin"'},
    )
