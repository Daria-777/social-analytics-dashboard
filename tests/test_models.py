from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.enums import Platform, Source, DataStatus
from app.models import Base, SocialAccount, AccountSnapshot


def test_orm_snapshot_is_immutable_and_keeps_null():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        account = SocialAccount(platform=Platform.TIKTOK, username="test", platform_account_id="test")
        db.add(account)
        db.flush()
        snapshot = AccountSnapshot(account_id=account.id, snapshot_at=datetime(2026, 10, 3, tzinfo=timezone.utc), source=Source.MANUAL, followers=0)
        db.add(snapshot)
        db.commit()
        assert snapshot.profile_views is None
        assert snapshot.followers == 0
        snapshot.followers = 2
        with pytest.raises(ValueError, match="append-only"):
            db.commit()
        db.rollback()
        assert db.scalar(select(AccountSnapshot)).followers == 0
        db.delete(snapshot)
        with pytest.raises(ValueError, match="append-only"):
            db.commit()
        db.rollback()
    engine.dispose()


def test_all_analytics_columns_nullable_without_zero_defaults():
    from app.models import ContentSnapshot
    for model in (AccountSnapshot, ContentSnapshot):
        for column in model.__table__.columns:
            if column.type.python_type in (int, Decimal):
                assert column.nullable
                assert column.default is None
                assert column.server_default is None


def test_database_rejects_negative_counts():
    from sqlalchemy.exc import IntegrityError
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        account = SocialAccount(platform=Platform.TIKTOK, username="test", platform_account_id="negative-test")
        db.add(account)
        db.flush()
        db.add(AccountSnapshot(account_id=account.id, snapshot_at=datetime.now(timezone.utc), source=Source.MANUAL, views=-1))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    engine.dispose()


def test_orm_rejects_naive_timestamp():
    from sqlalchemy.exc import StatementError
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        account = SocialAccount(platform=Platform.TIKTOK, username="test", platform_account_id="timezone-test")
        db.add(account)
        db.flush()
        db.add(AccountSnapshot(account_id=account.id, snapshot_at=datetime(2026, 10, 3), source=Source.MANUAL))
        with pytest.raises(StatementError, match="Timezone offset"):
            db.flush()
        db.rollback()
    engine.dispose()
