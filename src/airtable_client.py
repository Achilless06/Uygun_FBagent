"""Minimal Airtable HTTP client (Personal Access Token auth).

Used by the bot's `/import_sales` flow to push the monthly Top-15 demand
snapshot. Built with `requests` (already in requirements.txt) — no extra
dep, no async story; the FSM handler calls it inside `asyncio.to_thread`.

PAT setup (one-time, founder):
  1. Open https://airtable.com/create/tokens
  2. Create token → scopes: `data.records:read`, `data.records:write`,
     `schema.bases:read`. Access: select the "Uygun CRM" base only.
  3. Copy token → set `AIRTABLE_TOKEN` env var (Railway dashboard + .env).

The token + base ID + table ID are all read from `config.Config` so the
caller doesn't have to plumb them through.
"""

from __future__ import annotations

import time
from typing import Any, Iterable, Optional

import requests

from src.logging_setup import get_logger

log = get_logger(__name__)

_API_BASE = "https://api.airtable.com/v0"

# Airtable's create_records cap is 10 records per request (raised silently to
# higher levels in some cases, but 10 is the official documented max).
_BATCH_SIZE = 10
# Retry once on a transient 5xx with linear backoff.
_RETRIES = 2
_BACKOFF_SECONDS = 1.5


class AirtableError(RuntimeError):
    """Wraps a non-2xx Airtable API response with the parsed error body."""

    def __init__(self, status_code: int, body: Any, url: str):
        self.status_code = status_code
        self.body = body
        super().__init__(
            f"Airtable {status_code} from {url}: {body!r}"
        )


class AirtableClient:
    def __init__(self, token: str, base_id: str, *, timeout: float = 30.0):
        if not token:
            raise ValueError("AIRTABLE_TOKEN is empty — see src/airtable_client.py docstring")
        if not base_id:
            raise ValueError("base_id is empty")
        self._token = token
        self._base_id = base_id
        self._timeout = timeout
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    # ─── HTTP plumbing ──────────────────────────────────────────────────────

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{_API_BASE}/{self._base_id}/{path}"
        last_exc: Optional[Exception] = None
        for attempt in range(_RETRIES + 1):
            try:
                r = requests.request(
                    method, url, headers=self._headers, timeout=self._timeout, **kwargs
                )
            except requests.RequestException as e:
                last_exc = e
                log.warning(
                    "airtable_network_error",
                    method=method, url=url, attempt=attempt + 1, error=str(e),
                )
                if attempt == _RETRIES:
                    raise
                time.sleep(_BACKOFF_SECONDS * (attempt + 1))
                continue

            if 500 <= r.status_code < 600 and attempt < _RETRIES:
                log.warning(
                    "airtable_5xx_retry", status=r.status_code, attempt=attempt + 1,
                )
                time.sleep(_BACKOFF_SECONDS * (attempt + 1))
                continue

            if not r.ok:
                try:
                    body = r.json()
                except ValueError:
                    body = r.text
                raise AirtableError(r.status_code, body, url)

            if not r.content:
                return {}
            return r.json()

        if last_exc:
            raise last_exc
        raise RuntimeError("airtable retry loop exited without result")

    # ─── Records ────────────────────────────────────────────────────────────

    def create_records(
        self,
        table_id: str,
        records: list[dict],
        *,
        typecast: bool = False,
    ) -> list[dict]:
        """POST records in batches of 10. Returns the created records."""
        created: list[dict] = []
        for i in range(0, len(records), _BATCH_SIZE):
            chunk = records[i:i + _BATCH_SIZE]
            payload = {"records": [{"fields": r} for r in chunk]}
            if typecast:
                payload["typecast"] = True
            resp = self._request("POST", table_id, json=payload)
            created.extend(resp.get("records", []))
            log.info("airtable_created", table=table_id, count=len(chunk),
                     batch=(i // _BATCH_SIZE) + 1)
        return created

    def list_records(
        self,
        table_id: str,
        *,
        filter_by_formula: Optional[str] = None,
        max_records: int = 1000,
        fields: Optional[list[str]] = None,
    ) -> list[dict]:
        """Paginated GET. Returns all matching records up to `max_records`."""
        out: list[dict] = []
        offset: Optional[str] = None
        params_base: dict[str, Any] = {"pageSize": 100}
        if filter_by_formula:
            params_base["filterByFormula"] = filter_by_formula
        if fields:
            for f in fields:
                params_base.setdefault("fields[]", []).append(f)
        while True:
            params = dict(params_base)
            if offset:
                params["offset"] = offset
            resp = self._request("GET", table_id, params=params)
            out.extend(resp.get("records", []))
            if len(out) >= max_records:
                return out[:max_records]
            offset = resp.get("offset")
            if not offset:
                return out

    def delete_records(self, table_id: str, record_ids: Iterable[str]) -> int:
        """DELETE records by id (chunks of 10). Returns count deleted."""
        ids = list(record_ids)
        deleted = 0
        for i in range(0, len(ids), _BATCH_SIZE):
            chunk = ids[i:i + _BATCH_SIZE]
            params = [("records[]", r) for r in chunk]
            resp = self._request("DELETE", table_id, params=params)
            deleted += sum(1 for r in resp.get("records", []) if r.get("deleted"))
        return deleted


# ─── Convenience factory ────────────────────────────────────────────────────


def from_config():
    """Build an AirtableClient using values from `src.config.load()`.

    Raises a clear setup error if `AIRTABLE_TOKEN` is unset — caller should
    catch and surface a Telegram-friendly message to the founder.
    """
    from src import config as _config

    cfg = _config.load()
    if not cfg.airtable_token:
        raise RuntimeError(
            "AIRTABLE_TOKEN not set. Create a PAT at "
            "https://airtable.com/create/tokens (scopes: data.records:read/write, "
            "schema.bases:read; access: Uygun CRM base) and set it in .env / "
            "Railway dashboard."
        )
    return AirtableClient(cfg.airtable_token, cfg.airtable_base_id)
