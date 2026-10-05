"""Refresh expiring TikTok cover metadata; never create analytics snapshots."""
from threading import Lock
from time import time, monotonic
from uuid import UUID
from urllib.parse import urlsplit, parse_qsl, unquote
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from app.api import authenticate, DB, require
from app.models import Content, SocialAccount
from app.enums import Platform
from app.config import Settings
from app.preview import safe_preview_url
from app.connectors.tiktok.credentials import resolve_settings
from app.connectors.tiktok.client import TikTokClient
from app.connectors.tiktok.errors import TikTokError

router = APIRouter(dependencies=[Depends(authenticate)])
_lock = Lock()
_fresh = {}  # URL verified by this process, with a maximum six-hour lifetime.
_cooldown = {}  # Only known DB content IDs; brief negative cache avoids failed request loops.


def current_cover(value, secrets=()):
    value = safe_preview_url(value)
    if not value or any(secret and secret in unquote(value) for secret in secrets): return None
    try:
        expires = int(dict(parse_qsl(urlsplit(value).query)).get('x-expires', '0'))
    except (ValueError, OverflowError): return None
    return value if expires > time() + 60 else None


@router.get('/content/{content_id}/preview', include_in_schema=False)
def tiktok_preview(content_id: UUID, db: DB):
    content = require(db, Content, content_id)
    if content.platform != Platform.TIKTOK: raise HTTPException(404, 'No TikTok cover')
    with _lock:
        db.refresh(content)  # A concurrent request may already have refreshed the URL.
        now = monotonic()
        for key, expiry in list(_cooldown.items()):
            if expiry <= now: _cooldown.pop(key, None)
        if content_id in _cooldown: raise HTTPException(503, 'Cover temporarily unavailable')
        try:
            settings = resolve_settings(Settings(), allow_refresh=True)
            account = require(db, SocialAccount, content.account_id)
            if not settings.tiktok_open_id or account.platform_account_id != settings.tiktok_open_id:
                raise HTTPException(404, 'No cover for this account')
            secrets = tuple(v.get_secret_value() for v in (settings.tiktok_access_token, settings.tiktok_refresh_token, settings.tiktok_client_secret) if v)
            now = monotonic()
            for key, (_, expiry) in list(_fresh.items()):
                if expiry <= now: _fresh.pop(key, None)
            url = current_cover(content.preview_url, secrets)
            if url and _fresh.get(content_id, (None, 0))[0] == url:
                return RedirectResponse(url)
            _cooldown[content_id] = now + 300
            token = settings.require_tiktok_token()
            with TikTokClient(token, secrets=secrets, max_retries=0) as client:
                payload = client.cover(content.platform_content_id)
            videos = payload['data'].get('videos')
            if not isinstance(videos, list) or len(videos) != 1 or not isinstance(videos[0], dict) or videos[0].get('id') != content.platform_content_id:
                raise HTTPException(502, 'Invalid cover response')
            url = current_cover(videos[0].get('cover_image_url'), secrets)
            if not url: raise HTTPException(404, 'Cover unavailable')
            content.preview_url = url
            db.commit()
            _cooldown.pop(content_id, None)
            _fresh[content_id] = (url, monotonic() + 6 * 3600 - 60)
            return RedirectResponse(url)
        except (TikTokError, ValueError):
            _cooldown[content_id] = monotonic() + 300
            raise HTTPException(503, 'Cover temporarily unavailable') from None
