import pytest
from app.enums import ContentType
from app.connectors.instagram import mapper
from app.connectors.instagram.errors import InstagramInvalidResponseError


@pytest.mark.parametrize("raw,kind,capability", [
    ({"id":"1","media_type":"IMAGE"},ContentType.PHOTO,"FEED"),
    ({"id":"1","media_type":"CAROUSEL_ALBUM"},ContentType.CAROUSEL,"FEED"),
    ({"id":"1","media_type":"VIDEO"},ContentType.VIDEO,"VIDEO"),
    ({"id":"1","media_type":"VIDEO","media_product_type":"REELS"},ContentType.REEL,"REELS"),
])
def test_types_are_authoritative_and_nullable(raw,kind,capability):
    dto=mapper.media(raw)
    assert dto.content_type==kind
    assert dto.capability==capability
    assert dto.caption is None and dto.duration_seconds is None


@pytest.mark.parametrize("value", [0,None])
def test_zero_and_unavailable_are_distinct(value):
    assert mapper.insight_value({"data":[{"name":"views","period":"lifetime","values":[{"value":value}]}]},"views",period="lifetime")==value


def test_missing_metric_is_null():
    assert mapper.insight_value({"data":[]},"views",period="lifetime") is None


def test_does_not_alias_impressions_or_plays_to_views():
    payload={"data":[{"name":"impressions","period":"lifetime","values":[{"value":100}]}]}
    assert mapper.insight_value(payload,"views",period="lifetime") is None


def test_rejects_wrong_period_and_ambiguous_series():
    with pytest.raises(InstagramInvalidResponseError): mapper.insight_value({"data":[{"name":"views","period":"day","values":[{"value":1}]}]},"views",period="lifetime")
    with pytest.raises(InstagramInvalidResponseError): mapper.insight_value({"data":[{"name":"reach","period":"day","values":[{"value":1},{"value":2}]}]},"reach",period="day")


def test_sanitizes_embedded_credentials_without_changing_numbers():
    result=mapper.sanitize({"views":0,"access_token":"secret","paging":{"next":"https://graph.instagram.com/v26.0/123/media?after=cursor&access_token=secret"}},("secret",))
    assert result["views"]==0
    assert "secret" not in str(result) and "access_token" not in str(result)
    assert "after=cursor" in result["paging"]["next"]


def test_account_id_is_not_replaced_with_app_scoped_id():
    dto=mapper.account({"user_id":"123","id":"999","username":"demo.account"})
    assert dto.platform_account_id=="123"
    with pytest.raises(InstagramInvalidResponseError): mapper.account({"id":"999","username":"demo.account"})
