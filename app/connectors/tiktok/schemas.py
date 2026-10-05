from pydantic import BaseModel,ConfigDict,Field,SecretStr,field_validator
from app.schemas import Count
from app.connectors.instagram.schemas import Token as BearerToken


class Token(BearerToken):
    refresh_token: SecretStr
    refresh_expires_in: int=Field(gt=0)
    open_id: str=Field(min_length=1)
    scope: str

    @field_validator('refresh_token')
    @classmethod
    def refresh_nonempty(cls,value):
        if not value.get_secret_value().strip(): raise ValueError('Refresh token must be nonempty')
        return value


class User(BaseModel):
    model_config=ConfigDict(extra='allow')
    open_id: str=Field(min_length=1)
    username: str=Field(min_length=1)
    follower_count: Count | None=None
    following_count: Count | None=None
    likes_count: Count | None=None


class Video(BaseModel):
    model_config=ConfigDict(extra='allow')
    id: str=Field(pattern=r'^\d+$')
    create_time: Count | None=None
    duration: Count | None=None
    video_description: str | None=None
    title: str | None=None
    share_url: str | None=None
    cover_image_url: str | None=None
    view_count: Count | None=None
    like_count: Count | None=None
    comment_count: Count | None=None
    share_count: Count | None=None


class AccountDTO(BaseModel):
    platform_account_id: str=Field(min_length=1)
    username: str=Field(min_length=1)
    account_type: str | None=None
    followers: Count | None=None
    following: Count | None=None
    likes: Count | None=None
