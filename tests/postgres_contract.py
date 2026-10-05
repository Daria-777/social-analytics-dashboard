"""Run explicitly against CI's isolated migrated PostgreSQL database."""
import os
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from app.models import SocialAccount, Content, AccountSnapshot, ContentSnapshot, CollectorRun, ContentRetentionSnapshot, ContentGeoSnapshot
from app.enums import Platform, Source, ContentType


def main():
    url = os.environ["TEST_DATABASE_URL"]
    parsed=make_url(url)
    assert parsed.get_backend_name()=="postgresql" and parsed.database=="test_dash" and parsed.host in ("localhost","127.0.0.1","::1","postgres"), "Only local PostgreSQL test_dash is allowed"
    engine = create_engine(url, hide_parameters=True)
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(connection, join_transaction_mode="create_savepoint") as db:
            account = SocialAccount(platform=Platform.INSTAGRAM, username="trigger-test", platform_account_id="test-only-account")
            run=CollectorRun(platform=Platform.INSTAGRAM)
            db.add_all([account,run]); db.flush()
            content=Content(account_id=account.id,platform=Platform.INSTAGRAM,platform_content_id="test-only-media",content_type=ContentType.VIDEO)
            db.add(content); db.flush()
            account_snapshot = AccountSnapshot(account_id=account.id,collection_run_id=run.id,metric_scope="current",snapshot_at=datetime.now(timezone.utc),source=Source.INSTAGRAM_API,views=0)
            content_snapshot = ContentSnapshot(content_id=content.id,collection_run_id=run.id,metric_scope="lifetime",snapshot_at=datetime.now(timezone.utc),source=Source.INSTAGRAM_API,views=0)
            db.add_all([account_snapshot,content_snapshot]); db.commit()
            retention=ContentRetentionSnapshot(content_id=content.id,snapshot_at=datetime.now(timezone.utc),source=Source.INSTAGRAM_UI,average_watch_seconds=0)
            geo=ContentGeoSnapshot(content_snapshot_id=content_snapshot.id,country_code="LV",percentage=0)
            db.add_all([retention,geo]);db.commit()
            ids={"account_snapshots":(account_snapshot.id,"views"),"content_snapshots":(content_snapshot.id,"views"),"content_retention_snapshots":(retention.id,"average_watch_seconds"),"content_geo_snapshots":(geo.id,"percentage")}
        for table,(snapshot_id,metric) in ids.items():
            for sql in (f"UPDATE {table} SET {metric}=1 WHERE id=:id",f"DELETE FROM {table} WHERE id=:id"):
                savepoint = connection.begin_nested()
                try:
                    connection.execute(text(sql), {"id": snapshot_id})
                except DBAPIError as error:
                    assert "append-only" in str(error.orig)
                else:
                    raise AssertionError("Snapshot mutation was allowed")
                finally:
                    savepoint.rollback()
            assert connection.scalar(text(f"SELECT {metric} FROM {table} WHERE id=:id"), {"id": snapshot_id}) == 0
        savepoint=connection.begin_nested()
        try:
            connection.execute(text("""
                INSERT INTO content_snapshots (id,content_id,collection_run_id,metric_scope,
                    snapshot_at,source,snapshot_status,created_at)
                SELECT :new_id,content_id,collection_run_id,metric_scope,snapshot_at,
                    source,snapshot_status,created_at FROM content_snapshots WHERE id=:id
            """),{"new_id":uuid4(),"id":ids["content_snapshots"][0]})
        except IntegrityError as error:
            assert "uq_content_run" in str(error.orig)
        else:
            raise AssertionError("Duplicate snapshot for the same run was allowed")
        finally:
            savepoint.rollback()
        transaction.rollback()
    engine.dispose()


if __name__ == "__main__":
    main()
