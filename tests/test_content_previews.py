from uuid import uuid4
import httpx
import pytest
from sqlalchemy import select
from app.models import Content, ContentSnapshot
from app.connectors.instagram import mapper
from app.connectors.tiktok.mapper import video
from tests.test_instagram_service import db, collector, handler


@pytest.mark.parametrize('raw,expected', [
    ({'media_type':'IMAGE','media_url':'https://s.cdninstagram.com/photo.jpg'}, 'https://s.cdninstagram.com/photo.jpg'),
    ({'media_type':'VIDEO','media_url':'https://s.cdninstagram.com/video.mp4','thumbnail_url':'https://s.cdninstagram.com/cover.jpg'}, 'https://s.cdninstagram.com/cover.jpg'),
    ({'media_type':'VIDEO','media_url':'https://s.cdninstagram.com/video.mp4'}, None),
    ({'media_type':'CAROUSEL_ALBUM','children':{'data':[{'media_type':'IMAGE','media_url':'https://s.cdninstagram.com/first.jpg'}]}}, 'https://s.cdninstagram.com/first.jpg'),
    ({'media_type':'IMAGE'}, None),
    ({'media_type':'IMAGE','media_url':'https://s.cdninstagram.com/a?access_token=secret'}, None),
    ({'media_type':'IMAGE','media_url':'javascript:alert(1)'}, None),
    ({'media_type':'IMAGE','media_url':'https://cdninstagram.com.evil.example/a'}, None),
])
def test_instagram_preview_is_image_only_and_optional(raw, expected):
    assert mapper.media({'id':'1', **raw}).preview_url == expected


def test_tiktok_signed_cover_preserved():
    url='https://p16.tiktokcdn.com/a.jpg?sign=a%2Fb&x=a%20b'
    dto,_,_=video({'id':'1','cover_image_url':url})
    assert dto.preview_url == url
    assert video({'id':'1'})[0].preview_url is None


def test_collection_updates_preview_without_rewriting_snapshots(db):
    url='https://s.cdninstagram.com/first.jpg'
    def response(request):
        if request.url.path.endswith('/media'):
            assert 'thumbnail_url' in request.url.params['fields']
            return httpx.Response(200,json={'data':[{'id':'1','media_type':'IMAGE','media_url':url}]})
        return handler(request)
    worker=collector(db, response)
    try:
        worker.collect(run_id=uuid4())
        row=db.scalar(select(Content)); snapshot=db.scalar(select(ContentSnapshot))
        original=(snapshot.id, snapshot.raw_payload)
        assert row.preview_url == url
        url='https://s.cdninstagram.com/second.jpg'
        worker.collect(run_id=uuid4())
        assert db.get(Content,row.id).preview_url == url
        assert db.get(ContentSnapshot,original[0]).raw_payload == original[1]
        url=None
        worker.collect(run_id=uuid4())
        assert db.get(Content,row.id).preview_url == 'https://s.cdninstagram.com/second.jpg'
    finally:
        worker.client.close()


@pytest.mark.parametrize('url', ['https://p16.tiktokcdn.com/cover.jpg?sign=a%2Fb&x=a%20b', 'https://p16-common-sign.tiktokcdn-eu.com/a.image?refresh_token=ab12cd34&x-expires=4000000000&x-signature=a%2Fb'])
def test_tiktok_collection_requests_and_persists_cover(db, url):
    from tests.test_tiktok_service import collector as tiktok_collector, handler as tiktok_handler
    def response(request):
        result=tiktok_handler(request)
        if request.url.path.endswith('/video/list/'):
            assert 'cover_image_url' in request.url.params['fields']
            payload=result.json()
            payload['data']['videos'][0]['cover_image_url']=url
            return httpx.Response(200,json=payload)
        return result
    worker=tiktok_collector(db,response)
    try:
        assert worker.collect()['status']=='success'
        assert all(row.preview_url==url for row in db.scalars(select(Content)))
    finally:
        worker.client.close()


@pytest.mark.parametrize('url', ['https://user:password@s.cdninstagram.com/a', 'http://s.cdninstagram.com/a', 'https://s.cdninstagram.com:8080/a', 'https://127.0.0.1/a', 'https://s.cdninstagram.com/a?refresh_token=x'])
def test_unsafe_preview_is_unavailable(url):
    from app.preview import safe_preview_url
    assert safe_preview_url(url) is None
