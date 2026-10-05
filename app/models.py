from decimal import Decimal
from uuid import UUID, uuid4
from datetime import datetime
from sqlalchemy import (BigInteger, CheckConstraint, Enum, ForeignKey, ForeignKeyConstraint,
                        JSON, Numeric, Text, UniqueConstraint, Uuid, event)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from app.enums import Platform, ContentType, Source, DataStatus, ExperimentStatus, CollectorStatus
from app.types import UTCDateTime, utc_now


def enum_type(cls):
    return Enum(cls, values_callable=lambda values: [v.value for v in values],
                native_enum=False, create_constraint=True, name=cls.__name__.lower())


class Base(DeclarativeBase):
    pass


class Identity:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class Updated:
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class SocialAccount(Identity, Updated, Base):
    __tablename__ = "social_accounts"
    __table_args__ = (
        UniqueConstraint("platform", "platform_account_id", name="uq_account_platform_id"),
        UniqueConstraint("id", "platform", name="uq_account_id_platform"),
    )
    platform: Mapped[Platform] = mapped_column(enum_type(Platform))
    username: Mapped[str] = mapped_column(Text)
    platform_account_id: Mapped[str] = mapped_column(Text)
    account_type: Mapped[str | None] = mapped_column(Text)


class Experiment(Identity, Base):
    __tablename__ = "experiments"
    __table_args__ = (CheckConstraint("ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at", name="ck_experiment_dates"),)
    name: Mapped[str] = mapped_column(Text)
    hypothesis: Mapped[str | None] = mapped_column(Text)
    metric: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ExperimentStatus] = mapped_column(enum_type(ExperimentStatus), default=ExperimentStatus.DRAFT)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    notes: Mapped[str | None] = mapped_column(Text)


class Content(Identity, Updated, Base):
    __tablename__ = "content"
    __table_args__ = (
        UniqueConstraint("platform", "platform_content_id", name="uq_content_platform_id"),
        ForeignKeyConstraint(["account_id", "platform"], ["social_accounts.id", "social_accounts.platform"], name="fk_content_account_platform"),
        CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="ck_content_duration"),
    )
    account_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    platform: Mapped[Platform] = mapped_column(enum_type(Platform))
    platform_content_id: Mapped[str] = mapped_column(Text, index=True)
    content_type: Mapped[ContentType] = mapped_column(enum_type(ContentType))
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    caption: Mapped[str | None] = mapped_column(Text)
    permalink: Mapped[str | None] = mapped_column(Text)
    preview_url: Mapped[str | None] = mapped_column(Text)
    experiment_id: Mapped[UUID | None] = mapped_column(ForeignKey("experiments.id"))
    internal_title: Mapped[str | None] = mapped_column(Text)
    concept: Mapped[str | None] = mapped_column(Text)
    content_pillar: Mapped[str | None] = mapped_column(Text)
    series: Mapped[str | None] = mapped_column(Text)
    topic: Mapped[str | None] = mapped_column(Text)
    hook_type: Mapped[str | None] = mapped_column(Text)
    hook_text: Mapped[str | None] = mapped_column(Text)
    story_structure: Mapped[str | None] = mapped_column(Text)
    format: Mapped[str | None] = mapped_column(Text)
    cta_type: Mapped[str | None] = mapped_column(Text)
    production_version: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class CollectorRun(Identity, Base):
    __tablename__ = "collector_runs"
    platform_account_id: Mapped[str | None] = mapped_column(Text)
    platform: Mapped[Platform] = mapped_column(enum_type(Platform), index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[CollectorStatus] = mapped_column(enum_type(CollectorStatus), default=CollectorStatus.RUNNING)
    error_type: Mapped[str | None] = mapped_column(Text)
    error_message_safe: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict | None] = mapped_column(JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"))


class Snapshot(Identity):
    collection_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("collector_runs.id"), index=True)
    metric_scope: Mapped[str | None] = mapped_column(Text)
    reach: Mapped[int | None] = mapped_column(BigInteger)
    snapshot_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    source: Mapped[Source] = mapped_column(enum_type(Source), index=True)
    source_period_start: Mapped[datetime | None] = mapped_column(UTCDateTime())
    source_period_end: Mapped[datetime | None] = mapped_column(UTCDateTime())
    snapshot_status: Mapped[DataStatus] = mapped_column(enum_type(DataStatus), default=DataStatus.MANUAL)
    notes: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict | None] = mapped_column(JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"))


class AccountSnapshot(Snapshot, Base):
    __tablename__ = "account_snapshots"
    __table_args__ = (
        UniqueConstraint("account_id", "collection_run_id", "metric_scope", name="uq_account_run_scope"),
        CheckConstraint("reach IS NULL OR reach >= 0", name="ck_account_snapshots_reach"),
        CheckConstraint("collection_run_id IS NULL OR metric_scope IS NOT NULL", name="ck_account_run_scope"),
        CheckConstraint("followers IS NULL OR followers >= 0", name="ck_account_snapshots_followers"),
        CheckConstraint("following IS NULL OR following >= 0", name="ck_account_snapshots_following"),
        CheckConstraint("views IS NULL OR views >= 0", name="ck_account_snapshots_views"),
        CheckConstraint("unique_viewers IS NULL OR unique_viewers >= 0", name="ck_account_snapshots_unique_viewers"),
        CheckConstraint("profile_views IS NULL OR profile_views >= 0", name="ck_account_snapshots_profile_views"),
        CheckConstraint("likes IS NULL OR likes >= 0", name="ck_account_snapshots_likes"),
        CheckConstraint("comments IS NULL OR comments >= 0", name="ck_account_snapshots_comments"),
        CheckConstraint("shares IS NULL OR shares >= 0", name="ck_account_snapshots_shares"),
        CheckConstraint("saves IS NULL OR saves >= 0", name="ck_account_snapshots_saves"),
        CheckConstraint("new_viewers IS NULL OR new_viewers >= 0", name="ck_account_snapshots_new_viewers"),
        CheckConstraint("source_period_end IS NULL OR source_period_start IS NULL OR source_period_end >= source_period_start", name="ck_account_snapshots_period"),
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey("social_accounts.id"), index=True)
    followers: Mapped[int | None] = mapped_column(BigInteger)
    following: Mapped[int | None] = mapped_column(BigInteger)
    views: Mapped[int | None] = mapped_column(BigInteger)
    unique_viewers: Mapped[int | None] = mapped_column(BigInteger)
    profile_views: Mapped[int | None] = mapped_column(BigInteger)
    likes: Mapped[int | None] = mapped_column(BigInteger)
    comments: Mapped[int | None] = mapped_column(BigInteger)
    shares: Mapped[int | None] = mapped_column(BigInteger)
    saves: Mapped[int | None] = mapped_column(BigInteger)
    new_viewers: Mapped[int | None] = mapped_column(BigInteger)


class ContentSnapshot(Snapshot, Base):
    __tablename__ = "content_snapshots"
    __table_args__ = (
        UniqueConstraint("content_id", "collection_run_id", name="uq_content_run"),
        CheckConstraint("reach IS NULL OR reach >= 0", name="ck_content_snapshots_reach"),
        CheckConstraint("profile_activity IS NULL OR profile_activity >= 0", name="ck_content_snapshots_profile_activity"),
        CheckConstraint("views IS NULL OR views >= 0", name="ck_content_snapshots_views"),
        CheckConstraint("unique_viewers IS NULL OR unique_viewers >= 0", name="ck_content_snapshots_unique_viewers"),
        CheckConstraint("likes IS NULL OR likes >= 0", name="ck_content_snapshots_likes"),
        CheckConstraint("comments IS NULL OR comments >= 0", name="ck_content_snapshots_comments"),
        CheckConstraint("shares IS NULL OR shares >= 0", name="ck_content_snapshots_shares"),
        CheckConstraint("saves IS NULL OR saves >= 0", name="ck_content_snapshots_saves"),
        CheckConstraint("followers_gained IS NULL OR followers_gained >= 0", name="ck_content_snapshots_followers_gained"),
        CheckConstraint("profile_visits IS NULL OR profile_visits >= 0", name="ck_content_snapshots_profile_visits"),
        CheckConstraint("watch_time_total_seconds IS NULL OR watch_time_total_seconds >= 0", name="ck_content_snapshots_watch_time_total_seconds"),
        CheckConstraint("watch_time_avg_seconds IS NULL OR watch_time_avg_seconds >= 0", name="ck_content_snapshots_watch_time_avg_seconds"),
        CheckConstraint("completion_rate IS NULL OR completion_rate BETWEEN 0 AND 100", name="ck_content_snapshots_completion_rate"),
        CheckConstraint("traffic_for_you_pct IS NULL OR traffic_for_you_pct BETWEEN 0 AND 100", name="ck_content_snapshots_traffic_for_you_pct"),
        CheckConstraint("traffic_profile_pct IS NULL OR traffic_profile_pct BETWEEN 0 AND 100", name="ck_content_snapshots_traffic_profile_pct"),
        CheckConstraint("traffic_search_pct IS NULL OR traffic_search_pct BETWEEN 0 AND 100", name="ck_content_snapshots_traffic_search_pct"),
        CheckConstraint("traffic_following_pct IS NULL OR traffic_following_pct BETWEEN 0 AND 100", name="ck_content_snapshots_traffic_following_pct"),
        CheckConstraint("traffic_other_pct IS NULL OR traffic_other_pct BETWEEN 0 AND 100", name="ck_content_snapshots_traffic_other_pct"),
        CheckConstraint("new_viewers_pct IS NULL OR new_viewers_pct BETWEEN 0 AND 100", name="ck_content_snapshots_new_viewers_pct"),
        CheckConstraint("returning_viewers_pct IS NULL OR returning_viewers_pct BETWEEN 0 AND 100", name="ck_content_snapshots_returning_viewers_pct"),
        CheckConstraint("female_pct IS NULL OR female_pct BETWEEN 0 AND 100", name="ck_content_snapshots_female_pct"),
        CheckConstraint("male_pct IS NULL OR male_pct BETWEEN 0 AND 100", name="ck_content_snapshots_male_pct"),
        CheckConstraint("other_gender_pct IS NULL OR other_gender_pct BETWEEN 0 AND 100", name="ck_content_snapshots_other_gender_pct"),
        CheckConstraint("age_18_24_pct IS NULL OR age_18_24_pct BETWEEN 0 AND 100", name="ck_content_snapshots_age_18_24_pct"),
        CheckConstraint("age_25_34_pct IS NULL OR age_25_34_pct BETWEEN 0 AND 100", name="ck_content_snapshots_age_25_34_pct"),
        CheckConstraint("age_35_44_pct IS NULL OR age_35_44_pct BETWEEN 0 AND 100", name="ck_content_snapshots_age_35_44_pct"),
        CheckConstraint("age_45_54_pct IS NULL OR age_45_54_pct BETWEEN 0 AND 100", name="ck_content_snapshots_age_45_54_pct"),
        CheckConstraint("age_55_plus_pct IS NULL OR age_55_plus_pct BETWEEN 0 AND 100", name="ck_content_snapshots_age_55_plus_pct"),
        CheckConstraint("source_period_end IS NULL OR source_period_start IS NULL OR source_period_end >= source_period_start", name="ck_content_snapshots_period"),
    )
    profile_activity: Mapped[int | None] = mapped_column(BigInteger)
    content_id: Mapped[UUID] = mapped_column(ForeignKey("content.id"), index=True)
    views: Mapped[int | None] = mapped_column(BigInteger)
    unique_viewers: Mapped[int | None] = mapped_column(BigInteger)
    likes: Mapped[int | None] = mapped_column(BigInteger)
    comments: Mapped[int | None] = mapped_column(BigInteger)
    shares: Mapped[int | None] = mapped_column(BigInteger)
    saves: Mapped[int | None] = mapped_column(BigInteger)
    followers_gained: Mapped[int | None] = mapped_column(BigInteger)
    profile_visits: Mapped[int | None] = mapped_column(BigInteger)
    watch_time_total_seconds: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    watch_time_avg_seconds: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    completion_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    traffic_for_you_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    traffic_profile_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    traffic_search_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    traffic_following_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    traffic_other_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    new_viewers_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    returning_viewers_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    female_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    male_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    other_gender_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    age_18_24_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    age_25_34_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    age_35_44_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    age_45_54_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    age_55_plus_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))


class ContentExperiment(Base):
    __tablename__ = "content_experiments"
    content_id: Mapped[UUID] = mapped_column(ForeignKey("content.id"), primary_key=True, index=True)
    experiment_id: Mapped[UUID] = mapped_column(ForeignKey("experiments.id"), primary_key=True)
    variant: Mapped[str | None] = mapped_column(Text)


class ContentRetentionSnapshot(Identity, Base):
    __tablename__ = "content_retention_snapshots"
    __table_args__ = (
        CheckConstraint("drop_off_second IS NULL OR drop_off_second >= 0", name="ck_retention_dropoff"),
        CheckConstraint("average_watch_seconds IS NULL OR average_watch_seconds >= 0", name="ck_retention_average"),
        CheckConstraint("completion_rate IS NULL OR completion_rate BETWEEN 0 AND 100", name="ck_retention_completion"),
        CheckConstraint("source_period_end IS NULL OR source_period_start IS NULL OR source_period_end >= source_period_start", name="ck_retention_period"),
    )
    content_id: Mapped[UUID] = mapped_column(ForeignKey("content.id"), index=True)
    snapshot_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    source: Mapped[Source] = mapped_column(enum_type(Source), index=True)
    source_period_start: Mapped[datetime | None] = mapped_column(UTCDateTime())
    source_period_end: Mapped[datetime | None] = mapped_column(UTCDateTime())
    snapshot_status: Mapped[DataStatus] = mapped_column(enum_type(DataStatus), default=DataStatus.MANUAL)
    drop_off_second: Mapped[Decimal | None] = mapped_column(Numeric(20,6))
    average_watch_seconds: Mapped[Decimal | None] = mapped_column(Numeric(20,6))
    completion_rate: Mapped[Decimal | None] = mapped_column(Numeric(20,6))
    notes: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict | None] = mapped_column(JSON(none_as_null=True).with_variant(JSONB(none_as_null=True),"postgresql"))


class ContentGeoSnapshot(Identity, Base):
    __tablename__ = "content_geo_snapshots"
    __table_args__ = (
        UniqueConstraint("content_snapshot_id","country_code",name="uq_geo_snapshot_country"),
        CheckConstraint("percentage IS NULL OR percentage BETWEEN 0 AND 100",name="ck_geo_percentage"),
    )
    content_snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("content_snapshots.id"),index=True)
    country_code: Mapped[str] = mapped_column(Text)
    country_name: Mapped[str | None] = mapped_column(Text)
    percentage: Mapped[Decimal | None] = mapped_column(Numeric(20,6))


def reject_snapshot_mutation(mapper, connection, target):
    raise ValueError("Snapshots are append-only; add a new observation instead")


for snapshot_model in (AccountSnapshot, ContentSnapshot, ContentRetentionSnapshot, ContentGeoSnapshot):
    event.listen(snapshot_model, "before_update", reject_snapshot_mutation)
    event.listen(snapshot_model, "before_delete", reject_snapshot_mutation)
