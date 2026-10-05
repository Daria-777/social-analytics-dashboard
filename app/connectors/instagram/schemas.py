from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from app.schemas import Count, UTCStamp
from app.enums import ContentType

Identifier = Annotated[str, Field(pattern=r"^\d+$")]


class RawAccount(BaseModel):
    model_config = ConfigDict(extra="allow")
    user_id: Identifier
    username: str = Field(min_length=1)
    account_type: str | None = None
    followers_count: Count | None = None
    follows_count: Count | None = None


class RawMedia(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: Identifier
    media_type: str
    media_product_type: str | None = None
    timestamp: UTCStamp | None = None
    caption: str | None = None
    permalink: str | None = None
    media_url: str | None = None
    thumbnail_url: str | None = None
    children: dict | None = None


class AccountDTO(BaseModel):
    platform_account_id: Identifier
    username: str
    account_type: str | None = None
    followers: Count | None = None
    following: Count | None = None


class MediaDTO(BaseModel):
    platform_content_id: Identifier
    content_type: ContentType
    published_at: UTCStamp | None = None
    caption: str | None = None
    permalink: str | None = None
    preview_url: str | None = None
    duration_seconds: None = None
    capability: str


class Token(BaseModel):
    access_token: SecretStr
    expires_in: int = Field(gt=0)
    token_type: Literal["bearer"] = "bearer"

    @field_validator("access_token")
    @classmethod
    def nonempty_token(cls, value):
        if not value.get_secret_value().strip():
            raise ValueError("OAuth token must be nonempty")
        return value

    @field_validator("token_type", mode="before")
    @classmethod
    def normalize_type(cls, value):
        return value.lower() if isinstance(value, str) else value
