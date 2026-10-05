from uuid import uuid4
import httpx
import pytest
from sqlalchemy import select
from tests.test_instagram_service import db,count
from app.config import Settings
from app.models import SocialAccount,Content,AccountSnapshot,ContentSnapshot,CollectorRun
from app.connectors.tiktok.client import TikTokClient
from app.connectors.tiktok.service import TikTokCollector


def settings(): return Settings(_env_file=None,tiktok_access_token='test-tiktok-token')


def handler(request):
    if request.url.path.endswith('/user/info/'):
        user={'open_id':'test-open','username':'demo.account','follower_count':0,'following_count':2,'likes_count':3}
        return httpx.Response(200,json={'data':{'user':user},'error':{'code':'ok'}})
    import json
    cursor=json.loads(request.content).get('cursor')
    video={'id':'2' if cursor else '1','create_time':1790852400,'duration':20,'title':'test-only','view_count':0,'like_count':0,'comment_count':1,'share_count':None}
    return httpx.Response(200,json={'data':{'videos':[video],'cursor':100 if not cursor else 200,'has_more':not bool(cursor)},'error':{'code':'ok'}})


def collector(db,responses=handler):
    return TikTokCollector(settings(),db,TikTokClient('test-tiktok-token',transport=httpx.MockTransport(responses),max_retries=0))


def test_collection_public_counters_nulls_raw_and_idempotency(db):
    worker=collector(db);job=uuid4()
    assert worker.collect(run_id=job)['status']=='success'
    account=db.scalar(select(SocialAccount));assert account.platform.value=='tiktok' and account.platform_account_id=='test-open'
    current=db.scalar(select(AccountSnapshot));assert current.followers==0 and current.following==2 and current.views is None
    content=db.scalar(select(Content));assert content.duration_seconds==20
    snapshot=db.scalar(select(ContentSnapshot));assert snapshot.views==0 and snapshot.unique_viewers is None and snapshot.watch_time_avg_seconds is None and snapshot.shares is None
    assert snapshot.source.value=='tiktok_api' and snapshot.metric_scope=='lifetime'
    assert 'test-tiktok-token' not in str(snapshot.raw_payload)
    worker.collect(run_id=job);assert count(db,ContentSnapshot)==2
    worker.collect(run_id=uuid4());assert count(db,ContentSnapshot)==4 and count(db,AccountSnapshot)==2
    worker.client.close()


def test_partial_page_retry_keeps_completed_snapshots(db):
    failure=True
    def responses(request):
        if failure and request.url.path.endswith('/video/list/') and b'cursor' in request.content:
            return httpx.Response(500,json={'error':{'code':'internal_error','message':'test-tiktok-token'}})
        return handler(request)
    worker=collector(db,responses);job=uuid4()
    assert worker.collect(run_id=job)['status']=='partial'
    original=db.scalar(select(ContentSnapshot)).id
    failure=False
    assert worker.collect(run_id=job)['status']=='success'
    assert count(db,ContentSnapshot)==2 and db.get(ContentSnapshot,original).views==0
    assert count(db,CollectorRun)==1
    worker.client.close()


def test_optional_stats_permission_and_wrong_identity(db):
    def responses(request):
        if 'follower_count' in request.url.params.get('fields',''):
            return httpx.Response(401,json={'error':{'code':'scope_not_authorized'}})
        return handler(request)
    worker=collector(db,responses)
    assert worker.collect()['status']=='partial'
    assert db.scalar(select(AccountSnapshot)).followers is None
    worker.settings.tiktok_open_id='wrong'
    result=worker.collect()
    assert result['status']=='failed' and count(db,ContentSnapshot)==2
    worker.client.close()


def test_dry_run_never_uses_db():
    class Forbidden:
        def __getattribute__(self,name): raise AssertionError('Dry run used DB')
    worker=collector(Forbidden());result=worker.collect(dry_run=True)
    assert result['status']=='success' and result['new_media'] is None and result['media_discovered']==2
    worker.client.close()


def test_invalid_video_does_not_discard_valid_video(db):
    def responses(request):
        payload=handler(request).json()
        if request.url.path.endswith('/video/list/'):
            payload['data']['videos'].append({'id':'bad','view_count':-1})
        return httpx.Response(200,json=payload)
    worker=collector(db,responses);result=worker.collect()
    assert result['status']=='partial' and count(db,ContentSnapshot)==2
    worker.client.close()


def test_repeated_cursor_is_partial_and_no_duplicate_video(db):
    def responses(request):
        payload=handler(request).json()
        if request.url.path.endswith('/video/list/'):
            payload['data']['has_more']=True;payload['data']['cursor']=100
            payload['data']['videos'][0]['id']='1'
        return httpx.Response(200,json=payload)
    worker=collector(db,responses);result=worker.collect()
    assert result['status']=='partial' and count(db,ContentSnapshot)==1
    assert any(f['error_type']=='TikTokPaginationError' for f in result['failure_details'])
    worker.client.close()
