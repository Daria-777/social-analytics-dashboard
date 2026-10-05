"""Fetch → normalize → persist. Each successful object commits independently."""
from datetime import timedelta
from uuid import uuid4
import logging
from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError
from app.models import SocialAccount, Content, AccountSnapshot, ContentSnapshot, CollectorRun
from app.enums import Platform, Source, DataStatus, CollectorStatus
from app.types import utc_now
from app.connectors.locks import guard_collection
from . import mapper
from .errors import InstagramError, InstagramInvalidResponseError, InstagramPaginationError, InstagramIdentityError, InstagramDatabaseError, InstagramUnavailableMetricError

log=logging.getLogger(__name__)


from app.connectors.persistence import CollectorPersistence, CollectionBusyError


class InstagramCollector(CollectorPersistence):
    platform = Platform.INSTAGRAM
    identity_error = InstagramIdentityError
    def __init__(self,settings,session,client):
        self.settings,self.db,self.client=settings,session,client
        self.failures=[]
        self.secrets=(settings.instagram_access_token.get_secret_value() if settings.instagram_access_token else "",settings.instagram_client_secret.get_secret_value() if settings.instagram_client_secret else "")

    def _failure(self,item,error,metric=None):
        self.failures.append({"item":item,"metric":metric,"error_type":type(error).__name__,"endpoint":error.endpoint,"operation":error.operation,"http_status":error.http_status,"meta_code":error.meta_code})
        log.warning("Instagram collection limitation",extra={"platform":"instagram","operation":"collect","content_id":item,"status":"partial","error_type":type(error).__name__})

    def _media_pages(self,account_id):
        after=None; seen=set()
        for _ in range(self.settings.instagram_max_pages):
            params={"fields":"id,media_type,caption,permalink,timestamp,media_url,thumbnail_url,children{media_type,media_url,thumbnail_url}","limit":100}
            if after: params["after"]=after
            payload=self.client.get(f"{account_id}/media",operation="media_discovery",params=params)
            data=payload.get("data")
            if not isinstance(data,list) or any(not isinstance(item,dict) for item in data):
                raise InstagramInvalidResponseError("media","media_discovery")
            yield data
            paging=payload.get("paging",{})
            if not isinstance(paging,dict): raise InstagramInvalidResponseError("media","pagination")
            if not paging.get("next"): return
            cursors=paging.get("cursors",{})
            after=cursors.get("after") if isinstance(cursors,dict) else None
            if not isinstance(after,str) or not after or after in seen:
                raise InstagramPaginationError("media","pagination")
            seen.add(after)
        raise InstagramPaginationError("media","pagination_safety_limit")

    def _insights(self,object_id,metrics,period,params=None):
        values={}; raw={}; before=len(self.failures)
        for metric in metrics:
            try:
                parameters={"metric":metric,**(params or {})}
                payload=self.client.get(f"{object_id}/insights",operation="insight",params=parameters)
                value=mapper.insight_value(payload,metric,period=period)
                raw[metric]=mapper.sanitize(payload,self.secrets)
                field=mapper.FIELDS.get(metric)
                if field: values[field]=value
            except InstagramError as error:
                self._failure(object_id,error,metric)
        return values,raw,self.failures[before:]

    @guard_collection
    def collect(self,*,run_id=None,dry_run=False):
        self.failures=[]
        run=None
        if not dry_run:
            if self.db is None: raise ValueError("Database session is required")
            run,cached=self._reserve(run_id or uuid4())
            if cached: return run.summary
            # Failures attached to already-immutable partial snapshots remain unresolved.
            previous=(run.summary or {}).get("failure_details",[])
        else: previous=[]
        snapshot_at=utc_now()
        result={"run_id":str(run.id) if run else None,"dry_run":dry_run,"account":None,"media_discovered":0,"new_media":None if dry_run else (run.summary or {}).get("new_media",0),"content_snapshots":0,"account_snapshots":0,"failures":0,"status":"success"}
        if dry_run: result["would_sync"]=[]
        try:
            raw_account=self.client.get("me",operation="account_discovery",params={"fields":"user_id,username,account_type,followers_count,follows_count"})
            dto=mapper.account(raw_account)
            if self.settings.instagram_user_id and self.settings.instagram_user_id!=dto.platform_account_id:
                raise InstagramIdentityError("me","configured_id_mismatch")
            if run and run.platform_account_id and run.platform_account_id!=dto.platform_account_id:
                raise InstagramIdentityError("me","run_account_identity_mismatch")
            known = None if dry_run else self.db.scalar(select(SocialAccount).where(SocialAccount.platform==Platform.INSTAGRAM,SocialAccount.platform_account_id==dto.platform_account_id))
            pinned = bool(self.settings.instagram_user_id or (run and run.platform_account_id) or known)
            if not pinned and self.settings.instagram_expected_username and dto.username.casefold()!=self.settings.instagram_expected_username.casefold():
                raise InstagramIdentityError("me","configured_username_mismatch")
            if run and not run.platform_account_id:
                run.platform_account_id=dto.platform_account_id
                self.db.commit()
            result["account"]=mapper.sanitize(dto.username,self.secrets)
            snapshot_at=utc_now()
            account=None if dry_run else self._upsert_account(dto)
            account_current=None if dry_run else self._snapshot_exists(AccountSnapshot,"account_id",account.id,run.id,"current")
            if account_current is None:
                result["account_snapshots"]+=1
                if not dry_run:
                    self._persist_snapshot(AccountSnapshot(account_id=account.id,collection_run_id=run.id,metric_scope="current",snapshot_at=snapshot_at,source=Source.INSTAGRAM_API,snapshot_status=self._status({"followers":dto.followers,"following":dto.following},[]),followers=dto.followers,following=dto.following,raw_payload={"account":mapper.sanitize(raw_account,self.secrets)}))
            account_range=None if dry_run else self._snapshot_exists(AccountSnapshot,"account_id",account.id,run.id,"range")
            if account_range is None:
                end=(run.started_at if run else snapshot_at).replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(seconds=1)
                start=end.replace(hour=0,minute=0,second=0,microsecond=0)
                params={"period":"day","metric_type":"total_value","since":int(start.timestamp()),"until":int(end.timestamp())}
                values,raw,errors=self._insights(dto.platform_account_id,mapper.ACCOUNT_METRICS,"day",params)
                if raw:
                    result["account_snapshots"]+=1
                    if not dry_run:
                        self._persist_snapshot(AccountSnapshot(account_id=account.id,collection_run_id=run.id,metric_scope="range",snapshot_at=utc_now(),source=Source.INSTAGRAM_API,source_period_start=start,source_period_end=end,snapshot_status=self._status(values,errors),notes=self._notes(values,errors),raw_payload={"request":params,"insights":raw},**values))
            else:
                self._previous_errors(account_range,dto.platform_account_id,mapper.ACCOUNT_METRICS,previous)
            seen=set()
            try:
                for page in self._media_pages(dto.platform_account_id):
                    for payload in page:
                        try:
                            media=mapper.media(payload)
                            if media.platform_content_id in seen: continue
                            seen.add(media.platform_content_id);result["media_discovered"]+=1
                            if dry_run: result["would_sync"].append({"platform_content_id":media.platform_content_id,"content_type":media.content_type.value})
                            content,created=(None,False) if dry_run else self._upsert_content(account,media)
                            if created: result["new_media"]+=1
                            existing=None if dry_run else self._snapshot_exists(ContentSnapshot,"content_id",content.id,run.id)
                            if existing:
                                self._previous_errors(existing,media.platform_content_id,mapper.CAPABILITIES[media.capability],previous)
                                continue
                            metrics=mapper.CAPABILITIES[media.capability]
                            values,raw,errors=self._insights(media.platform_content_id,metrics,"lifetime")
                            if raw:
                                result["content_snapshots"]+=1
                                if not dry_run:
                                    self._persist_snapshot(ContentSnapshot(content_id=content.id,collection_run_id=run.id,metric_scope="lifetime",snapshot_at=utc_now(),source=Source.INSTAGRAM_API,snapshot_status=self._status(values,errors),notes=self._notes(values,errors),raw_payload={"metadata":mapper.sanitize(payload,self.secrets),"insights":raw},**values))
                            elif not metrics:
                                self._failure(media.platform_content_id,InstagramInvalidResponseError("media","unsupported_media_type"))
                        except InstagramError as error: self._failure("media",error)
            except InstagramError as error: self._failure("media_discovery",error)
        except InstagramError as error:
            self._failure("account_discovery",error)
        except SQLAlchemyError:
            if not dry_run: self.db.rollback()
            self._failure("database",InstagramDatabaseError("collector","persistence"))
        result["failures"]=len(self.failures)
        result["failure_details"]=self.failures
        if not dry_run:
            result["account_snapshots"]=self.db.scalar(select(func.count()).select_from(AccountSnapshot).where(AccountSnapshot.collection_run_id==run.id))
            result["content_snapshots"]=self.db.scalar(select(func.count()).select_from(ContentSnapshot).where(ContentSnapshot.collection_run_id==run.id))
        if self.failures:
            result["status"]="partial" if result["content_snapshots"] or result["account_snapshots"] else "failed"
        if run:
            run.status=CollectorStatus(result["status"])
            run.finished_at=utc_now()
            run.error_type=self.failures[0]["error_type"] if self.failures else None
            run.error_message_safe="One or more collection operations failed; see safe failure_details" if self.failures else None
            run.summary=result
            self.db.commit()
        return result

    def _previous_errors(self,snapshot,item,metrics,previous):
        raw=(snapshot.raw_payload or {}).get("insights",{})
        for metric in metrics:
            if metric not in raw:
                prior=next((failure for failure in previous if failure["item"]==item and failure["metric"]==metric),None)
                if prior: self.failures.append(prior)
                else: self._failure(item,InstagramUnavailableMetricError("insights","previous_partial_snapshot"),metric)

    @staticmethod
    def _status(values,errors):
        if errors: return DataStatus.UNAVAILABLE
        if values.get("reach") is not None: return DataStatus.ESTIMATED
        if any(value is not None for value in values.values()): return DataStatus.CONFIRMED
        return DataStatus.UNAVAILABLE

    @staticmethod
    def _notes(values,errors):
        notes=[]
        if values.get("reach") is not None: notes.append("reach is estimated; it is not unique_viewers")
        if errors: notes.append("Some metrics unavailable; raw contains successful responses only")
        return "; ".join(notes) or None
