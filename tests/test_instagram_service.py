from uuid import uuid4
import httpx
import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from app.config import Settings
from app.models import Base, SocialAccount, Content, AccountSnapshot, ContentSnapshot, CollectorRun
from app.connectors.instagram.client import InstagramClient
from app.connectors.instagram.service import InstagramCollector


@pytest.fixture(params=["sqlite", "postgres"])
def db(request):
    if request.param == "sqlite":
        engine=create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as session: yield session
    else:
        from tests.postgres_support import test_engine
        engine=test_engine()
        with engine.connect() as connection:
            transaction=connection.begin()
            try:
                with Session(connection,join_transaction_mode="create_savepoint") as session:
                    yield session
            finally:
                transaction.rollback()
    engine.dispose()


def settings():
    return Settings(_env_file=None,instagram_access_token="test-token",instagram_api_version="v26.0",instagram_max_pages=3)


def handler(request):
    path=request.url.path
    if path.endswith("/me"):
        return httpx.Response(200,json={"data":[{"user_id":"123","id":"999","username":"demo.account","account_type":"BUSINESS","followers_count":0,"follows_count":2}]})
    if path.endswith("/media"):
        if request.url.params.get("after")=="cursor2":
            return httpx.Response(200,json={"data":[{"id":"2","media_type":"CAROUSEL_ALBUM","caption":None,"timestamp":"2026-10-01T12:00:00+0000"}]})
        return httpx.Response(200,json={"data":[{"id":"1","media_type":"VIDEO","timestamp":"2026-10-01T11:00:00+0000"}],"paging":{"next":"https://evil.example/?access_token=test-token","cursors":{"after":"cursor2"}}})
    if path.endswith("/insights"):
        metric=request.url.params["metric"]
        period="day" if path.endswith("/123/insights") else "lifetime"
        if metric=="saved": return httpx.Response(200,json={"data":[]})
        return httpx.Response(200,json={"data":[{"name":metric,"period":period,"total_value":{"value":0}}]})
    raise AssertionError(str(request.url))


def collector(db=None, transport_handler=handler):
    client=InstagramClient("test-token","v26.0",transport=httpx.MockTransport(transport_handler),max_retries=0)
    return InstagramCollector(settings(),db,client)


def count(db,model): return db.scalar(select(func.count()).select_from(model))


def test_collect_authoritative_identity_pagination_null_and_scopes(db):
    worker=collector(db)
    result=worker.collect(run_id=uuid4())
    assert result["status"]=="success"
    assert result["media_discovered"]==2
    assert count(db,SocialAccount)==1
    assert db.scalar(select(SocialAccount)).platform_account_id=="123"
    assert count(db,Content)==2
    assert count(db,ContentSnapshot)==2
    assert count(db,AccountSnapshot)==2
    snapshot=db.scalar(select(ContentSnapshot).order_by(ContentSnapshot.created_at))
    assert snapshot.views==0
    assert snapshot.saves is None
    assert all(row.duration_seconds is None for row in db.scalars(select(Content)))
    assert snapshot.unique_viewers is None
    assert snapshot.raw_payload
    assert "test-token" not in str(snapshot.raw_payload)
    scopes={row.metric_scope for row in db.scalars(select(AccountSnapshot))}
    assert scopes=={"current","range"}
    range_snapshot=db.scalar(select(AccountSnapshot).where(AccountSnapshot.metric_scope=="range"))
    assert range_snapshot.followers is None
    assert range_snapshot.source_period_start and range_snapshot.source_period_end
    worker.client.close()


def test_run_idempotency_and_new_measurements(db):
    worker=collector(db); job=uuid4()
    worker.collect(run_id=job)
    worker.collect(run_id=job)
    assert count(db,ContentSnapshot)==2
    assert count(db,CollectorRun)==1
    worker.collect(run_id=uuid4())
    assert count(db,ContentSnapshot)==4
    assert count(db,AccountSnapshot)==4
    assert count(db,Content)==2
    assert count(db,SocialAccount)==1
    worker.client.close()


def test_partial_failure_keeps_other_media_and_can_resume(db):
    failed=True
    def flaky(request):
        if failed and request.url.path.endswith("/1/insights"):
            return httpx.Response(500,json={"error":{"code":2,"message":"test-token"}})
        return handler(request)
    worker=collector(db,flaky); job=uuid4()
    result=worker.collect(run_id=job)
    assert result["status"]=="partial"
    assert count(db,ContentSnapshot)==1
    failed=False
    result=worker.collect(run_id=job)
    assert result["status"]=="success"
    assert count(db,ContentSnapshot)==2
    assert count(db,AccountSnapshot)==2
    worker.client.close()


def test_unsupported_metric_preserves_other_values(db):
    def unsupported(request):
        if request.url.path.endswith("/1/insights") and request.url.params["metric"]=="shares":
            return httpx.Response(400,json={"error":{"code":100,"message":"unsupported metric test-token"}})
        return handler(request)
    worker=collector(db,unsupported)
    result=worker.collect(run_id=uuid4())
    assert result["status"]=="partial"
    snapshot=db.scalar(select(ContentSnapshot).join(Content).where(Content.platform_content_id=="1"))
    assert snapshot.views==0 and snapshot.shares is None
    assert "error" not in str(snapshot.raw_payload)
    assert "test-token" not in str(snapshot.raw_payload)
    worker.client.close()


def test_dry_run_never_uses_database():
    class ForbiddenDB:
        def __getattribute__(self,name): raise AssertionError("Dry run used DB")
    worker=collector(ForbiddenDB())
    result=worker.collect(dry_run=True)
    assert result["dry_run"] is True
    assert result["media_discovered"]==2
    worker.client.close()


def test_pagination_limit_is_partial(db):
    worker=collector(db)
    worker.settings.instagram_max_pages=1
    result=worker.collect(run_id=uuid4())
    assert result["status"]=="partial"
    assert result["media_discovered"]==1
    worker.client.close()


def test_username_change_reuses_authoritative_account(db):
    renamed=False
    def responses(request):
        response=handler(request)
        if renamed and request.url.path.endswith("/me"):
            data=response.json();data["data"][0]["username"]="dash.renamed"
            return httpx.Response(200,json=data)
        return response
    worker=collector(db,responses)
    worker.collect(run_id=uuid4())
    renamed=True
    result=worker.collect(run_id=uuid4())
    assert result["status"]=="success"
    assert count(db,SocialAccount)==1
    assert db.scalar(select(SocialAccount)).username=="dash.renamed"
    worker.client.close()


def test_running_job_is_not_reentered(db):
    from app.enums import Platform,CollectorStatus
    from app.connectors.instagram.service import CollectionBusyError
    job=uuid4()
    db.add(CollectorRun(id=job,platform=Platform.INSTAGRAM,status=CollectorStatus.RUNNING))
    db.commit()
    worker=collector(db)
    with pytest.raises(CollectionBusyError): worker.collect(run_id=job)
    assert count(db,ContentSnapshot)==0
    worker.client.close()


def test_partial_metric_retry_does_not_mutate_existing_snapshot(db):
    unsupported=True
    def responses(request):
        if unsupported and request.url.path.endswith("/1/insights") and request.url.params["metric"]=="shares":
            return httpx.Response(400,json={"error":{"code":100,"message":"unsupported metric"}})
        return handler(request)
    worker=collector(db,responses);job=uuid4()
    worker.collect(run_id=job)
    unsupported=False
    result=worker.collect(run_id=job)
    assert result["status"]=="partial"
    assert count(db,ContentSnapshot)==2
    snapshot=db.scalar(select(ContentSnapshot).join(Content).where(Content.platform_content_id=="1"))
    assert snapshot.shares is None
    # A genuine new measurement may now collect the formerly unsupported metric.
    worker.collect(run_id=uuid4())
    assert count(db,ContentSnapshot)==4
    worker.client.close()


def test_wrong_account_does_not_write_account_or_content(db):
    def responses(request):
        if request.url.path.endswith("/me"):
            return httpx.Response(200,json={"user_id":"555","username":"another.person"})
        raise AssertionError("Do not collect from unexpected account")
    worker=collector(db,responses)
    assert worker.collect(run_id=uuid4())["status"]=="failed"
    assert count(db,SocialAccount)==0
    assert count(db,AccountSnapshot)==0
    assert count(db,Content)==0
    worker.client.close()


def test_duplicate_media_across_pages_reuses_single_object(db):
    def duplicate(request):
        if request.url.path.endswith("/media") and request.url.params.get("after"):
            return httpx.Response(200,json={"data":[{"id":"1","media_type":"VIDEO"}]})
        return handler(request)
    worker=collector(db,duplicate)
    result=worker.collect(run_id=uuid4())
    assert result["media_discovered"]==1
    assert count(db,Content)==1 and count(db,ContentSnapshot)==1
    worker.client.close()


def test_account_range_errors_leave_current_counters_separate(db):
    def unavailable(request):
        if request.url.path.endswith("/123/insights"):
            return httpx.Response(403,json={"error":{"code":10,"message":"missing permission"}})
        return handler(request)
    worker=collector(db,unavailable)
    result=worker.collect(run_id=uuid4())
    assert result["status"]=="partial"
    current=db.scalar(select(AccountSnapshot))
    assert current.metric_scope=="current" and current.followers==0
    assert current.views is None and current.source_period_start is None
    assert count(db,ContentSnapshot)==2
    worker.client.close()


def test_content_snapshot_stays_immutable(db):
    worker=collector(db); worker.collect(run_id=uuid4())
    snapshot=db.scalar(select(ContentSnapshot))
    snapshot.views=200
    with pytest.raises(ValueError,match="append-only"): db.commit()
    db.rollback()
    assert db.scalar(select(ContentSnapshot)).views==0
    worker.client.close()


def test_run_snapshot_uniqueness_preserves_manual_null_run(db):
    from sqlalchemy.exc import IntegrityError
    from app.enums import Source
    from app.types import utc_now
    worker=collector(db); result=worker.collect(run_id=uuid4())
    first=db.scalar(select(ContentSnapshot))
    content_id,job=first.content_id,first.collection_run_id
    db.add(ContentSnapshot(content_id=content_id,collection_run_id=job,metric_scope="lifetime",snapshot_at=utc_now(),source=Source.INSTAGRAM_API,views=1))
    with pytest.raises(IntegrityError): db.commit()
    db.rollback()
    for source in (Source.MANUAL,Source.INSTAGRAM_UI):
        db.add(ContentSnapshot(content_id=content_id,snapshot_at=utc_now(),source=source,views=1))
    db.commit()
    assert count(db,ContentSnapshot)==4
    worker.client.close()


@pytest.mark.parametrize("known", ["reel", "story"])
def test_ambiguous_video_preserves_known_type_without_granting_reel_metrics(db, known):
    from app.enums import ContentType
    worker=collector(db)
    worker.collect(run_id=uuid4())
    content=db.scalar(select(Content).where(Content.platform_content_id=="1"))
    content.content_type=ContentType(known);db.commit()
    metrics=[]
    def responses(request):
        if request.url.path.endswith("/1/insights"): metrics.append(request.url.params["metric"])
        return handler(request)
    worker.client.close();worker=collector(db,responses)
    worker.collect(run_id=uuid4())
    assert content.content_type==ContentType(known)
    assert not any(metric.startswith("ig_reels_") for metric in metrics)
    worker.client.close()


@pytest.mark.parametrize("product, expected", [("REELS", "reel"), ("STORY", "story"), ("FEED", "video")])
def test_authoritative_product_refines_existing_type(db, product, expected):
    worker=collector(db);worker.collect(run_id=uuid4());worker.client.close()
    content=db.scalar(select(Content).where(Content.platform_content_id=="1"))
    from app.enums import ContentType
    content.content_type=ContentType.REEL;db.commit()
    def responses(request):
        response=handler(request)
        if request.url.path.endswith("/media"):
            payload=response.json()
            for item in payload["data"]:
                if item["id"]=="1": item["media_product_type"]=product
            return httpx.Response(200,json=payload)
        return response
    worker=collector(db,responses);worker.collect(run_id=uuid4())
    assert content.content_type.value==expected
    worker.client.close()


@pytest.mark.parametrize("counters, status, followers, following", [
    ({}, "unavailable", None, None),
    ({"followers_count":7}, "confirmed", 7, None),
    ({"follows_count":4}, "confirmed", None, 4),
    ({"followers_count":0,"follows_count":0}, "confirmed", 0, 0),
])
def test_current_counter_availability(db, counters, status, followers, following):
    def responses(request):
        if request.url.path.endswith("/me"):
            return httpx.Response(200,json={"user_id":"123","username":"demo.account",**counters})
        return handler(request)
    worker=collector(db,responses);result=worker.collect(run_id=uuid4())
    snapshot=db.scalar(select(AccountSnapshot).where(AccountSnapshot.metric_scope=="current"))
    assert snapshot.snapshot_status.value==status
    assert (snapshot.followers,snapshot.following)==(followers,following)
    assert result["status"]=="success"
    worker.client.close()


def test_account_run_scope_uniqueness(db):
    from sqlalchemy.exc import IntegrityError
    from app.enums import Source
    from app.types import utc_now
    worker=collector(db);job=uuid4();worker.collect(run_id=job)
    account=db.scalar(select(SocialAccount))
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(AccountSnapshot(account_id=account.id,collection_run_id=job,metric_scope="current",snapshot_at=utc_now(),source=Source.INSTAGRAM_API))
            db.flush()
    with db.begin_nested():
        db.add(AccountSnapshot(account_id=account.id,collection_run_id=job,metric_scope="other",snapshot_at=utc_now(),source=Source.INSTAGRAM_API))
        db.flush()
    assert count(db,AccountSnapshot)==3
    worker.client.close()
