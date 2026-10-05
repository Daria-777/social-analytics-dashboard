from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID
from pydantic import (BaseModel, ConfigDict, Field, AwareDatetime, AfterValidator, model_validator)
from app.enums import Platform, ContentType, Source, DataStatus, ExperimentStatus

UTCStamp = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(timezone.utc))]
Count = Annotated[int, Field(strict=True, ge=0, le=9223372036854775807)]
Seconds = Annotated[Decimal, Field(ge=0, max_digits=20, decimal_places=6, allow_inf_nan=False)]
Percentage = Annotated[Decimal, Field(ge=0, le=100, max_digits=20, decimal_places=6, allow_inf_nan=False)]
Nonempty = Annotated[str, Field(min_length=1)]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class AccountCreate(Schema):
    platform: Platform
    username: Nonempty
    platform_account_id: Nonempty
    account_type: str | None = None


class AccountRead(AccountCreate):
    id: UUID
    created_at: datetime
    updated_at: datetime


class ExperimentCreate(Schema):
    name: Nonempty
    hypothesis: str | None = None
    metric: str | None = None
    status: ExperimentStatus = ExperimentStatus.DRAFT
    started_at: UTCStamp | None = None
    ended_at: UTCStamp | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def dates(self):
        if self.started_at and self.ended_at and self.ended_at < self.started_at:
            raise ValueError("ended_at must be >= started_at")
        return self


class ExperimentRead(ExperimentCreate):
    id: UUID
    created_at: datetime


class ContentCreate(Schema):
    account_id: UUID
    platform: Platform
    platform_content_id: Nonempty
    content_type: ContentType
    published_at: UTCStamp | None = None
    duration_seconds: Seconds | None = None
    caption: str | None = None
    permalink: str | None = None
    preview_url: str | None = None
    experiment_id: UUID | None = None
    internal_title: str | None = None
    concept: str | None = None
    content_pillar: str | None = None
    series: str | None = None
    topic: str | None = None
    hook_type: str | None = None
    hook_text: str | None = None
    story_structure: str | None = None
    format: str | None = None
    cta_type: str | None = None
    production_version: str | None = None
    notes: str | None = None


class ContentRead(ContentCreate):
    id: UUID
    created_at: datetime
    updated_at: datetime


class SnapshotCreate(Schema):
    snapshot_at: UTCStamp
    source: Source
    source_period_start: UTCStamp | None = None
    source_period_end: UTCStamp | None = None
    snapshot_status: DataStatus = DataStatus.MANUAL
    notes: str | None = None
    raw_payload: dict | None = None

    @model_validator(mode="after")
    def period(self):
        if self.source_period_start and self.source_period_end and self.source_period_end < self.source_period_start:
            raise ValueError("source_period_end must be >= source_period_start")
        return self


class AccountSnapshotCreate(SnapshotCreate):
    account_id: UUID
    followers: Count | None = None
    following: Count | None = None
    views: Count | None = None
    unique_viewers: Count | None = None
    profile_views: Count | None = None
    likes: Count | None = None
    comments: Count | None = None
    shares: Count | None = None
    saves: Count | None = None
    new_viewers: Count | None = None


class AccountSnapshotRead(AccountSnapshotCreate):
    reach: Count | None = None
    metric_scope: str | None = None
    collection_run_id: UUID | None = None
    id: UUID
    created_at: datetime


class ContentSnapshotCreate(SnapshotCreate):
    content_id: UUID
    views: Count | None = None
    unique_viewers: Count | None = None
    likes: Count | None = None
    comments: Count | None = None
    shares: Count | None = None
    saves: Count | None = None
    followers_gained: Count | None = None
    profile_visits: Count | None = None
    watch_time_total_seconds: Seconds | None = None
    watch_time_avg_seconds: Seconds | None = None
    completion_rate: Percentage | None = None
    traffic_for_you_pct: Percentage | None = None
    traffic_profile_pct: Percentage | None = None
    traffic_search_pct: Percentage | None = None
    traffic_following_pct: Percentage | None = None
    traffic_other_pct: Percentage | None = None
    new_viewers_pct: Percentage | None = None
    returning_viewers_pct: Percentage | None = None
    female_pct: Percentage | None = None
    male_pct: Percentage | None = None
    other_gender_pct: Percentage | None = None
    age_18_24_pct: Percentage | None = None
    age_25_34_pct: Percentage | None = None
    age_35_44_pct: Percentage | None = None
    age_45_54_pct: Percentage | None = None
    age_55_plus_pct: Percentage | None = None


class ContentSnapshotRead(ContentSnapshotCreate):
    reach: Count | None = None
    profile_activity: Count | None = None
    metric_scope: str | None = None
    collection_run_id: UUID | None = None
    id: UUID
    created_at: datetime


class ContentExperimentCreate(Schema):
    content_id: UUID
    experiment_id: UUID
    variant: str | None = None


class GeographyCreate(Schema):
    country_code: Annotated[str, Field(pattern=r'^[A-Z]{2}$')]
    country_name: str | None = None
    percentage: Percentage | None = None


class GeographyRead(GeographyCreate):
    id: UUID
    content_snapshot_id: UUID
    created_at: datetime


class RetentionCreate(SnapshotCreate):
    content_id: UUID | None = None
    drop_off_second: Seconds | None = None
    average_watch_seconds: Seconds | None = None
    completion_rate: Percentage | None = None


class RetentionRead(RetentionCreate):
    id: UUID
    created_at: datetime


class ManualContentRecord(ContentSnapshotCreate):
    content_id: UUID | None = None
    platform: Platform
    platform_content_id: Nonempty
    metric_scope: Literal["lifetime","range"] | None = None
    geography: list[GeographyCreate] = Field(default_factory=list, max_length=300)


class ManualAccountRecord(AccountSnapshotCreate):
    metric_scope: Literal["current","range"] | None = None
    account_id: UUID | None = None
    platform: Platform
    platform_account_id: Nonempty


class ManualRetentionRecord(RetentionCreate):
    platform: Platform
    platform_content_id: Nonempty


class ImportBatch(Schema):
    version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    content_snapshots: list[ManualContentRecord] = Field(default_factory=list, max_length=1000)
    account_snapshots: list[ManualAccountRecord] = Field(default_factory=list, max_length=1000)
    retention_snapshots: list[ManualRetentionRecord] = Field(default_factory=list, max_length=1000)

    @model_validator(mode='after')
    def manual_sources(self):
        if not (self.content_snapshots or self.account_snapshots or self.retention_snapshots):
            raise ValueError('Import must contain observations')
        for record in [*self.content_snapshots,*self.account_snapshots,*self.retention_snapshots]:
            scope=getattr(record,'metric_scope',None)
            if scope=='range' and (record.source_period_start is None or record.source_period_end is None):
                raise ValueError('Range observations require both period boundaries')
            if scope in ('lifetime','current') and (record.source_period_start is not None or record.source_period_end is not None):
                raise ValueError('Lifetime/current observations must not contain range boundaries')
            if record.source not in (Source.MANUAL,Source.INSTAGRAM_UI,Source.TIKTOK_STUDIO):
                raise ValueError('Manual import accepts only manual/UI sources')
        return self


class ContentTagsPatch(Schema):
    internal_title: str | None = None
    concept: str | None = None
    content_pillar: str | None = None
    series: str | None = None
    topic: str | None = None
    hook_type: str | None = None
    hook_text: str | None = None
    story_structure: str | None = None
    format: str | None = None
    cta_type: str | None = None
    production_version: str | None = None
    experiment_id: UUID | None = None
    notes: str | None = None


class ExperimentPatch(Schema):
    name: Nonempty | None = None
    hypothesis: str | None = None
    metric: str | None = None
    status: ExperimentStatus | None = None
    started_at: UTCStamp | None = None
    ended_at: UTCStamp | None = None
    notes: str | None = None
