from datetime import datetime,timezone,timedelta
from uuid import uuid4
import pytest
from app.scheduler import planned_jobs,run_tick
from app.config import Settings
from app.models import CollectorRun,SocialAccount,Content
from app.enums import Platform,CollectorStatus,ContentType
from tests.test_instagram_service import db

NOW=datetime(2026,10,3,12,tzinfo=timezone.utc)


def settings(): return Settings(_env_file=None,scheduler_enabled=True,instagram_access_token='test-token',scheduler_daily_hour_utc=9,scheduler_max_attempts=3)


def test_daily_identity_restart_and_bounded_failure(db):
    config=settings();calls=[]
    def fail(job):
        calls.append(job.run_id)
        run=db.get(CollectorRun,job.run_id)
        if run is None: run=CollectorRun(id=job.run_id,platform=job.platform);db.add(run)
        run.status=CollectorStatus.FAILED;run.summary={'status':'failed'};db.commit()
        return run.summary
    jobs=planned_jobs(db,config,NOW)
    assert {j.run_id for j in jobs}=={j.run_id for j in planned_jobs(db,config,NOW+timedelta(minutes=1))}
    for minutes in (0,0,31,62,93): run_tick(db,config,NOW+timedelta(minutes=minutes),runner=fail)
    assert len(calls)==3 and len(set(calls))==1
    run=db.get(CollectorRun,calls[0]);assert run.summary['schedule']['attempts']==3
    run.status=CollectorStatus.RUNNING;db.commit();config.scheduler_max_attempts=4
    run_tick(db,config,NOW+timedelta(hours=2),runner=fail)
    assert len(calls)==3


def test_age_jobs_coalesce_and_do_not_backfill_obsolete_milestones(db):
    account=SocialAccount(platform=Platform.INSTAGRAM,username='demo.account',platform_account_id='test-scheduler');db.add(account);db.flush()
    for delta in (timedelta(hours=6,minutes=30),timedelta(hours=6,minutes=45),timedelta(days=3,hours=5)):
        db.add(Content(account_id=account.id,platform=Platform.INSTAGRAM,platform_content_id=str(uuid4()),content_type=ContentType.VIDEO,published_at=NOW-delta))
    db.commit()
    jobs=planned_jobs(db,settings(),NOW)
    age=[job for job in jobs if job.reason=='age']
    assert len(age)==1 and len(age[0].targets)==2
    assert all(t['age_hours']==6 for t in age[0].targets)


def test_scheduler_disabled_cli_never_opens_db(capsys):
    from app.cli.scheduler import main
    def forbidden(): raise AssertionError('Disabled scheduler opened DB')
    assert main(['--once'],settings=Settings(_env_file=None),engine_factory=forbidden)==2
    assert 'disabled' in capsys.readouterr().err.lower()


def test_renewal_failure_does_not_stop_instagram_or_repeat_tiktok_within_tick(db,monkeypatch):
    from app.connectors.tiktok.errors import TikTokAuthError
    from app.scheduler import ScheduledJob
    import app.scheduler as scheduler
    jobs=[ScheduledJob(uuid4(),platform,NOW,'daily') for platform in (Platform.TIKTOK,Platform.TIKTOK,Platform.INSTAGRAM)]
    monkeypatch.setattr(scheduler,'planned_jobs',lambda *a:jobs)
    calls=[]
    def runner(job):
        calls.append(job.platform)
        if job.platform==Platform.TIKTOK:raise TikTokAuthError('oauth','renewal')
        run=CollectorRun(id=job.run_id,platform=job.platform,status=CollectorStatus.SUCCESS,summary={'status':'success'});db.add(run);db.commit();return run.summary
    result=run_tick(db,settings(),NOW,runner=runner)
    assert calls==[Platform.TIKTOK,Platform.INSTAGRAM]
    assert result[0]['error_type']=='TikTokCredentialRenewalError' and result[1]['status']=='success'


def test_store_only_scheduler_plan_does_not_call_oauth(db,tmp_path):
    from tests.test_tiktok_credentials import config,seed
    path=tmp_path/'.tiktok-credentials';seed(path,expires_in=1)
    configuration=config(path)
    from app.scheduler import configured
    assert configured(configuration,Platform.TIKTOK)
    jobs=planned_jobs(db,configuration,NOW)
    assert jobs and all(job.platform==Platform.TIKTOK for job in jobs)


def test_renewal_failures_obey_cooldown_and_max_attempts_without_snapshots(db,monkeypatch):
    from app.connectors.tiktok.errors import TikTokAuthError
    from app.scheduler import ScheduledJob
    import app.scheduler as scheduler
    from app.models import AccountSnapshot,ContentSnapshot
    from sqlalchemy import select,func
    job=ScheduledJob(uuid4(),Platform.TIKTOK,NOW,'daily');calls=[]
    monkeypatch.setattr(scheduler,'planned_jobs',lambda *a:[job])
    def failed_refresh(job):calls.append(job.run_id);raise TikTokAuthError('oauth','renewal')
    config=settings();config.scheduler_max_attempts=2
    first=run_tick(db,config,NOW,runner=failed_refresh)
    assert first[0]['attempts']==1
    assert run_tick(db,config,NOW+timedelta(minutes=1),runner=failed_refresh)==[]
    second=run_tick(db,config,NOW+timedelta(minutes=31),runner=failed_refresh)
    assert second[0]['attempts']==2
    assert run_tick(db,config,NOW+timedelta(hours=5),runner=failed_refresh)==[]
    assert len(calls)==2
    run=db.get(CollectorRun,job.run_id)
    assert run.status==CollectorStatus.FAILED and run.error_type=='TikTokCredentialRenewalError'
    assert run.summary['schedule']['next_retry_at'] is None
    assert db.scalar(select(func.count()).select_from(AccountSnapshot))==0 and db.scalar(select(func.count()).select_from(ContentSnapshot))==0


def test_renewal_failure_keeps_previous_partial_run_summary(db,monkeypatch):
    import app.scheduler as scheduler
    from app.scheduler import ScheduledJob
    from app.connectors.tiktok.errors import TikTokAuthError
    job=ScheduledJob(uuid4(),Platform.TIKTOK,NOW,'daily')
    run=CollectorRun(id=job.run_id,platform=Platform.TIKTOK,status=CollectorStatus.PARTIAL,summary={'new_media':5,'content_snapshots':5,'failure_details':[{'item':'account_stats'}]});db.add(run);db.commit()
    monkeypatch.setattr(scheduler,'planned_jobs',lambda *a:[job])
    run_tick(db,settings(),NOW,runner=lambda job:(_ for _ in ()).throw(TikTokAuthError('oauth','renewal')))
    assert run.summary['new_media']==5 and run.summary['content_snapshots']==5 and run.summary['failure_details']==[{'item':'account_stats'}]


def test_platform_renewal_cooldown_cannot_be_bypassed_by_another_tiktok_job(db,monkeypatch):
    import app.scheduler as scheduler
    from app.scheduler import ScheduledJob
    from app.connectors.tiktok.errors import TikTokAuthError
    tiktok=[ScheduledJob(uuid4(),Platform.TIKTOK,NOW,reason) for reason in ('daily','age')]
    instagram=[ScheduledJob(uuid4(),Platform.INSTAGRAM,NOW,'daily') for _ in range(4)]
    monkeypatch.setattr(scheduler,'planned_jobs',lambda db,config,now:tiktok+[instagram.pop(0)])
    calls=[]
    def runner(job):
        calls.append(job.platform)
        if job.platform==Platform.TIKTOK:raise TikTokAuthError('oauth','renewal')
        run=CollectorRun(id=job.run_id,platform=job.platform,status=CollectorStatus.SUCCESS,summary={'status':'success'});db.add(run);db.commit();return run.summary
    config=settings();config.scheduler_max_attempts=2;config.scheduler_max_jobs_per_tick=1
    for minutes in (0,1,31,100):run_tick(db,config,NOW+timedelta(minutes=minutes),runner=runner)
    assert calls.count(Platform.TIKTOK)==2 and calls.count(Platform.INSTAGRAM)==4
    assert db.get(CollectorRun,tiktok[0].run_id).summary['schedule']['attempts']==2
    assert db.get(CollectorRun,tiktok[1].run_id) is None


def test_verified_new_credentials_end_platform_cooldown(db,tmp_path):
    from app.scheduler import renewal_cooldown
    from tests.test_tiktok_credentials import config,seed
    path=tmp_path/'.tiktok-credentials';seed(path,issued_at=NOW+timedelta(seconds=1))
    run=CollectorRun(platform=Platform.TIKTOK,status=CollectorStatus.FAILED,finished_at=NOW,error_type='TikTokCredentialRenewalError',summary={'schedule':{'attempts':3,'next_retry_at':None}});db.add(run);db.commit()
    assert renewal_cooldown(db,config(path),NOW+timedelta(seconds=2)) is False
    assert renewal_cooldown(db,settings(),NOW+timedelta(seconds=2)) is True
