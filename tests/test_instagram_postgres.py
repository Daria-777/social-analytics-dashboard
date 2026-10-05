from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
from sqlalchemy import delete, select, func
from sqlalchemy.orm import Session
from app.models import CollectorRun
from app.enums import Platform, CollectorStatus
from app.connectors.instagram.service import CollectionBusyError
from tests.postgres_support import test_engine as postgres_engine
from tests.test_instagram_service import collector
from tests.test_tiktok_service import collector as tiktok_collector


@pytest.mark.parametrize("platform", [Platform.INSTAGRAM, Platform.TIKTOK])
@pytest.mark.parametrize("initial", [None, CollectorStatus.FAILED, CollectorStatus.PARTIAL])
def test_only_one_independent_session_can_claim_uuid(initial,platform):
    engine=postgres_engine();job=uuid4();barrier=Barrier(2)
    try:
        if initial is not None:
            with Session(engine) as db:
                db.add(CollectorRun(id=job,platform=platform,status=initial));db.commit()
        class ContendingSession(Session):
            def get(self, entity, ident, **kwargs):
                result=super().get(entity,ident,**kwargs)
                if entity is CollectorRun:
                    barrier.wait(timeout=10)  # Both workers observed the same pre-claim state.
                return result
        def attempt():
            with ContendingSession(engine) as db:
                worker=collector(db) if platform==Platform.INSTAGRAM else tiktok_collector(db)
                try:
                    run,cached=worker._reserve(job)
                    assert not cached and run.status==CollectorStatus.RUNNING
                    return "claimed"
                except CollectionBusyError:
                    return "busy"
                finally:
                    worker.client.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:attempt(),range(2)))
        assert sorted(results)==["busy","claimed"]
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(CollectorRun).where(CollectorRun.id==job))==1
    finally:
        # This claim-only scenario writes no snapshots. Delete only its generated job.
        with engine.begin() as connection:
            connection.execute(delete(CollectorRun).where(CollectorRun.id==job))
        engine.dispose()


@pytest.mark.parametrize('platform',[Platform.INSTAGRAM,Platform.TIKTOK])
def test_platform_lock_prevents_different_uuid_workers(platform):
    from threading import Event
    import httpx
    from tests.test_instagram_service import handler as instagram_handler
    from tests.test_tiktok_service import handler as tiktok_handler
    from app.connectors.locks import advisory_lock
    engine=postgres_engine();entered=Event();release=Event();winner_id,loser_id=uuid4(),uuid4()
    first=engine.connect();second=engine.connect();transactions=[first.begin(),second.begin()]
    def responses(request):
        entered.set()
        if not release.wait(timeout=10): raise AssertionError('Worker gate timed out')
        return (instagram_handler if platform==Platform.INSTAGRAM else tiktok_handler)(request)
    def winner():
        with Session(first,join_transaction_mode='create_savepoint') as db:
            worker=collector(db,responses) if platform==Platform.INSTAGRAM else tiktok_collector(db,responses)
            try: return worker.collect(run_id=winner_id)
            finally: worker.client.close()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(winner)
            try:
                assert entered.wait(timeout=10)
                with Session(second,join_transaction_mode='create_savepoint') as db:
                    worker=collector(db) if platform==Platform.INSTAGRAM else tiktok_collector(db)
                    try:
                        with pytest.raises(CollectionBusyError): worker.collect(run_id=loser_id)
                        assert db.get(CollectorRun,loser_id) is None
                    finally: worker.client.close()
            finally: release.set()
            assert future.result(timeout=10)['status']=='success'
        with Session(first,join_transaction_mode='create_savepoint') as db:
            with advisory_lock(db,'collector:'+platform.value) as acquired: assert acquired
    finally:
        release.set()
        for transaction in transactions: transaction.rollback()
        first.close();second.close();engine.dispose()
