"""Meta Graph API publisher — uploads a photo + caption to the FB Page.

We use the `/{page-id}/photos` endpoint which:
  - Accepts a multipart file upload (the rendered image, real or text-card)
  - Takes a `caption` parameter (the post body + hashtags)
  - Returns `{id, post_id}` — we save the post_id as our fb_post_id

Why not /feed: /feed posts text-only or text+url. For consistent visual
branding we always upload a photo, and /photos is the right endpoint.

DRY_RUN handling: if `cfg.dry_run=true`, we log the would-be call but return
a synthetic "dryrun-{timestamp}" id without touching the API. This is how
Phase 4 testing has been working — flipping DRY_RUN=false unlocks real posts.

Credential validation: at first publish attempt we hit /me to verify the
token actually works. A 401 here points straight at the token (most common
failure mode is "I generated a short-lived one and forgot to exchange it").
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src import config, db
from src.logging_setup import get_logger

log = get_logger(__name__)

GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# Tenacity will retry on transient network errors but NOT on 4xx (auth/permission
# bugs — those are configuration issues, retrying won't help).
_RETRY_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)


@dataclass
class PublishResult:
    fb_post_id: str          # "{page_id}_{post_id}" — globally unique
    fb_permalink: Optional[str]
    dry_run: bool


class FacebookPublishError(Exception):
    """Raised when Meta Graph API rejects the request (4xx) or returns an error."""


class FacebookCredentialsMissing(Exception):
    """Raised when DRY_RUN=false but Meta env vars are unset/empty."""


def _require_credentials(cfg: config.Config) -> None:
    """In live mode, the four Meta env vars MUST be present."""
    missing = [
        name for name, value in (
            ("META_APP_ID", cfg.meta_app_id),
            ("META_APP_SECRET", cfg.meta_app_secret),
            ("FB_PAGE_ID", cfg.fb_page_id),
            ("FB_PAGE_ACCESS_TOKEN", cfg.fb_page_access_token),
        )
        if not value
    ]
    if missing:
        raise FacebookCredentialsMissing(
            f"Cannot publish: missing env vars {missing}. "
            f"Either complete the Meta App setup or set DRY_RUN=true."
        )


@retry(
    retry=retry_if_exception_type(_RETRY_EXCEPTIONS),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=20),
    reraise=True,
)
def _post_photo(
    page_id: str,
    page_token: str,
    image_path: Path,
    caption: str,
    timeout_seconds: int = 60,
) -> dict:
    """One HTTP call. Returns the JSON response dict on success.

    Raises FacebookPublishError on 4xx with the error message inside.
    """
    url = f"{GRAPH_BASE}/{page_id}/photos"
    with open(image_path, "rb") as fp:
        files = {"source": (image_path.name, fp, _guess_mime(image_path))}
        data = {
            "caption": caption,
            "access_token": page_token,
            # `published=true` is the default; set explicitly for clarity.
            "published": "true",
        }
        response = requests.post(url, data=data, files=files, timeout=timeout_seconds)

    if response.status_code >= 400:
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text[:500]}
        err = payload.get("error", {})
        msg = err.get("message") or payload.get("raw") or "unknown"
        log.error(
            "fb_publish_http_error",
            status_code=response.status_code,
            error_message=msg[:200],
            fbtrace_id=err.get("fbtrace_id"),
        )
        raise FacebookPublishError(
            f"Meta Graph API {response.status_code}: {msg}"
        )

    return response.json()


def _guess_mime(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".gif":
        return "image/gif"
    return "application/octet-stream"


def _build_caption(body_text: str, hashtags: list[str]) -> str:
    """Combine body + hashtags into a single Facebook caption.

    FB allows ~63k chars but Telegram preview / readability favors brevity.
    We trust the generator to keep the body short; just join hashtags on the
    end as a separate line.
    """
    body = body_text.strip()
    tag_line = " ".join(hashtags).strip() if hashtags else ""
    if tag_line:
        return f"{body}\n\n{tag_line}"
    return body


def verify_credentials(cfg: Optional[config.Config] = None) -> dict:
    """Sanity-check the token by hitting /me. Returns the page info dict.

    Use this in a /test_fb Telegram command before the first real publish:
    if the token is wrong/short-lived, this fails clearly with a 401.
    """
    cfg = cfg or config.load()
    _require_credentials(cfg)
    response = requests.get(
        f"{GRAPH_BASE}/me",
        params={"access_token": cfg.fb_page_access_token, "fields": "id,name,category"},
        timeout=15,
    )
    if response.status_code >= 400:
        try:
            err = response.json().get("error", {})
        except ValueError:
            err = {}
        raise FacebookPublishError(
            f"Token verify failed ({response.status_code}): {err.get('message', response.text[:200])}"
        )
    return response.json()


def publish_post(
    body_text: str,
    hashtags: list[str],
    image_path: str | Path,
    cfg: Optional[config.Config] = None,
) -> PublishResult:
    """Public entry point — publish a generated post to the FB Page.

    DRY_RUN behavior: logs the would-be call and returns a synthetic id.
    Live behavior: hits /{page}/photos with the image as multipart upload.
    Records spend (provider=meta, cost_usd=0 — Graph API is free).
    """
    cfg = cfg or config.load()
    image_path = Path(image_path)
    if not image_path.exists():
        raise FacebookPublishError(f"Image file not found: {image_path}")

    caption = _build_caption(body_text, hashtags)

    if cfg.dry_run:
        synth_id = f"dryrun-{int(time.time())}"
        log.info(
            "fb_publish_dry_run",
            caption_chars=len(caption),
            image_path=str(image_path),
            synthetic_id=synth_id,
        )
        _record_publish(operation="publish_dryrun")
        return PublishResult(fb_post_id=synth_id, fb_permalink=None, dry_run=True)

    _require_credentials(cfg)
    payload = _post_photo(
        page_id=cfg.fb_page_id,
        page_token=cfg.fb_page_access_token,
        image_path=image_path,
        caption=caption,
    )

    # Response shape: {"id": "<photo_id>", "post_id": "<page_id>_<post_id>"}.
    # We prefer post_id for the timeline link; fall back to id if absent.
    fb_post_id = payload.get("post_id") or payload.get("id")
    if not fb_post_id:
        raise FacebookPublishError(f"No post_id in response: {payload}")

    permalink = _build_permalink(cfg.fb_page_id, fb_post_id)
    log.info("fb_publish_success", fb_post_id=fb_post_id, permalink=permalink)
    _record_publish(operation="publish")
    return PublishResult(fb_post_id=fb_post_id, fb_permalink=permalink, dry_run=False)


def _build_permalink(page_id: str, fb_post_id: str) -> str:
    """Construct the canonical FB permalink for a post.

    fb_post_id format from /photos is "{page_id}_{post_id}". The public URL is
    facebook.com/{page_id}/posts/{post_id}.
    """
    if "_" in fb_post_id:
        _, post_part = fb_post_id.split("_", 1)
    else:
        post_part = fb_post_id
    return f"https://www.facebook.com/{page_id}/posts/{post_part}"


def _record_publish(operation: str) -> None:
    """Log a Graph API call to api_spend (free, but useful for audit trail)."""
    with db.session_scope() as s:
        s.add(
            db.ApiSpend(
                provider="meta",
                operation=operation,
                cost_usd=0.0,
            )
        )
