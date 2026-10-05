"""Shared persistence invariants; platform fetch/mapping remains in each connector."""
from sqlalchemy import select,update
from sqlalchemy.exc import IntegrityError
from app.models import SocialAccount,Content,CollectorRun
from app.enums import Platform,ContentType,CollectorStatus
from app.types import utc_now
from app.preview import safe_preview_url
from app.connectors.instagram.mapper import sanitize


class CollectionBusyError(ValueError): pass


class CollectorPersistence:
    def _reserve(self,run_id):
        run=self.db.get(CollectorRun,run_id)
        if run:
            if run.platform!=self.platform: raise ValueError("Run belongs to another platform")
            if run.status==CollectorStatus.SUCCESS: return run,True
            if run.status==CollectorStatus.RUNNING: raise CollectionBusyError("Collection run is already running; operator recovery required after a crash")
            previous=run.status
            claimed=self.db.execute(update(CollectorRun).where(CollectorRun.id==run_id,CollectorRun.status==previous).values(status=CollectorStatus.RUNNING,finished_at=None,error_type=None,error_message_safe=None))
            if claimed.rowcount!=1:
                self.db.rollback(); raise CollectionBusyError("Collection run is already claimed")
            self.db.commit()
            self.db.refresh(run)
            return run,False
        run=CollectorRun(id=run_id,platform=self.platform,started_at=utc_now(),status=CollectorStatus.RUNNING)
        self.db.add(run)
        try: self.db.commit()
        except IntegrityError:
            self.db.rollback(); raise CollectionBusyError("Collection run already exists") from None
        self.db.refresh(run)
        return run,False

    def _upsert_account(self,dto):
        row=self.db.scalar(select(SocialAccount).where(SocialAccount.platform==self.platform,SocialAccount.platform_account_id==dto.platform_account_id))
        if row is None:
            row=SocialAccount(platform=self.platform,platform_account_id=dto.platform_account_id,username=dto.username,account_type=dto.account_type)
            try:
                with self.db.begin_nested(): self.db.add(row); self.db.flush()
            except IntegrityError:
                row=self.db.scalar(select(SocialAccount).where(SocialAccount.platform==self.platform,SocialAccount.platform_account_id==dto.platform_account_id))
                if row is None: raise
        row.username=dto.username
        if dto.account_type is not None: row.account_type=dto.account_type
        self.db.commit(); return row

    def _upsert_content(self,account,dto):
        row=self.db.scalar(select(Content).where(Content.platform==self.platform,Content.platform_content_id==dto.platform_content_id))
        created=False
        if row is None:
            row=Content(account_id=account.id,platform=self.platform,platform_content_id=dto.platform_content_id,content_type=dto.content_type)
            try:
                with self.db.begin_nested(): self.db.add(row); self.db.flush()
                created=True
            except IntegrityError:
                row=self.db.scalar(select(Content).where(Content.platform==self.platform,Content.platform_content_id==dto.platform_content_id))
                if row is None: raise
        if row.account_id!=account.id: raise self.identity_error("media","manual_reconciliation_required")
        # No titles/tags/experiments overwritten. Null metadata never erases known values.
        ambiguous_video = dto.content_type == ContentType.VIDEO and dto.capability == "VIDEO"
        if not (self.platform == Platform.INSTAGRAM and ambiguous_video and row.content_type in (ContentType.REEL, ContentType.STORY)):
            row.content_type=dto.content_type
        # Insights capabilities still come exclusively from the current API DTO.
        for field in ("published_at","caption","permalink","preview_url"):
            value=getattr(dto,field)
            if field == "preview_url":
                # Signed CDN queries must not be reconstructed by sanitize().
                value = safe_preview_url(value)
                if value and any(secret and secret in value for secret in self.secrets): value = None
                if value is not None: row.preview_url = value
            elif value is not None: setattr(row,field,sanitize(value,self.secrets))
        self.db.commit(); return row,created

    def _snapshot_exists(self,model,parent,parent_id,run_id,scope=None):
        query=select(model).where(getattr(model,parent)==parent_id,model.collection_run_id==run_id)
        if scope: query=query.where(model.metric_scope==scope)
        return self.db.scalar(query)

    def _persist_snapshot(self,row):
        self.db.add(row)
        self.db.commit()
