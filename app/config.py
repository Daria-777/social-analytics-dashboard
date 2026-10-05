from pathlib import Path
from typing import Literal
from pydantic import SecretStr, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)
    database_url: SecretStr = SecretStr("postgresql+psycopg://localhost/dash")
    internal_api_key: SecretStr | None = None
    display_timezone: str = "UTC"
    dash_domain: str | None = None

    instagram_client_id: str | None = None
    instagram_client_secret: SecretStr | None = None
    instagram_redirect_uri: str | None = None
    instagram_access_token: SecretStr | None = None
    instagram_granted_scopes: str = ""
    instagram_user_id: str | None = None
    instagram_api_version: str = "v26.0"
    instagram_expected_username: str = ""
    instagram_max_pages: int = Field(100, ge=1, le=10000)

    dashboard_session_hours: int = Field(8, ge=1, le=24)

    scheduler_enabled: bool = False
    scheduler_daily_hour_utc: int = Field(9, ge=0, le=23)
    scheduler_poll_seconds: int = Field(900, ge=60, le=86400)
    scheduler_max_attempts: int = Field(3, ge=1, le=10)
    scheduler_retry_minutes: int = Field(30, ge=1, le=1440)
    scheduler_max_lateness_hours: int = Field(2, ge=1, le=24)
    scheduler_max_jobs_per_tick: int = Field(2, ge=1, le=20)

    tiktok_oauth_mode: Literal["web", "desktop"] = "web"
    tiktok_client_key: str | None = None
    tiktok_client_secret: SecretStr | None = None
    tiktok_redirect_uri: str | None = None
    tiktok_access_token: SecretStr | None = None
    tiktok_refresh_token: SecretStr | None = None
    tiktok_open_id: str | None = None
    tiktok_scopes: str = "user.info.basic,user.info.profile,user.info.stats,video.list"
    tiktok_expected_username: str = ""
    tiktok_credential_store: Path | None = None
    tiktok_auto_refresh_enabled: bool = False
    tiktok_renewal_runtime: Literal["host","docker"] = "host"
    tiktok_refresh_skew_seconds: int = Field(300,ge=0,le=3600)

    @field_validator("tiktok_credential_store",mode="before")
    @classmethod
    def empty_store(cls,value):return None if value=="" else value

    tiktok_max_pages: int = Field(100, ge=1, le=10000)

    def require_tiktok_token(self):
        if not self.tiktok_access_token or not self.tiktok_access_token.get_secret_value().strip():
            raise ValueError("TIKTOK_ACCESS_TOKEN is required")
        return self.tiktok_access_token.get_secret_value()

    def require_tiktok_client(self):
        if not self.tiktok_client_key or not self.tiktok_client_secret or not self.tiktok_client_secret.get_secret_value().strip():
            raise ValueError("TikTok OAuth client credentials required")

    def require_tiktok_oauth(self):
        from urllib.parse import urlsplit
        import ipaddress
        if not self.tiktok_client_key or not self.tiktok_client_secret or not self.tiktok_client_secret.get_secret_value().strip() or not self.tiktok_redirect_uri:
            raise ValueError("TikTok client key, secret and HTTPS redirect URI are required")
        uri=urlsplit(self.tiktok_redirect_uri)
        if not uri.hostname or uri.username or uri.password or uri.query or uri.fragment or len(self.tiktok_redirect_uri)>=512 or any(c in self.tiktok_redirect_uri for c in "\\\r\n\t"):
            raise ValueError("Invalid TikTok redirect URI")
        if self.tiktok_oauth_mode == "desktop":
            # This helper implements plain HTTP loopback, not a TLS listener.
            if uri.scheme != "http" or uri.hostname not in ("localhost", "127.0.0.1") or not uri.port or not uri.path.startswith("/"):
                raise ValueError("Desktop callback requires HTTP loopback and an explicit port/path")
            return
        if self.tiktok_oauth_mode != "web" or uri.scheme != "https":
            raise ValueError("Web redirect must be a static public HTTPS URL")
        if uri.hostname=="localhost" or uri.hostname.endswith((".localhost",".local")):
            raise ValueError("TikTok redirect must be public")
        try: address=ipaddress.ip_address(uri.hostname)
        except ValueError: address=None
        if address is not None and not address.is_global:
            raise ValueError("TikTok redirect must be public")

    @field_validator("instagram_api_version")
    @classmethod
    def api_version(cls, value):
        import re
        if not re.fullmatch(r"v\d+\.\d+", value):
            raise ValueError("Invalid API version")
        return value

    def require_instagram_token(self):
        if not self.instagram_access_token or not self.instagram_access_token.get_secret_value():
            raise ValueError("INSTAGRAM_ACCESS_TOKEN is required")
        return self.instagram_access_token.get_secret_value()

    def require_instagram_oauth(self):
        from urllib.parse import urlsplit
        if not self.instagram_client_id or not self.instagram_client_secret or not self.instagram_redirect_uri:
            raise ValueError("Instagram App ID, Secret and HTTPS redirect URI are required")
        uri=urlsplit(self.instagram_redirect_uri)
        if uri.scheme != "https" or not uri.hostname or uri.username or uri.password or uri.fragment:
            raise ValueError("Instagram redirect URI must be a public HTTPS URL")
        if not self.instagram_client_id.isdigit():
            raise ValueError("Instagram App ID must be numeric")
        import ipaddress
        if uri.hostname in ("localhost",) or uri.hostname.endswith((".localhost", ".local")):
            raise ValueError("Instagram redirect requires a public HTTPS hostname")
        try:
            address=ipaddress.ip_address(uri.hostname)
        except ValueError:
            address=None
        if address is not None and not address.is_global:
            raise ValueError("Instagram redirect requires a public HTTPS hostname")
