"""Dashboard review markers, separate from immutable analytics snapshots."""
from alembic import op
import sqlalchemy as sa

revision='0005'
down_revision='0004'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('comment_reviews',
        sa.Column('content_id',sa.Uuid(),sa.ForeignKey('content.id'),primary_key=True),
        sa.Column('snapshot_id',sa.Uuid(),sa.ForeignKey('content_snapshots.id'),nullable=False),
        sa.Column('snapshot_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('snapshot_created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('comments',sa.BigInteger(),nullable=False),
        sa.Column('reviewed_at',sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint('comments >= 0',name='ck_comment_review_count'))


def downgrade():
    op.drop_table('comment_reviews')
