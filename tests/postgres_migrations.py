"""Explicit destructive migration round trip, ONLY on an EMPTY local test_dash."""
import os
from datetime import datetime, timezone
from uuid import uuid4
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, inspect, select
from sqlalchemy.engine import make_url
from app.config import Settings
from tests.postgres_contract import main as check_contract


def main():
    url=os.environ["TEST_DATABASE_URL"]
    parsed=make_url(url)
    if parsed.get_backend_name()!="postgresql" or parsed.database!="test_dash" or parsed.host not in ("localhost","127.0.0.1","::1","postgres"):
        raise ValueError("Only local PostgreSQL test_dash is allowed")
    engine=create_engine(url,hide_parameters=True)
    if inspect(engine).get_table_names():
        engine.dispose()
        raise RuntimeError("Migration round trip requires EMPTY test_dash; refuses existing tables")
    Settings.model_config["env_file"]=None
    os.environ["DATABASE_URL"]=url
    config=Config("alembic.ini")
    command.upgrade(config,"0001")
    metadata=MetaData()
    tables={name:Table(name,metadata,autoload_with=engine) for name in ("social_accounts","content","account_snapshots","content_snapshots","experiments","content_experiments")}
    account_id,content_id,experiment_id=uuid4(),uuid4(),uuid4()
    now=datetime(2026,10,1,tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.execute(tables["experiments"].insert().values(id=experiment_id,name="phase2-test",hypothesis="preserved",status="draft",created_at=now))
        connection.execute(tables["social_accounts"].insert().values(id=account_id,platform="instagram",username="phase2-test",platform_account_id="phase2-test",created_at=now,updated_at=now))
        connection.execute(tables["content"].insert().values(id=content_id,account_id=account_id,platform="instagram",platform_content_id="phase2-test",content_type="reel",experiment_id=experiment_id,internal_title="preserved",hook_text="preserved",created_at=now,updated_at=now))
        connection.execute(tables["content_experiments"].insert().values(content_id=content_id,experiment_id=experiment_id,variant="original"))
        for name,parent in (("account_snapshots",{"account_id":account_id}),("content_snapshots",{"content_id":content_id})):
            values=dict(id=uuid4(),**parent,snapshot_at=now,source="instagram_ui",snapshot_status="anomalous",views=0,unique_viewers=2,raw_payload={"original":"unchanged"},created_at=now)
            if name=="content_snapshots": values["watch_time_avg_seconds"]=15.78
            connection.execute(tables[name].insert().values(**values))
        originals={name:dict(connection.execute(select(table)).mappings().one()) for name,table in tables.items()}
    def assert_preserved():
        with engine.connect() as connection:
            for name,original in originals.items():
                table=Table(name,MetaData(),autoload_with=engine)
                row=connection.execute(select(table)).mappings().one()
                assert {key:row[key] for key in original}==original
                for key in ("collection_run_id","metric_scope","reach","profile_activity"):
                    if key in row: assert row[key] is None
    command.upgrade(config,"head")
    assert_preserved()
    command.check(config)
    check_contract()
    command.downgrade(config,"0001")
    assert_preserved()
    command.downgrade(config,"base")
    assert inspect(engine).get_table_names()==["alembic_version"]
    engine.dispose()
    print("PostgreSQL: Phase 2 preserved; upgrade/check/immutability/downgrade passed")


if __name__=="__main__":
    main()
