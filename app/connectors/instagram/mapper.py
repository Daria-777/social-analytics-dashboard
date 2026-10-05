import math
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from pydantic import ValidationError
from app.enums import ContentType
from app.preview import safe_preview_url
from .schemas import RawAccount, RawMedia, AccountDTO, MediaDTO
from .errors import InstagramInvalidResponseError

# Source: official Media Insights reference. VIDEO without surface gets intersection.
COMMON = ("views", "reach", "likes", "comments", "saved", "shares")
CAPABILITIES = {
    "FEED": COMMON + ("profile_activity", "profile_visits", "follows"),
    "VIDEO": COMMON,
    "REELS": COMMON + ("ig_reels_avg_watch_time", "ig_reels_video_view_total_time"),
    "STORY": ("views", "reach", "shares", "profile_activity", "profile_visits", "follows"),
    "OTHER": (),
}
ACCOUNT_METRICS = ("views", "reach", "likes", "comments", "shares", "saves")
FIELDS = {"views":"views","reach":"reach","likes":"likes","comments":"comments","shares":"shares","saved":"saves","saves":"saves","profile_activity":"profile_activity","profile_visits":"profile_visits","follows":"followers_gained"}


def single_object(payload, endpoint):
    entries=payload.get("data")
    if entries is None: return payload
    if not isinstance(entries,list) or len(entries)!=1 or not isinstance(entries[0],dict):
        raise InstagramInvalidResponseError(endpoint,"normalize")
    return entries[0]


def account(payload):
    try: raw=RawAccount.model_validate(single_object(payload,"me"))
    except ValidationError: raise InstagramInvalidResponseError("me","normalize_account") from None
    return AccountDTO(platform_account_id=raw.user_id,username=raw.username,account_type=raw.account_type,followers=raw.followers_count,following=raw.follows_count)


def media(payload):
    try: raw=RawMedia.model_validate(payload)
    except ValidationError: raise InstagramInvalidResponseError("media","normalize_media") from None
    if raw.media_product_type=="REELS": kind,capability=ContentType.REEL,"REELS"
    elif raw.media_product_type=="STORY": kind,capability=ContentType.STORY,"STORY"
    elif raw.media_type=="CAROUSEL_ALBUM": kind,capability=ContentType.CAROUSEL,"FEED"
    elif raw.media_type=="IMAGE": kind,capability=ContentType.PHOTO,"FEED"
    elif raw.media_type=="VIDEO": kind,capability=ContentType.VIDEO,"FEED" if raw.media_product_type=="FEED" else "VIDEO"
    else: kind,capability=ContentType.OTHER,"OTHER"
    image = payload
    if raw.media_type == "CAROUSEL_ALBUM":
        children = (raw.children or {}).get("data", [])
        image = children[0] if isinstance(children, list) and children and isinstance(children[0], dict) else {}
    preview = image.get("thumbnail_url") if image.get("media_type") == "VIDEO" else image.get("media_url") if image.get("media_type") == "IMAGE" else None
    return MediaDTO(preview_url=safe_preview_url(preview),platform_content_id=raw.id,content_type=kind,capability=capability,published_at=raw.timestamp,caption=raw.caption,permalink=raw.permalink)


def insight_value(payload,metric,*,period):
    data=payload.get("data")
    if not isinstance(data,list): raise InstagramInvalidResponseError("insights","normalize_insight")
    matching=[item for item in data if isinstance(item,dict) and item.get("name")==metric]
    if not matching: return None
    if len(matching)!=1 or matching[0].get("period")!=period:
        raise InstagramInvalidResponseError("insights","normalize_insight")
    item=matching[0]
    if isinstance(item.get("total_value"),dict):
        value=item["total_value"].get("value")
    else:
        values=item.get("values",[])
        if not isinstance(values,list) or len(values)>1 or any(not isinstance(v,dict) for v in values):
            raise InstagramInvalidResponseError("insights","normalize_insight")
        value=values[0].get("value") if values else None
    if value is None: return None
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0 or value>9223372036854775807:
        raise InstagramInvalidResponseError("insights","normalize_insight")
    if metric.startswith("ig_reels_"): return value  # raw only: units unverified.
    if not isinstance(value,int): raise InstagramInvalidResponseError("insights","normalize_insight")
    return value


def sanitize(payload,secrets):
    """Keep analytics response structure, removing credentials embedded in paging URLs."""
    if isinstance(payload,dict):
        return {k:sanitize(v,secrets) for k,v in payload.items() if k.lower() not in {"access_token","client_secret","authorization","code"}}
    if isinstance(payload,list): return [sanitize(value,secrets) for value in payload]
    if isinstance(payload,str):
        if payload.startswith("https://"):
            url=urlsplit(payload)
            query=[(k,v) for k,v in parse_qsl(url.query,keep_blank_values=True) if k.lower() not in {"access_token","client_secret","code"}]
            payload=urlunsplit((url.scheme,url.netloc,url.path,urlencode(query),url.fragment))
        for secret in secrets:
            if secret: payload=payload.replace(secret,"[REDACTED]")
    return payload
