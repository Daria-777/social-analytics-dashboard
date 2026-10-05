import httpx
import pytest
from app.connectors.tiktok.client import TikTokClient
from app.connectors.tiktok.errors import TikTokAuthError,TikTokPermissionError,TikTokRateLimitError,TikTokInvalidResponseError,TikTokAPIError


def test_list_post_is_read_only_retry_and_redacted(caplog):
    calls=[];delays=[]
    def response(request):
        calls.append(request)
        return httpx.Response(429,headers={"Retry-After":"3"},json={"error":{"code":"rate_limit_exceeded","message":"test-secret"}}) if len(calls)==1 else httpx.Response(200,json={"data":{"videos":[],"has_more":False},"error":{"code":"ok"}})
    with TikTokClient('test-secret',transport=httpx.MockTransport(response),sleep=delays.append) as client:
        assert client.videos(None)['data']['videos']==[]
    assert len(calls)==2 and delays==[3]
    assert all(r.method=='POST' and r.url.path=='/v2/video/list/' for r in calls)
    assert 'test-secret' not in caplog.text


@pytest.mark.parametrize('status,code,kind',[(401,'access_token_invalid',TikTokAuthError),(401,'scope_not_authorized',TikTokPermissionError),(400,'scope_permission_missed',TikTokPermissionError),(429,'rate_limit_exceeded',TikTokRateLimitError),(500,'internal_error',TikTokAPIError),(200,'invalid_params',TikTokAPIError)])
def test_safe_structured_errors(status,code,kind):
    with TikTokClient('test-secret',transport=httpx.MockTransport(lambda r:httpx.Response(status,json={'error':{'code':code,'message':'test-secret'}})),max_retries=0) as client:
        with pytest.raises(kind) as error: client.user()
    assert error.value.code==code and 'test-secret' not in str(error.value)


def test_unbounded_retry_after_aborts_without_sleep():
    calls=[]
    with TikTokClient('x',transport=httpx.MockTransport(lambda r:httpx.Response(429,headers={'Retry-After':'300'},json={'error':{'code':'rate_limit_exceeded'}})),sleep=calls.append) as client:
        with pytest.raises(TikTokRateLimitError): client.user()
    assert calls==[]


def test_malformed_response_and_no_social_write_endpoints():
    with TikTokClient('x',transport=httpx.MockTransport(lambda r:httpx.Response(200,text='bad-json'))) as client:
        with pytest.raises(TikTokInvalidResponseError): client.user()
        with pytest.raises(ValueError): client.request('POST','/v2/post/publish/')


def test_oauth_does_not_retry_or_leak_payload():
    calls=[]
    def response(r): calls.append(r);return httpx.Response(500,json={'error':'invalid_client','error_description':'secret-value'})
    with TikTokClient('',transport=httpx.MockTransport(response)) as client:
        with pytest.raises(TikTokAPIError) as error: client.oauth({'client_secret':'secret-value'})
    assert len(calls)==1 and 'secret-value' not in str(error.value)
