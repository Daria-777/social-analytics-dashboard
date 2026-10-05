from io import StringIO
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_migration_upgrade_downgrade_and_no_drift(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = create_engine(url)
    assert set(inspect(engine).get_table_names()) == {"alembic_version", "social_accounts", "content", "account_snapshots", "content_snapshots", "experiments", "content_experiments", "collector_runs", "content_retention_snapshots", "content_geo_snapshots"}
    assert 'preview_url' in {c['name'] for c in inspect(engine).get_columns('content')}
    command.check(config)
    engine.dispose()
    command.downgrade(config, "0003")
    engine = create_engine(url)
    assert 'preview_url' not in {c['name'] for c in inspect(engine).get_columns('content')}
    engine.dispose()
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    engine = create_engine(url)
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_postgres_migration_uses_jsonb_timestamptz_and_triggers(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://localhost/test_dash")
    output = StringIO()
    config = Config("alembic.ini", output_buffer=output)
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    assert "JSONB" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "BEFORE UPDATE OR DELETE ON content_snapshots" in sql
    assert "BEFORE UPDATE OR DELETE ON account_snapshots" in sql
    assert "UNIQUE (platform, platform_content_id)" in sql


def test_phase3_migration_preserves_phase2_snapshots(tmp_path,monkeypatch):
    from datetime import datetime,timezone
    from uuid import uuid4
    from sqlalchemy import MetaData,Table,select
    url=f"sqlite:///{tmp_path / 'existing.db'}"
    monkeypatch.setenv("DATABASE_URL",url)
    config=Config("alembic.ini")
    command.upgrade(config,"0001")
    engine=create_engine(url)
    metadata=MetaData()
    accounts=Table("social_accounts",metadata,autoload_with=engine)
    content=Table("content",metadata,autoload_with=engine)
    snapshots=Table("content_snapshots",metadata,autoload_with=engine)
    account_id,content_id,snapshot_id=[uuid4().hex for _ in range(3)]
    now=datetime(2026,10,1,tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.execute(accounts.insert().values(id=account_id,platform="instagram",username="demo.account",platform_account_id="123",created_at=now,updated_at=now))
        connection.execute(content.insert().values(id=content_id,account_id=account_id,platform="instagram",platform_content_id="1",content_type="video",created_at=now,updated_at=now))
        connection.execute(snapshots.insert().values(id=snapshot_id,content_id=content_id,snapshot_at=now,source="instagram_ui",snapshot_status="anomalous",views=0,unique_viewers=2,watch_time_avg_seconds=15.78,raw_payload={"original":"unchanged"},created_at=now))
    engine.dispose()
    command.upgrade(config,"head")
    engine=create_engine(url)
    snapshots=Table("content_snapshots",MetaData(),autoload_with=engine)
    with engine.connect() as connection:
        row=connection.execute(select(snapshots)).mappings().one()
        assert row["id"]==snapshot_id
        assert row["views"]==0 and row["unique_viewers"]==2
        assert float(row["watch_time_avg_seconds"])==15.78
        assert row["raw_payload"]=={"original":"unchanged"}
        assert row["collection_run_id"] is None and row["reach"] is None
    engine.dispose()
