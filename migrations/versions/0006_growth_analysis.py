"""Append-only analytical results and atomic agent delivery receipts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision='0006'
down_revision='0005'
branch_labels=None
depends_on=None


def upgrade():
    json_type=sa.JSON().with_variant(JSONB(),'postgresql')
    op.create_table('growth_analyses',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('content_id',sa.Uuid(),sa.ForeignKey('content.id'),nullable=False),
        sa.Column('agent_run_id',sa.Uuid(),nullable=False),
        sa.Column('request_hash',sa.Text(),nullable=False),
        sa.Column('analysis_snapshot_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('data_cutoff_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('agent_version',sa.Text(),nullable=False),
        sa.Column('hypothesis_status',sa.Text(),nullable=False),
        sa.Column('confidence',sa.Text(),nullable=False),
        sa.Column('result',json_type,nullable=False),
        sa.Column('provenance',json_type,nullable=False),
        sa.UniqueConstraint('content_id','agent_run_id',name='uq_growth_content_run'),
        sa.CheckConstraint('data_cutoff_at <= analysis_snapshot_at',name='ck_growth_cutoff'),
        sa.CheckConstraint("hypothesis_status IN ('SUPPORTED','PARTIALLY_SUPPORTED','NOT_SUPPORTED','INCONCLUSIVE')",name='ck_growth_hypothesis'),
        sa.CheckConstraint("confidence IN ('LOW','MEDIUM','HIGH')",name='ck_growth_confidence'),
    )
    op.create_index('ix_growth_analyses_content_id','growth_analyses',['content_id'])
    op.create_table('agent_imports',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('agent_run_id',sa.Uuid(),nullable=False),
        sa.Column('request_hash',sa.Text(),nullable=False),
        sa.Column('response',json_type,nullable=False),
        sa.UniqueConstraint('agent_run_id',name='uq_agent_import_run'),
    )
    if op.get_bind().dialect.name=='postgresql':
        for table in ('growth_analyses','agent_imports'):
            op.execute(f'CREATE TRIGGER immutable_snapshot BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_snapshot_mutation()')


def downgrade():
    op.drop_table('agent_imports')
    op.drop_table('growth_analyses')
