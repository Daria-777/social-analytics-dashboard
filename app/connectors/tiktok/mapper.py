from datetime import datetime,timezone
from pydantic import ValidationError
from app.enums import ContentType
from app.preview import safe_preview_url
from app.connectors.instagram.schemas import MediaDTO
from .schemas import User,Video,AccountDTO
from .errors import TikTokInvalidResponseError


def account(payload):
    try: raw=User.model_validate(payload['data']['user'])
    except (ValidationError,KeyError,TypeError): raise TikTokInvalidResponseError('/v2/user/info/','normalize_user') from None
    return AccountDTO(platform_account_id=raw.open_id,username=raw.username,followers=raw.follower_count,following=raw.following_count,likes=raw.likes_count)


def video(payload):
    try:
        raw=Video.model_validate(payload)
        published=datetime.fromtimestamp(raw.create_time,timezone.utc) if raw.create_time is not None else None
    except (ValidationError,ValueError,OverflowError,OSError): raise TikTokInvalidResponseError('/v2/video/list/','normalize_video') from None
    dto=MediaDTO(preview_url=safe_preview_url(raw.cover_image_url),platform_content_id=raw.id,content_type=ContentType.VIDEO,published_at=published,caption=raw.video_description if raw.video_description is not None else raw.title,permalink=raw.share_url,capability='VIDEO')
    values={'views':raw.view_count,'likes':raw.like_count,'comments':raw.comment_count,'shares':raw.share_count}
    return dto,raw.duration,values
