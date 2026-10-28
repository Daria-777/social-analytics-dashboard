from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
import pytest
from app.config import Settings
from app.models import Base, CollectorRun, SocialAccount, Content
from app.enums import Platform, CollectorStatus, ContentType
from app.scheduler import planned_jobs, run_tick

NOW=datetime(2026,10,23,12,5,tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session: yield session
    engine.dispose()


def settings():
    return Settings(_env_file=None,scheduler_enabled=True,scheduler_collection_frequency='hourly',
        instagram_access_token='fake-instagram',tiktok_access_token='fake-tiktok')


def test_hourly_discovers_both_accounts_without_known_publications(db):
    jobs=planned_jobs(db,settings(),NOW)
    assert len(jobs)==2 and {j.platform for j in jobs}==set(Platform)
    assert all(j.reason=='hourly' and j.due_at==NOW.replace(minute=0) for j in jobs)


def test_hour_identity_stable_across_restart_timezone_and_changes_next_hour(db):
    first=planned_jobs(db,settings(),NOW)
    same=planned_jobs(db,settings(),(NOW+timedelta(minutes=40)).astimezone(timezone(timedelta(hours=3))))
    next_hour=planned_jobs(db,settings(),NOW+timedelta(hours=1))
    assert [j.run_id for j in first]==[j.run_id for j in same]
    assert not {j.run_id for j in first}&{j.run_id for j in next_hour}
    assert len(next_hour)==2  # Missed hours are not backfilled with current counters.


def test_hourly_coalesces_current_age_milestone_and_skips_older_buckets(db):
    account=SocialAccount(platform=Platform.INSTAGRAM,username='demo.account',platform_account_id='123')
    db.add(account);db.flush()
    for n,age in enumerate([6,7]):
        db.add(Content(account_id=account.id,platform=Platform.INSTAGRAM,platform_content_id=str(n),content_type=ContentType.REEL,published_at=NOW.replace(minute=0)-timedelta(hours=age)))
    db.commit()
    jobs=planned_jobs(db,settings(),NOW)
    assert len(jobs)==2
    instagram=next(j for j in jobs if j.platform==Platform.INSTAGRAM)
    assert instagram.reason=='hourly'
    assert len(instagram.targets)==1 and instagram.targets[0]['age_hours']==6


def test_legacy_daily_remains_default(db):
    config=settings().model_copy(update={'scheduler_collection_frequency':'daily'})
    assert {j.reason for j in planned_jobs(db,config,NOW)}=={'daily'}
    assert Settings(_env_file=None).scheduler_collection_frequency=='daily'


def test_hourly_success_not_repeated_and_failed_retry_reuses_uuid(db,monkeypatch):
    import app.scheduler as scheduler
    @contextmanager
    def local_lock(*args):yield True
    monkeypatch.setattr(scheduler,'advisory_lock',local_lock)
    calls=[]
    def runner(job):
        calls.append(job.run_id)
        run=db.get(CollectorRun,job.run_id)
        if run is None:
            run=CollectorRun(id=job.run_id,platform=job.platform);db.add(run)
        run.status=CollectorStatus.SUCCESS
        run.summary={'status':'success'};db.commit()
        return run.summary
    run_tick(db,settings(),NOW,runner=runner)
    run_tick(db,settings(),NOW+timedelta(minutes=10),runner=runner)
    assert len(calls)==2
    run_tick(db,settings(),NOW+timedelta(hours=1),runner=runner)
    assert len(calls)==4 and len(set(calls))==4
    assert db.scalar(select(func.count()).select_from(CollectorRun))==4


def test_hourly_failed_run_retries_same_uuid_within_hour(db,monkeypatch):
    import app.scheduler as scheduler
    @contextmanager
    def local_lock(*args):yield True
    monkeypatch.setattr(scheduler,'advisory_lock',local_lock)
    calls=[]
    def runner(job):
        calls.append(job.run_id)
        run=db.get(CollectorRun,job.run_id)
        if run is None:run=CollectorRun(id=job.run_id,platform=job.platform);db.add(run)
        run.status=CollectorStatus.FAILED;run.summary={'status':'failed'};db.commit()
        return run.summary
    run_tick(db,settings(),NOW,runner=runner)
    assert run_tick(db,settings(),NOW+timedelta(minutes=1),runner=runner)==[]
    run_tick(db,settings(),NOW+timedelta(minutes=31),runner=runner)
    assert calls[:2]==calls[2:] and len(calls)==4
