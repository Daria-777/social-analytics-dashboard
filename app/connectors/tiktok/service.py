"""TikTok public counters only; optional creator analytics remain NULL."""
from uuid import uuid4
import logging
from sqlalchemy import select,func
from sqlalchemy.exc import SQLAlchemyError
from app.models import SocialAccount,AccountSnapshot,ContentSnapshot
from app.enums import Platform,Source,DataStatus,CollectorStatus
from app.types import utc_now
from app.connectors.locks import guard_collection
from app.connectors.persistence import CollectorPersistence
from app.connectors.instagram.mapper import sanitize
from . import mapper
from .errors import TikTokError,TikTokIdentityError,TikTokPaginationError,TikTokInvalidResponseError,TikTokDatabaseError

log=logging.getLogger(__name__)


class TikTokCollector(CollectorPersistence):
    platform=Platform.TIKTOK
    identity_error=TikTokIdentityError
    def __init__(self,settings,session,client):
        self.settings,self.db,self.client=settings,session,client
        self.secrets=tuple(value.get_secret_value() for value in (settings.tiktok_access_token,settings.tiktok_refresh_token,settings.tiktok_client_secret) if value)
        self.failures=[]
    def _failure(self,item,error):
        self.failures.append({'item':item,'error_type':type(error).__name__,'endpoint':error.endpoint,'operation':error.operation,'http_status':error.http_status,'code':error.code})
        log.warning('TikTok collection limitation',extra={'platform':'tiktok','operation':'collect','content_id':item,'status':'partial','error_type':type(error).__name__})
    def _pages(self):
        cursor=None;seen=set()
        for _ in range(self.settings.tiktok_max_pages):
            payload=self.client.videos(cursor);data=payload['data']
            videos=data.get('videos');more=data.get('has_more')
            if not isinstance(videos,list) or any(not isinstance(v,dict) for v in videos) or not isinstance(more,bool):
                raise TikTokInvalidResponseError('/v2/video/list/','normalize_page')
            yield payload
            if not more: return
            cursor=data.get('cursor')
            if isinstance(cursor,bool) or not isinstance(cursor,int) or cursor<0 or cursor in seen:
                raise TikTokPaginationError('/v2/video/list/','cursor_invalid_or_repeated')
            seen.add(cursor)
        raise TikTokPaginationError('/v2/video/list/','page_limit')
    @guard_collection
    def collect(self,*,run_id=None,dry_run=False):
        self.failures=[];run=None
        if not dry_run:
            run,cached=self._reserve(run_id or uuid4())
            if cached: return run.summary
        result={'run_id':str(run.id) if run else None,'dry_run':dry_run,'account':None,'media_discovered':0,'new_media':None if dry_run else (run.summary or {}).get('new_media',0),'content_snapshots':0,'account_snapshots':0,'status':'success'}
        if dry_run: result['would_sync']=[]
        try:
            raw=self.client.user();dto=mapper.account(raw)
            if self.settings.tiktok_open_id and dto.platform_account_id!=self.settings.tiktok_open_id:
                raise TikTokIdentityError('/v2/user/info/','configured_id_mismatch')
            if run and run.platform_account_id and dto.platform_account_id!=run.platform_account_id:
                raise TikTokIdentityError('/v2/user/info/','run_identity_mismatch')
            known=None if dry_run else self.db.scalar(select(SocialAccount).where(SocialAccount.platform==self.platform,SocialAccount.platform_account_id==dto.platform_account_id))
            if not (self.settings.tiktok_open_id or known or (run and run.platform_account_id)) and dto.username.casefold()!=self.settings.tiktok_expected_username.casefold():
                raise TikTokIdentityError('/v2/user/info/','configured_username_mismatch')
            result['account']=sanitize(dto.username,self.secrets)
            if run and not run.platform_account_id: run.platform_account_id=dto.platform_account_id;self.db.commit()
            account=None if dry_run else self._upsert_account(dto)
            current=None if dry_run else self._snapshot_exists(AccountSnapshot,'account_id',account.id,run.id,'current')
            if current is None:
                values={'followers':None,'following':None,'likes':None};raw_stats=None
                if 'user.info.stats' in self.settings.tiktok_scopes.split(','):
                    try:
                        raw_stats=self.client.user(stats=True)
                        combined={'data':{'user':{**raw_stats['data'].get('user',{}),'username':dto.username}}}
                        stats=mapper.account(combined)
                        if stats.platform_account_id!=dto.platform_account_id: raise TikTokIdentityError('/v2/user/info/','stats_identity_mismatch')
                        values={'followers':stats.followers,'following':stats.following,'likes':stats.likes}
                    except TikTokError as error:
                        raw_stats=None;self._failure('account_stats',error)
                status=DataStatus.CONFIRMED if any(v is not None for v in values.values()) else DataStatus.UNAVAILABLE
                result['account_snapshots']+=1
                if not dry_run:
                    self._persist_snapshot(AccountSnapshot(account_id=account.id,collection_run_id=run.id,metric_scope='current',snapshot_at=utc_now(),source=Source.TIKTOK_API,snapshot_status=status,raw_payload={'user':sanitize(raw,self.secrets),'stats':sanitize(raw_stats,self.secrets)},**values))
            elif (current.raw_payload or {}).get('stats') is None:
                for failure in (run.summary or {}).get('failure_details',[]):
                    if failure['item']=='account_stats': self.failures.append(failure)
            seen=set()
            for page in self._pages():
                for payload in page['data']['videos']:
                    try:
                        media,duration,values=mapper.video(payload)
                        if media.platform_content_id in seen: continue
                        seen.add(media.platform_content_id);result['media_discovered']+=1
                        if dry_run: result['would_sync'].append({'platform_content_id':media.platform_content_id,'content_type':'video'});result['content_snapshots']+=1;continue
                        content,created=self._upsert_content(account,media)
                        if duration is not None: content.duration_seconds=duration;self.db.commit()
                        if created: result['new_media']+=1
                        if self._snapshot_exists(ContentSnapshot,'content_id',content.id,run.id): continue
                        status=DataStatus.CONFIRMED if any(v is not None for v in values.values()) else DataStatus.UNAVAILABLE
                        self._persist_snapshot(ContentSnapshot(content_id=content.id,collection_run_id=run.id,metric_scope='lifetime',snapshot_at=utc_now(),source=Source.TIKTOK_API,snapshot_status=status,raw_payload={'video':sanitize(payload,self.secrets),'response':sanitize(page,self.secrets)},**values))
                    except TikTokError as error: self._failure('video',error)
        except TikTokError as error: self._failure('discovery',error)
        except SQLAlchemyError:
            if not dry_run: self.db.rollback()
            self._failure('database',TikTokDatabaseError('collector','persistence'))
        if not dry_run:
            result['content_snapshots']=self.db.scalar(select(func.count()).select_from(ContentSnapshot).where(ContentSnapshot.collection_run_id==run.id))
            result['account_snapshots']=self.db.scalar(select(func.count()).select_from(AccountSnapshot).where(AccountSnapshot.collection_run_id==run.id))
        result['failures']=len(self.failures);result['failure_details']=self.failures
        if self.failures: result['status']='partial' if result['content_snapshots'] or result['account_snapshots'] else 'failed'
        if run:
            run.status=CollectorStatus(result['status']);run.finished_at=utc_now();run.summary=result
            run.error_type=self.failures[0]['error_type'] if self.failures else None
            run.error_message_safe='Collection limitations; see safe failure_details' if self.failures else None
            self.db.commit()
        return result
