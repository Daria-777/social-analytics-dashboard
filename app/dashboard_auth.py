"""Stateless owner session; cookie contains expiry/nonce/signature, never API keys."""
import hashlib
import hmac
import secrets
import time
from fastapi import HTTPException

COOKIE='dash_session'


def session_token(key,expires):
    value=f'{int(expires)}.{secrets.token_urlsafe(24)}'
    signature=hmac.new(key.encode(),('dashboard:v1:'+value).encode(),hashlib.sha256).hexdigest()
    return value+'.'+signature


def valid_session(token,key,*,now=None):
    if not token or len(token)>512: return False
    try:
        expires,nonce,signature=token.split('.')
        if not nonce or int(expires)<=(time.time() if now is None else now): return False
        expected=hmac.new(key.encode(),f'dashboard:v1:{expires}.{nonce}'.encode(),hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature,expected)
    except (ValueError,TypeError): return False


def same_origin(request):
    origin=request.headers.get('origin')
    expected=f'{request.url.scheme}://{request.url.netloc}'
    if origin!=expected: raise HTTPException(403,'Same-origin request required')
