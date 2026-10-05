import logging
import httpx
import pytest
from app.connectors.instagram.client import InstagramClient
from app.connectors.instagram.errors import (InstagramAuthError, InstagramPermissionError, InstagramRateLimitError, InstagramAPIError, InstagramInvalidResponseError)

TOKEN = "test-super-secret-token"


@pytest.mark.parametrize("status,code,error", [(401,190,InstagramAuthError),(400,190,InstagramAuthError),(403,10,InstagramPermissionError),(403,200,InstagramPermissionError),(429,4,InstagramRateLimitError),(500,2,InstagramAPIError),(200,190,InstagramAuthError)])
def test_structured_errors_without_secrets(status, code, error, caplog):
    caplog.set_level(logging.DEBUG)
    def handler(request):
        return httpx.Response(status, json={"error":{"code":code,"message":TOKEN}})
    with InstagramClient(TOKEN, "v26.0", transport=httpx.MockTransport(handler), max_retries=0) as client:
        with pytest.raises(error) as raised:
            client.get("me", operation="account", params={"fields":"user_id,username"})
    assert TOKEN not in str(raised.value)
    assert TOKEN not in caplog.text
    assert raised.value.meta_code == code


def test_malformed_response():
    with InstagramClient(TOKEN, "v26.0", transport=httpx.MockTransport(lambda r:httpx.Response(200,text="not json"))) as client:
        with pytest.raises(InstagramInvalidResponseError): client.get("me", operation="account")


def test_retry_after_and_bounded_backoff():
    calls=[]; waits=[]
    def handler(request):
        calls.append(request)
        if len(calls)<3: return httpx.Response(429, headers={"Retry-After":"2"},json={"error":{"code":4}})
        return httpx.Response(200,json={"user_id":"123","username":"demo.account"})
    with InstagramClient(TOKEN,"v26.0",transport=httpx.MockTransport(handler),sleep=waits.append) as client:
        assert client.get("me",operation="account")["user_id"] == "123"
    assert len(calls)==3
    assert waits==[2,2]
    assert all(TOKEN not in str(r.url) for r in calls)


def test_transport_failures_are_bounded():
    calls=[]
    def handler(request):
        calls.append(1); raise httpx.ReadTimeout(TOKEN,request=request)
    with InstagramClient(TOKEN,"v26.0",transport=httpx.MockTransport(handler),sleep=lambda _:None) as client:
        with pytest.raises(InstagramAPIError) as raised: client.get("me",operation="account")
    assert len(calls)==3
    assert TOKEN not in str(raised.value)


def test_client_refuses_social_write_actions():
    with InstagramClient(TOKEN,"v26.0",transport=httpx.MockTransport(lambda r:pytest.fail("Network must not be used"))) as client:
        with pytest.raises(ValueError):
            client.request("POST","https://graph.instagram.com/v26.0/123/media",endpoint="123/media",operation="forbidden")


def test_5xx_retries_then_succeeds():
    waits=[];calls=[]
    def handler(request):
        calls.append(1)
        return httpx.Response(500,text="temporary") if len(calls)<3 else httpx.Response(200,json={"ok":True})
    with InstagramClient(TOKEN,"v26.0",transport=httpx.MockTransport(handler),sleep=waits.append) as client:
        assert client.get("me",operation="account")["ok"]
    assert waits==[1,2]


def test_retry_after_longer_than_budget_is_not_ignored():
    waits=[]
    with InstagramClient(TOKEN,"v26.0",transport=httpx.MockTransport(lambda r:httpx.Response(429,headers={"Retry-After":"120"},json={"error":{"code":4}})),sleep=waits.append) as client:
        with pytest.raises(InstagramRateLimitError): client.get("me",operation="account")
    assert waits==[]
