"""Append-only UI retention and snapshot geography, separate from API metrics."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision='0003'
down_revision='0002'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('content_retention_snapshots',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('content_id',sa.Uuid(),sa.ForeignKey('content.id'),nullable=False),
        sa.Column('snapshot_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('source',sa.Enum('instagram_api','instagram_ui','tiktok_api','tiktok_studio','manual',name='source',native_enum=False,create_constraint=True),nullable=False),
        sa.Column('source_period_start',sa.DateTime(timezone=True)),
        sa.Column('source_period_end',sa.DateTime(timezone=True)),
        sa.Column('snapshot_status',sa.Enum('confirmed','processing','unavailable','anomalous','estimated','manual',name='datastatus',native_enum=False,create_constraint=True),nullable=False),
        sa.Column('drop_off_second',sa.Numeric(20,6)),
        sa.Column('average_watch_seconds',sa.Numeric(20,6)),
        sa.Column('completion_rate',sa.Numeric(20,6)),
        sa.Column('notes',sa.Text()),
        sa.Column('raw_payload',sa.JSON(none_as_null=True).with_variant(postgresql.JSONB(none_as_null=True),'postgresql')),
        sa.CheckConstraint('drop_off_second IS NULL OR drop_off_second >= 0',name='ck_retention_dropoff'),
        sa.CheckConstraint('average_watch_seconds IS NULL OR average_watch_seconds >= 0',name='ck_retention_average'),
        sa.CheckConstraint('completion_rate IS NULL OR completion_rate BETWEEN 0 AND 100',name='ck_retention_completion'),
        sa.CheckConstraint('source_period_end IS NULL OR source_period_start IS NULL OR source_period_end >= source_period_start',name='ck_retention_period'),
    )
    for key in ('content_id','snapshot_at','source'):
        op.create_index(f'ix_content_retention_snapshots_{key}','content_retention_snapshots',[key])
    op.create_table('content_geo_snapshots',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('content_snapshot_id',sa.Uuid(),sa.ForeignKey('content_snapshots.id'),nullable=False),
        sa.Column('country_code',sa.Text(),nullable=False),
        sa.Column('country_name',sa.Text()),
        sa.Column('percentage',sa.Numeric(20,6)),
        sa.UniqueConstraint('content_snapshot_id','country_code',name='uq_geo_snapshot_country'),
        sa.CheckConstraint('percentage IS NULL OR percentage BETWEEN 0 AND 100',name='ck_geo_percentage'),
    )
    op.create_index('ix_content_geo_snapshots_content_snapshot_id','content_geo_snapshots',['content_snapshot_id'])
    if op.get_bind().dialect.name=='postgresql':
        for table in ('content_retention_snapshots','content_geo_snapshots'):
            op.execute(f'CREATE TRIGGER immutable_snapshot BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_snapshot_mutation()')


def downgrade():
    op.drop_table('content_geo_snapshots')
    op.drop_table('content_retention_snapshots')
