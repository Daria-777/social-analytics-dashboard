"""Meta Business Login flow. OAuth response never enters analytics persistence."""
from secrets import token_urlsafe, compare_digest
import time
from urllib.parse import urlencode
from pydantic import ValidationError
from .client import InstagramClient
from .schemas import Token
from .errors import InstagramInvalidResponseError, InstagramPermissionError

SCOPES = ("instagram_business_basic", "instagram_business_manage_insights")


class OAuthState:
    def __init__(self, *, ttl=600):
        self.value=token_urlsafe(32); self.deadline=time.monotonic()+ttl; self.used=False
    def consume(self, received):
        if self.used or time.monotonic()>self.deadline or not compare_digest(self.value.encode(),received.encode()):
            raise ValueError("Invalid, expired or reused OAuth state")
        self.used=True


class InstagramAuth:
    def __init__(self,settings,*,transport=None):
        self.settings=settings
        self.granted_scopes=None
        self.client=InstagramClient("",settings.instagram_api_version,transport=transport,secrets=(settings.instagram_client_secret.get_secret_value() if settings.instagram_client_secret else "",))
    def __enter__(self): return self
    def __exit__(self,*_): self.client.close()

    def authorization_url(self,state):
        self.settings.require_instagram_oauth()
        return "https://www.instagram.com/oauth/authorize?"+urlencode({"client_id":self.settings.instagram_client_id,"redirect_uri":self.settings.instagram_redirect_uri,"response_type":"code","scope":",".join(SCOPES),"state":state.value,"enable_fb_login":"false"})

    def exchange_code(self,code):
        self.settings.require_instagram_oauth()
        # Add code/short token to the same active logging filter before any request.
        self.client.filter.secrets += (code,)
        payload=self.client.request("POST","https://api.instagram.com/oauth/access_token",endpoint="oauth/access_token",operation="oauth_code_exchange",data={"client_id":self.settings.instagram_client_id,"client_secret":self.settings.instagram_client_secret.get_secret_value(),"grant_type":"authorization_code","redirect_uri":self.settings.instagram_redirect_uri,"code":code},retry=False)
        entries=payload.get("data")
        if entries is not None:
            if not isinstance(entries,list) or len(entries)!=1 or not isinstance(entries[0],dict) or "access_token" in payload:
                raise InstagramInvalidResponseError("oauth/access_token","oauth_code_exchange")
            payload=entries[0]
        token=payload.get("access_token")
        if not isinstance(token,str) or not token:
            raise InstagramInvalidResponseError("oauth/access_token","oauth_code_exchange")
        permissions=payload.get("permissions")
        if isinstance(permissions,str): permissions=permissions.split(",")
        if not isinstance(permissions,list) or not all(isinstance(permission,str) for permission in permissions) or set(permissions)!=set(SCOPES):
            raise InstagramPermissionError("oauth/access_token","oauth_code_exchange")
        self.granted_scopes=tuple(sorted(set(permissions)))
        self.client.filter.secrets += (token,)
        result=self.client.request("GET","https://graph.instagram.com/access_token",endpoint="access_token",operation="oauth_long_exchange",params={"grant_type":"ig_exchange_token","client_secret":self.settings.instagram_client_secret.get_secret_value(),"access_token":token},retry=False)
        return self._token(result,"access_token")

    def refresh(self,token):
        self.client.filter.secrets += (token,)
        result=self.client.request("GET","https://graph.instagram.com/refresh_access_token",endpoint="refresh_access_token",operation="oauth_refresh",params={"grant_type":"ig_refresh_token","access_token":token},retry=False)
        return self._token(result,"refresh_access_token")

    def _token(self,payload,endpoint):
        try: return Token.model_validate(payload)
        except ValidationError: raise InstagramInvalidResponseError(endpoint,"oauth_token_validation") from None
