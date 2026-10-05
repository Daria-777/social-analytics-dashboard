"""Opt-in daily and young-publication jobs. No stale-running reset."""
from dataclasses import dataclass,field
from datetime import datetime,timedelta,timezone
from uuid import UUID,uuid5,NAMESPACE_URL
from sqlalchemy import select,func
from app.models import Content,CollectorRun,SocialAccount
from app.enums import Platform,CollectorStatus
from app.connectors.locks import advisory_lock
from app.connectors.persistence import CollectionBusyError
from app.connectors.instagram.client import InstagramClient
from app.connectors.instagram.service import InstagramCollector
from app.connectors.tiktok.client import TikTokClient
from app.connectors.tiktok.credentials import resolve_settings,CredentialStore
from app.connectors.tiktok.errors import TikTokError
from app.connectors.tiktok.service import TikTokCollector

AGES=(6,24,72,168)


@dataclass
class ScheduledJob:
    run_id: UUID
    platform: Platform
    due_at: datetime
    reason: str
    targets: list=field(default_factory=list)

    def public(self):
        return {'run_id':str(self.run_id),'platform':self.platform.value,'due_at':self.due_at.isoformat(),'reason':self.reason,'targets':self.targets}


def configured(settings,platform):
    if platform==Platform.TIKTOK and settings.tiktok_credential_store:
        try:settings=resolve_settings(settings)
        except TikTokError:return False
    token=getattr(settings,platform.value+'_access_token')
    return bool(token and token.get_secret_value().strip())


def planned_jobs(db,settings,now):
    if now.tzinfo is None: raise ValueError('Scheduler clock must be aware')
    now=now.astimezone(timezone.utc);jobs={}
    original_settings=settings
    for platform in Platform:
        settings=original_settings
        if platform==Platform.TIKTOK:
            try:settings=resolve_settings(settings,now=now)
            except TikTokError:continue
        if not configured(settings,platform): continue
        due=now.replace(hour=settings.scheduler_daily_hour_utc,minute=0,second=0,microsecond=0)
        if due<=now:
            key=f'daily:{platform.value}:{due.date().isoformat()}'
            jobs[key]=ScheduledJob(uuid5(NAMESPACE_URL,'dash:schedule:'+key),platform,due,'daily')
        owner_id=settings.instagram_user_id if platform==Platform.INSTAGRAM else settings.tiktok_open_id
        expected=settings.instagram_expected_username if platform==Platform.INSTAGRAM else settings.tiktok_expected_username
        posts_query=select(Content).join(SocialAccount,SocialAccount.id==Content.account_id).where(Content.platform==platform,Content.published_at>=now-timedelta(days=8),Content.published_at<=now)
        posts_query=posts_query.where(SocialAccount.platform_account_id==owner_id) if owner_id else posts_query.where(func.lower(SocialAccount.username)==expected.casefold())
        posts=db.scalars(posts_query).all()
        for post in posts:
            for hours in AGES:
                exact=post.published_at+timedelta(hours=hours)
                due=exact.replace(minute=0,second=0,microsecond=0)
                if exact!=due: due+=timedelta(hours=1)
                if due>now or now-due>timedelta(hours=settings.scheduler_max_lateness_hours): continue
                key=f'age:{platform.value}:{due.isoformat()}'
                job=jobs.setdefault(key,ScheduledJob(uuid5(NAMESPACE_URL,'dash:schedule:'+key),platform,due,'age'))
                job.targets.append({'content_id':str(post.id),'age_hours':hours})
    return sorted(jobs.values(),key=lambda job:(job.due_at,job.platform.value,job.reason))


def collect_job(job,settings,db):
    if job.platform==Platform.INSTAGRAM:
        with InstagramClient(settings.require_instagram_token(),settings.instagram_api_version) as client:
            return InstagramCollector(settings,db,client).collect(run_id=job.run_id)
    settings=resolve_settings(settings,allow_refresh=True)
    with TikTokClient(settings.require_tiktok_token()) as client:
        return TikTokCollector(settings,db,client).collect(run_id=job.run_id)


def renewal_cooldown(db,settings,now):
    last=db.scalar(select(CollectorRun).where(CollectorRun.platform==Platform.TIKTOK,CollectorRun.status==CollectorStatus.FAILED,CollectorRun.error_type=='TikTokCredentialRenewalError').order_by(CollectorRun.finished_at.desc(),CollectorRun.id.desc()).limit(1))
    if last is None:return False
    # Explicitly renewed/reauthorized credentials end the old credential cooldown.
    if settings.tiktok_credential_store and last.finished_at:
        try:
            issued=CredentialStore(settings.tiktok_credential_store).read().issued_at
            if last.finished_at<issued<=now:return False
        except TikTokError:pass
    metadata=(last.summary or {}).get('schedule',{})
    if metadata.get('attempts',0)>=settings.scheduler_max_attempts:return True
    retry=metadata.get('next_retry_at')
    return bool(retry and datetime.fromisoformat(retry)>now)


def run_tick(db,settings,now,*,runner=None):
    results=[];executed=0;unavailable={Platform.TIKTOK} if renewal_cooldown(db,settings,now) else set()
    for job in planned_jobs(db,settings,now):
        if job.platform in unavailable:continue
        if executed>=settings.scheduler_max_jobs_per_tick: break
        with advisory_lock(db,'schedule:'+str(job.run_id)) as acquired:
            if not acquired: results.append({**job.public(),'status':'busy'});continue
            db.expire_all()
            run=db.get(CollectorRun,job.run_id)
            metadata=(run.summary or {}).get('schedule',{}) if run else {}
            attempts=metadata.get('attempts',0)
            if run and run.status in (CollectorStatus.RUNNING,CollectorStatus.SUCCESS): continue
            if attempts>=settings.scheduler_max_attempts: continue
            next_retry=metadata.get('next_retry_at')
            if next_retry and datetime.fromisoformat(next_retry)>now: continue
            renewal_failed=False
            try: result=runner(job) if runner else collect_job(job,settings,db)
            except CollectionBusyError:
                results.append({**job.public(),'status':'busy'});continue
            except TikTokError:
                unavailable.add(job.platform)
                renewal_failed=True
                if run is None:
                    run=CollectorRun(id=job.run_id,platform=job.platform,started_at=now);db.add(run)
                run.status=CollectorStatus.FAILED;run.finished_at=now
                run.error_type='TikTokCredentialRenewalError'
                run.summary={**(run.summary or {}),'status':'failed','failures':max((run.summary or {}).get('failures') or 0,1)}
                db.flush()
                result=run.summary
            run=db.get(CollectorRun,job.run_id)
            attempts+=1
            if not renewal_failed:executed+=1
            retry=now+timedelta(minutes=settings.scheduler_retry_minutes*(2**(attempts-1)))
            schedule={**job.public(),'attempts':attempts,'next_retry_at':retry.isoformat() if result['status'] in ('failed','partial') and attempts<settings.scheduler_max_attempts else None}
            run.summary={**(run.summary or {}),'schedule':schedule};db.commit()
            results.append({**job.public(),'status':result['status'],'attempts':attempts,**({'error_type':'TikTokCredentialRenewalError'} if renewal_failed else {})})
    return results
