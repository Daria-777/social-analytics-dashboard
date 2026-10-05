"""Collector identity and source-specific reach/profile semantics."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("collector_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("platform_account_id",sa.Text(),nullable=True),
        sa.Column("platform", sa.Enum("instagram", "tiktok",name="platform",native_enum=False,create_constraint=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Enum("running","success","partial","failed",name="collectorstatus",native_enum=False,create_constraint=True), nullable=False),
        sa.Column("error_type", sa.Text()),
        sa.Column("error_message_safe", sa.Text()),
        sa.Column("summary", sa.JSON(none_as_null=True).with_variant(postgresql.JSONB(none_as_null=True),"postgresql")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_collector_runs_platform","collector_runs",["platform"])
    for table, parent, constraint in (("account_snapshots","account_id","uq_account_run_scope"),("content_snapshots","content_id","uq_content_run")):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("collection_run_id",sa.Uuid(),nullable=True))
            batch.add_column(sa.Column("metric_scope",sa.Text(),nullable=True))
            batch.add_column(sa.Column("reach",sa.BigInteger(),nullable=True))
            batch.create_foreign_key(f"fk_{table}_collector_run", "collector_runs", ["collection_run_id"],["id"])
            batch.create_index(f"ix_{table}_collection_run_id",["collection_run_id"])
            keys=[parent,"collection_run_id"] + (["metric_scope"] if parent=="account_id" else [])
            batch.create_unique_constraint(constraint,keys)
            batch.create_check_constraint(f"ck_{table}_reach","reach IS NULL OR reach >= 0")
            if parent=="account_id":
                batch.create_check_constraint("ck_account_run_scope","collection_run_id IS NULL OR metric_scope IS NOT NULL")
            if parent=="content_id":
                batch.add_column(sa.Column("profile_activity",sa.BigInteger(),nullable=True))
                batch.create_check_constraint("ck_content_snapshots_profile_activity","profile_activity IS NULL OR profile_activity >= 0")


def downgrade():
    for table, constraint in (("content_snapshots","uq_content_run"),("account_snapshots","uq_account_run_scope")):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(constraint,type_="unique")
            batch.drop_constraint(f"fk_{table}_collector_run",type_="foreignkey")
            batch.drop_index(f"ix_{table}_collection_run_id")
            batch.drop_constraint(f"ck_{table}_reach",type_="check")
            if table=="account_snapshots":
                batch.drop_constraint("ck_account_run_scope",type_="check")
            if table=="content_snapshots":
                batch.drop_constraint("ck_content_snapshots_profile_activity",type_="check")
                batch.drop_column("profile_activity")
            batch.drop_column("reach")
            batch.drop_column("metric_scope")
            batch.drop_column("collection_run_id")
    op.drop_index("ix_collector_runs_platform",table_name="collector_runs")
    op.drop_table("collector_runs")
