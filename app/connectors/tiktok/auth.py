import hashlib
import secrets
import time
from urllib.parse import urlencode
from pydantic import SecretStr,ValidationError
from app.connectors.instagram.auth import OAuthState
from .client import TikTokClient
from .schemas import Token
from .errors import TikTokInvalidResponseError,TikTokPermissionError,TikTokIdentityError

REQUIRED_SCOPES={'user.info.basic','user.info.profile','video.list'}
SCOPES=REQUIRED_SCOPES | {'user.info.stats'}


def validate_grant(scope, *, endpoint='/v2/oauth/token/'):
    """Exact comma-separated names; never trim, drop or silently deduplicate grants."""
    if not isinstance(scope,str):raise TikTokInvalidResponseError(endpoint,'oauth_grant_validation')
    entries=scope.split(',')
    if any(not entry or entry!=entry.strip() for entry in entries) or len(entries)!=len(set(entries)):
        raise TikTokInvalidResponseError(endpoint,'oauth_grant_validation')
    granted=set(entries)
    if not REQUIRED_SCOPES.issubset(granted) or not granted.issubset(SCOPES):
        raise TikTokPermissionError(endpoint,'read_only_grant_validation')
    return scope


class DesktopPKCE:
    """Fresh proof per authorization; TikTok Desktop uses SHA256 hex, not base64url."""
    def __init__(self):
        self.verifier=SecretStr(secrets.token_urlsafe(64))
        self.used=False

    @property
    def challenge(self):
        if self.used: raise ValueError('Desktop proof was already used')
        return hashlib.sha256(self.verifier.get_secret_value().encode()).hexdigest()

    def consume(self):
        if self.used: raise ValueError('Desktop proof was already used')
        self.used=True
        return self.verifier.get_secret_value()


class TikTokAuth:
    def __init__(self,settings,*,transport=None):
        self.settings=settings
        self._desktop_context=None
        self.client=TikTokClient('',transport=transport,secrets=(settings.tiktok_client_secret.get_secret_value() if settings.tiktok_client_secret else '',))
    def __enter__(self): return self
    def __exit__(self,*_): self.client.close()
    def authorization_url(self,state,*,pkce=None):
        self.settings.require_tiktok_oauth()
        params={'client_key':self.settings.tiktok_client_key,'redirect_uri':self.settings.tiktok_redirect_uri,'response_type':'code','scope':','.join(sorted(SCOPES)),'state':state.value}
        if self.settings.tiktok_oauth_mode=='desktop':
            if not isinstance(pkce,DesktopPKCE) or state.used or self._desktop_context is not None:
                raise ValueError('Fresh desktop authorization proof/state required')
            params.update(code_challenge=pkce.challenge,code_challenge_method='S256')
            self._desktop_context=(state,pkce,self.settings.tiktok_redirect_uri)
        elif pkce is not None:
            raise ValueError('Desktop proof cannot be used in Web mode')
        return 'https://www.tiktok.com/v2/auth/authorize/?'+urlencode(params)

    def exchange_code(self,code,*,pkce=None):
        self.settings.require_tiktok_oauth()
        if not isinstance(code,str) or not code.strip(): raise ValueError('Authorization code required')
        data={'client_key':self.settings.tiktok_client_key,'client_secret':self.settings.tiktok_client_secret.get_secret_value(),'code':code,'grant_type':'authorization_code','redirect_uri':self.settings.tiktok_redirect_uri}
        if self.settings.tiktok_oauth_mode=='desktop':
            if self._desktop_context is None: raise ValueError('Desktop authorization not initialized')
            state,proof,uri=self._desktop_context
            if pkce is not proof or uri!=self.settings.tiktok_redirect_uri or not state.used or time.monotonic()>state.deadline:
                raise ValueError('Desktop authorization context does not match')
            data['code_verifier']=proof.consume()
        elif pkce is not None or self._desktop_context is not None:
            raise ValueError('Desktop proof cannot be used in Web mode')
        return self._token(self.client.oauth(data))
    def refresh(self,refresh_token):
        self.settings.require_tiktok_client()
        return self._token(self.client.oauth({'client_key':self.settings.tiktok_client_key,'client_secret':self.settings.tiktok_client_secret.get_secret_value(),'refresh_token':refresh_token,'grant_type':'refresh_token'}))
    def _token(self,payload):
        try: token=Token.model_validate(payload)
        except ValidationError: raise TikTokInvalidResponseError('/v2/oauth/token/','oauth_token_validation') from None
        validate_grant(token.scope)
        if self.settings.tiktok_open_id and token.open_id!=self.settings.tiktok_open_id:
            raise TikTokIdentityError('/v2/oauth/token/','configured_identity_mismatch')
        return token
