"""Optional provider image URL on current content metadata, never snapshots."""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('content', sa.Column('preview_url', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('content', 'preview_url')
