import json
import time
from uuid import UUID
import httpx
import pytest
from sqlalchemy import select, func
from app.models import Content, ContentSnapshot, CollectorRun
from app.database import get_session
from app import content_preview as module
from app.connectors.tiktok.client import TikTokClient
from app.preview import safe_preview_url

URL = 'https://p16-common-sign.tiktokcdn-eu.com/a.image?refresh_token=ab12cd34&x-expires=' + str(int(time.time()) + 21600) + '&x-signature=a%2Fb'


@pytest.fixture
def cover_content(client, monkeypatch):
    module._cooldown.clear(); module._fresh.clear()
    monkeypatch.setenv('TIKTOK_ACCESS_TOKEN', 'test-private-access')
    monkeypatch.setenv('TIKTOK_REFRESH_TOKEN', 'rft.test-private-refresh')
    monkeypatch.setenv('TIKTOK_OPEN_ID', 'test-cover-owner')
    account = client.post('/accounts', json={'platform':'tiktok', 'username':'fixture', 'platform_account_id':'test-cover-owner'}).json()
    content = client.post('/content', json={'account_id':account['id'], 'platform':'tiktok', 'platform_content_id':'123', 'content_type':'video'}).json()
    yield content
    module._cooldown.clear(); module._fresh.clear()


def mock_provider(monkeypatch, videos=None, status=200):
    calls=[]
    def response(request):
        calls.append(request)
        assert request.url.path == '/v2/video/query/' and request.method == 'POST'
        assert request.url.params['fields'] == 'id,cover_image_url'
        assert json.loads(request.content) == {'filters':{'video_ids':['123']}}
        return httpx.Response(status, json={'data':{'videos':videos if videos is not None else [{'id':'123', 'cover_image_url':URL}]}, 'error':{'code':'ok' if status == 200 else 'access_token_invalid', 'message':'rft.test-private-refresh'}})
    monkeypatch.setattr(module, 'TikTokClient', lambda token, **kw:TikTokClient(token, transport=httpx.MockTransport(response), **kw))
    return calls


def saved(client, content, url):
    generator=client.app.dependency_overrides[get_session]()
    db=next(generator)
    try:
        row=db.get(Content, UUID(content['id']));row.preview_url=url;db.commit()
    finally: generator.close()


def test_signed_cdn_marker_is_preserved_and_oauth_is_blocked():
    assert safe_preview_url(URL) == URL
    for value in ('rft.secret', 'secret', 'ABCDEF12', 'ab12cd34&refresh_token=ab12cd34'):
        assert safe_preview_url(URL.replace('ab12cd34', value)) is None
    assert safe_preview_url(URL.replace('tiktokcdn-eu.com','cdninstagram.com')) is None
    assert safe_preview_url(URL.replace('tiktokcdn-eu.com','tiktokcdn-eu.com.evil.example')) is None
    assert safe_preview_url(URL + '&access_token=secret') is None
    assert safe_preview_url(URL.replace('x-signature=','other=')) is None


def test_missing_cover_refreshes_once_and_does_not_create_snapshots(client, cover_content, monkeypatch):
    calls=mock_provider(monkeypatch)
    path=f"/content/{cover_content['id']}/preview"
    for _ in range(2):
        response=client.get(path, follow_redirects=False)
        assert response.status_code==307 and response.headers['location']==URL
        assert response.headers['Cache-Control']=='no-store'
    assert len(calls)==1
    assert client.get('/content').json()[0]['preview_url']==URL
    generator=client.app.dependency_overrides[get_session]();db=next(generator)
    try:
        assert db.scalar(select(func.count()).select_from(ContentSnapshot))==0
        assert db.scalar(select(func.count()).select_from(CollectorRun))==0
    finally: generator.close()


def test_expired_cover_is_refreshed_without_reusing_old_signature(client, cover_content, monkeypatch):
    saved(client, cover_content, URL.replace(URL.split('x-expires=')[1].split('&')[0], '1'))
    calls=mock_provider(monkeypatch)
    response=client.get(f"/content/{cover_content['id']}/preview", follow_redirects=False)
    assert response.status_code==307 and response.headers['location']==URL and len(calls)==1


@pytest.mark.parametrize('videos', [[], [{'id':'999','cover_image_url':URL}], [{'id':'123','cover_image_url':URL+'%20test-private-access'}], [{'id':'123','cover_image_url':'https://evil.example/a'}]])
def test_invalid_or_secret_cover_is_never_redirected(client, cover_content, monkeypatch, videos):
    calls=mock_provider(monkeypatch, videos)
    response=client.get(f"/content/{cover_content['id']}/preview", follow_redirects=False)
    assert response.status_code in (404,502) and 'location' not in response.headers
    assert 'test-private-access' not in response.text
    assert client.get('/content').json()[0]['preview_url'] is None
    assert len(calls)==1


def test_failed_refresh_is_safe_and_cooled_down(client, cover_content, monkeypatch, caplog):
    calls=mock_provider(monkeypatch, status=401)
    for _ in range(2):
        response=client.get(f"/content/{cover_content['id']}/preview", follow_redirects=False)
        assert response.status_code==503 and 'rft.test-private-refresh' not in response.text
    assert len(calls)==1 and 'rft.test-private-refresh' not in caplog.text


def test_preview_requires_login_and_owner_before_provider_call(client, cover_content, monkeypatch):
    calls=mock_provider(monkeypatch)
    client.headers.pop('X-API-Key')
    assert client.get(f"/content/{cover_content['id']}/preview", follow_redirects=False).status_code==401
    client.headers['X-API-Key']='test-only-key'
    monkeypatch.setenv('TIKTOK_OPEN_ID','another-owner')
    assert client.get(f"/content/{cover_content['id']}/preview", follow_redirects=False).status_code==404
    assert calls==[]


def test_cover_requeries_after_six_hours_even_if_cdn_expiry_is_later(client, cover_content, monkeypatch):
    clock=[100.0]
    monkeypatch.setattr(module,'monotonic',lambda:clock[0])
    calls=mock_provider(monkeypatch)
    path=f"/content/{cover_content['id']}/preview"
    assert client.get(path,follow_redirects=False).status_code==307
    clock[0]+=6*3600
    assert client.get(path,follow_redirects=False).status_code==307
    assert len(calls)==2
