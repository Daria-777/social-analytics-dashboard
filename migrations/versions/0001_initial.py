"""Initial accounts, content, immutable snapshots and experiments."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('experiments',
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('hypothesis', sa.Text(), nullable=True),
    sa.Column('metric', sa.Text(), nullable=True),
    sa.Column('status', sa.Enum('draft', 'running', 'completed', 'stopped', name='experimentstatus', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at', name='ck_experiment_dates'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('social_accounts',
    sa.Column('platform', sa.Enum('instagram', 'tiktok', name='platform', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('username', sa.Text(), nullable=False),
    sa.Column('platform_account_id', sa.Text(), nullable=False),
    sa.Column('account_type', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'platform', name='uq_account_id_platform'),
    sa.UniqueConstraint('platform', 'platform_account_id', name='uq_account_platform_id')
    )
    op.create_table('account_snapshots',
    sa.Column('account_id', sa.Uuid(), nullable=False),
    sa.Column('followers', sa.BigInteger(), nullable=True),
    sa.Column('following', sa.BigInteger(), nullable=True),
    sa.Column('views', sa.BigInteger(), nullable=True),
    sa.Column('unique_viewers', sa.BigInteger(), nullable=True),
    sa.Column('profile_views', sa.BigInteger(), nullable=True),
    sa.Column('likes', sa.BigInteger(), nullable=True),
    sa.Column('comments', sa.BigInteger(), nullable=True),
    sa.Column('shares', sa.BigInteger(), nullable=True),
    sa.Column('saves', sa.BigInteger(), nullable=True),
    sa.Column('new_viewers', sa.BigInteger(), nullable=True),
    sa.Column('snapshot_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('source', sa.Enum('instagram_api', 'instagram_ui', 'tiktok_api', 'tiktok_studio', 'manual', name='source', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('source_period_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source_period_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('snapshot_status', sa.Enum('confirmed', 'processing', 'unavailable', 'anomalous', 'estimated', 'manual', name='datastatus', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('raw_payload', sa.JSON(none_as_null=True).with_variant(postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('comments IS NULL OR comments >= 0', name='ck_account_snapshots_comments'),
    sa.CheckConstraint('followers IS NULL OR followers >= 0', name='ck_account_snapshots_followers'),
    sa.CheckConstraint('following IS NULL OR following >= 0', name='ck_account_snapshots_following'),
    sa.CheckConstraint('likes IS NULL OR likes >= 0', name='ck_account_snapshots_likes'),
    sa.CheckConstraint('new_viewers IS NULL OR new_viewers >= 0', name='ck_account_snapshots_new_viewers'),
    sa.CheckConstraint('profile_views IS NULL OR profile_views >= 0', name='ck_account_snapshots_profile_views'),
    sa.CheckConstraint('saves IS NULL OR saves >= 0', name='ck_account_snapshots_saves'),
    sa.CheckConstraint('shares IS NULL OR shares >= 0', name='ck_account_snapshots_shares'),
    sa.CheckConstraint('source_period_end IS NULL OR source_period_start IS NULL OR source_period_end >= source_period_start', name='ck_account_snapshots_period'),
    sa.CheckConstraint('unique_viewers IS NULL OR unique_viewers >= 0', name='ck_account_snapshots_unique_viewers'),
    sa.CheckConstraint('views IS NULL OR views >= 0', name='ck_account_snapshots_views'),
    sa.ForeignKeyConstraint(['account_id'], ['social_accounts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_account_snapshots_account_id'), 'account_snapshots', ['account_id'], unique=False)
    op.create_index(op.f('ix_account_snapshots_snapshot_at'), 'account_snapshots', ['snapshot_at'], unique=False)
    op.create_index(op.f('ix_account_snapshots_source'), 'account_snapshots', ['source'], unique=False)
    op.create_table('content',
    sa.Column('account_id', sa.Uuid(), nullable=False),
    sa.Column('platform', sa.Enum('instagram', 'tiktok', name='platform', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('platform_content_id', sa.Text(), nullable=False),
    sa.Column('content_type', sa.Enum('video', 'reel', 'photo', 'carousel', 'story', 'other', name='contenttype', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('duration_seconds', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('caption', sa.Text(), nullable=True),
    sa.Column('permalink', sa.Text(), nullable=True),
    sa.Column('experiment_id', sa.Uuid(), nullable=True),
    sa.Column('internal_title', sa.Text(), nullable=True),
    sa.Column('concept', sa.Text(), nullable=True),
    sa.Column('content_pillar', sa.Text(), nullable=True),
    sa.Column('series', sa.Text(), nullable=True),
    sa.Column('topic', sa.Text(), nullable=True),
    sa.Column('hook_type', sa.Text(), nullable=True),
    sa.Column('hook_text', sa.Text(), nullable=True),
    sa.Column('story_structure', sa.Text(), nullable=True),
    sa.Column('format', sa.Text(), nullable=True),
    sa.Column('cta_type', sa.Text(), nullable=True),
    sa.Column('production_version', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('duration_seconds IS NULL OR duration_seconds >= 0', name='ck_content_duration'),
    sa.ForeignKeyConstraint(['account_id', 'platform'], ['social_accounts.id', 'social_accounts.platform'], name='fk_content_account_platform'),
    sa.ForeignKeyConstraint(['experiment_id'], ['experiments.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('platform', 'platform_content_id', name='uq_content_platform_id')
    )
    op.create_index(op.f('ix_content_account_id'), 'content', ['account_id'], unique=False)
    op.create_index(op.f('ix_content_platform_content_id'), 'content', ['platform_content_id'], unique=False)
    op.create_table('content_experiments',
    sa.Column('content_id', sa.Uuid(), nullable=False),
    sa.Column('experiment_id', sa.Uuid(), nullable=False),
    sa.Column('variant', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['content_id'], ['content.id'], ),
    sa.ForeignKeyConstraint(['experiment_id'], ['experiments.id'], ),
    sa.PrimaryKeyConstraint('content_id', 'experiment_id')
    )
    op.create_index(op.f('ix_content_experiments_content_id'), 'content_experiments', ['content_id'], unique=False)
    op.create_table('content_snapshots',
    sa.Column('content_id', sa.Uuid(), nullable=False),
    sa.Column('views', sa.BigInteger(), nullable=True),
    sa.Column('unique_viewers', sa.BigInteger(), nullable=True),
    sa.Column('likes', sa.BigInteger(), nullable=True),
    sa.Column('comments', sa.BigInteger(), nullable=True),
    sa.Column('shares', sa.BigInteger(), nullable=True),
    sa.Column('saves', sa.BigInteger(), nullable=True),
    sa.Column('followers_gained', sa.BigInteger(), nullable=True),
    sa.Column('profile_visits', sa.BigInteger(), nullable=True),
    sa.Column('watch_time_total_seconds', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('watch_time_avg_seconds', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('completion_rate', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('traffic_for_you_pct', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('traffic_profile_pct', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('traffic_search_pct', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('traffic_following_pct', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('traffic_other_pct', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('new_viewers_pct', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('returning_viewers_pct', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('female_pct', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('male_pct', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('other_gender_pct', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('age_18_24_pct', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('age_25_34_pct', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('age_35_44_pct', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('age_45_54_pct', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('age_55_plus_pct', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('snapshot_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('source', sa.Enum('instagram_api', 'instagram_ui', 'tiktok_api', 'tiktok_studio', 'manual', name='source', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('source_period_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source_period_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('snapshot_status', sa.Enum('confirmed', 'processing', 'unavailable', 'anomalous', 'estimated', 'manual', name='datastatus', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('raw_payload', sa.JSON(none_as_null=True).with_variant(postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('age_18_24_pct IS NULL OR age_18_24_pct BETWEEN 0 AND 100', name='ck_content_snapshots_age_18_24_pct'),
    sa.CheckConstraint('age_25_34_pct IS NULL OR age_25_34_pct BETWEEN 0 AND 100', name='ck_content_snapshots_age_25_34_pct'),
    sa.CheckConstraint('age_35_44_pct IS NULL OR age_35_44_pct BETWEEN 0 AND 100', name='ck_content_snapshots_age_35_44_pct'),
    sa.CheckConstraint('age_45_54_pct IS NULL OR age_45_54_pct BETWEEN 0 AND 100', name='ck_content_snapshots_age_45_54_pct'),
    sa.CheckConstraint('age_55_plus_pct IS NULL OR age_55_plus_pct BETWEEN 0 AND 100', name='ck_content_snapshots_age_55_plus_pct'),
    sa.CheckConstraint('comments IS NULL OR comments >= 0', name='ck_content_snapshots_comments'),
    sa.CheckConstraint('completion_rate IS NULL OR completion_rate BETWEEN 0 AND 100', name='ck_content_snapshots_completion_rate'),
    sa.CheckConstraint('female_pct IS NULL OR female_pct BETWEEN 0 AND 100', name='ck_content_snapshots_female_pct'),
    sa.CheckConstraint('followers_gained IS NULL OR followers_gained >= 0', name='ck_content_snapshots_followers_gained'),
    sa.CheckConstraint('likes IS NULL OR likes >= 0', name='ck_content_snapshots_likes'),
    sa.CheckConstraint('male_pct IS NULL OR male_pct BETWEEN 0 AND 100', name='ck_content_snapshots_male_pct'),
    sa.CheckConstraint('new_viewers_pct IS NULL OR new_viewers_pct BETWEEN 0 AND 100', name='ck_content_snapshots_new_viewers_pct'),
    sa.CheckConstraint('other_gender_pct IS NULL OR other_gender_pct BETWEEN 0 AND 100', name='ck_content_snapshots_other_gender_pct'),
    sa.CheckConstraint('profile_visits IS NULL OR profile_visits >= 0', name='ck_content_snapshots_profile_visits'),
    sa.CheckConstraint('returning_viewers_pct IS NULL OR returning_viewers_pct BETWEEN 0 AND 100', name='ck_content_snapshots_returning_viewers_pct'),
    sa.CheckConstraint('saves IS NULL OR saves >= 0', name='ck_content_snapshots_saves'),
    sa.CheckConstraint('shares IS NULL OR shares >= 0', name='ck_content_snapshots_shares'),
    sa.CheckConstraint('source_period_end IS NULL OR source_period_start IS NULL OR source_period_end >= source_period_start', name='ck_content_snapshots_period'),
    sa.CheckConstraint('traffic_following_pct IS NULL OR traffic_following_pct BETWEEN 0 AND 100', name='ck_content_snapshots_traffic_following_pct'),
    sa.CheckConstraint('traffic_for_you_pct IS NULL OR traffic_for_you_pct BETWEEN 0 AND 100', name='ck_content_snapshots_traffic_for_you_pct'),
    sa.CheckConstraint('traffic_other_pct IS NULL OR traffic_other_pct BETWEEN 0 AND 100', name='ck_content_snapshots_traffic_other_pct'),
    sa.CheckConstraint('traffic_profile_pct IS NULL OR traffic_profile_pct BETWEEN 0 AND 100', name='ck_content_snapshots_traffic_profile_pct'),
    sa.CheckConstraint('traffic_search_pct IS NULL OR traffic_search_pct BETWEEN 0 AND 100', name='ck_content_snapshots_traffic_search_pct'),
    sa.CheckConstraint('unique_viewers IS NULL OR unique_viewers >= 0', name='ck_content_snapshots_unique_viewers'),
    sa.CheckConstraint('views IS NULL OR views >= 0', name='ck_content_snapshots_views'),
    sa.CheckConstraint('watch_time_avg_seconds IS NULL OR watch_time_avg_seconds >= 0', name='ck_content_snapshots_watch_time_avg_seconds'),
    sa.CheckConstraint('watch_time_total_seconds IS NULL OR watch_time_total_seconds >= 0', name='ck_content_snapshots_watch_time_total_seconds'),
    sa.ForeignKeyConstraint(['content_id'], ['content.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_content_snapshots_content_id'), 'content_snapshots', ['content_id'], unique=False)
    op.create_index(op.f('ix_content_snapshots_snapshot_at'), 'content_snapshots', ['snapshot_at'], unique=False)
    op.create_index(op.f('ix_content_snapshots_source'), 'content_snapshots', ['source'], unique=False)
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION reject_snapshot_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'Snapshots are append-only';
            END;
            $$
        """)
        for table in ("account_snapshots", "content_snapshots"):
            op.execute(f"CREATE TRIGGER immutable_snapshot BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_snapshot_mutation()")


def downgrade():
    op.drop_index(op.f('ix_content_snapshots_source'), table_name='content_snapshots')
    op.drop_index(op.f('ix_content_snapshots_snapshot_at'), table_name='content_snapshots')
    op.drop_index(op.f('ix_content_snapshots_content_id'), table_name='content_snapshots')
    op.drop_table('content_snapshots')
    op.drop_index(op.f('ix_content_experiments_content_id'), table_name='content_experiments')
    op.drop_table('content_experiments')
    op.drop_index(op.f('ix_content_platform_content_id'), table_name='content')
    op.drop_index(op.f('ix_content_account_id'), table_name='content')
    op.drop_table('content')
    op.drop_index(op.f('ix_account_snapshots_source'), table_name='account_snapshots')
    op.drop_index(op.f('ix_account_snapshots_snapshot_at'), table_name='account_snapshots')
    op.drop_index(op.f('ix_account_snapshots_account_id'), table_name='account_snapshots')
    op.drop_table('account_snapshots')
    op.drop_table('social_accounts')
    op.drop_table('experiments')
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION reject_snapshot_mutation()")
