"""Structured logging with secret redaction.

Why structlog: JSON-formatted logs are trivial to filter in Railway's log viewer
('event=publish_attempt' is much nicer than parsing free-form text).

Why a secret redactor: the Page Access Token is the most damaging secret if
leaked (§10 of the plan). Any code path that accidentally logs it — an
exception traceback containing the request URL, a debug `repr()` — would push
the token to Railway's log retention.

The redactor inspects every log event's values and replaces strings that match
known secret shapes with "***REDACTED***".
"""

from __future__ import annotations

import logging
import os
import re
import sys

import structlog

# Patterns matching token shapes. Loose enough to catch tokens even if env
# var names change; tight enough to avoid false positives on normal text.
_TOKEN_PATTERNS = [
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"),       # Telegram: 7123:AAH...
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{40,}\b"),         # Anthropic API key
    re.compile(r"\bAIza[A-Za-z0-9_-]{30,}\b"),            # Google API key
    re.compile(r"\bEAA[A-Za-z0-9]{50,}\b"),               # Meta page/user access token
]

# Env var names whose values must always be redacted, regardless of shape.
_SECRET_ENV_NAMES = {
    "TELEGRAM_BOT_TOKEN",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "META_APP_SECRET",
    "FB_PAGE_ACCESS_TOKEN",
}


def _redact_string(value: str) -> str:
    """Replace any token-shaped substring with REDACTED."""
    for pattern in _TOKEN_PATTERNS:
        value = pattern.sub("***REDACTED***", value)
    return value


def _build_known_secrets() -> set[str]:
    """Collect actual secret values from env so we can substring-match them."""
    secrets = set()
    for name in _SECRET_ENV_NAMES:
        raw = os.getenv(name)
        if raw and len(raw) >= 8:
            secrets.add(raw)
    return secrets


def _redact_processor(logger, method_name, event_dict):
    """structlog processor that redacts secrets from all event values."""
    known_secrets = _build_known_secrets()

    def scrub(v):
        if isinstance(v, str):
            for secret in known_secrets:
                if secret in v:
                    v = v.replace(secret, "***REDACTED***")
            v = _redact_string(v)
            return v
        if isinstance(v, dict):
            return {k: scrub(val) for k, val in v.items()}
        if isinstance(v, (list, tuple)):
            return type(v)(scrub(item) for item in v)
        return v

    return {k: scrub(val) for k, val in event_dict.items()}


def configure(level: str = "INFO") -> None:
    """Configure structlog + stdlib logging. Call once at startup."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_processor,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a logger. Pass `__name__` from the calling module."""
    return structlog.get_logger(name)
