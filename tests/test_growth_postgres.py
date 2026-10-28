"""Real independent connections; only disposable local test_dash is accepted."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import datetime,timezone
from uuid import uuid4
import pytest
from sqlalchemy import select,func,text
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError
from tests.postgres_support import test_engine as postgres_engine
from tests.test_growth import analysis
from app import models as m
from app.enums import Platform,ContentType,Source
from app.growth_api import create_analysis,agent_import
from app.growth_schemas import AnalysisCreate,AgentObservationImport


@pytest.fixture
def isolated_growth_engine():
    base=postgres_engine();schema='growth_test_'+uuid4().hex
    with base.begin() as conn:conn.execute(text(f'CREATE SCHEMA {schema}'))
    engine=base.execution_options(schema_translate_map={None:schema})
    m.Base.metadata.create_all(engine)
    with base.begin() as conn:
        for table in ('growth_analyses','agent_imports'):
            conn.execute(text(f'CREATE TRIGGER immutable_snapshot BEFORE UPDATE OR DELETE ON {schema}.{table} FOR EACH ROW EXECUTE FUNCTION public.reject_snapshot_mutation()'))
    try:yield engine,schema
    finally:
        with base.begin() as conn:conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        base.dispose()


@pytest.mark.parametrize('kind',['analysis','import'])
def test_simultaneous_delivery_has_one_persisted_result(kind,isolated_growth_engine):
    engine,schema=isolated_growth_engine;barrier=Barrier(2);suffix=str(uuid4())
    with Session(engine) as db:
        account=m.SocialAccount(platform=Platform.TIKTOK,username='test',platform_account_id=suffix);db.add(account);db.flush()
        content=m.Content(account_id=account.id,platform=Platform.TIKTOK,platform_content_id=suffix,content_type=ContentType.VIDEO);db.add(content);db.flush()
        snapshot=m.ContentSnapshot(content_id=content.id,snapshot_at=datetime(2026,10,2,6,tzinfo=timezone.utc),source=Source.TIKTOK_STUDIO,metric_scope='lifetime',views=0)
        db.add(snapshot);db.commit();cid=content.id;sid=snapshot.id
    receipt_model=m.GrowthAnalysis if kind=='analysis' else m.AgentImport
    class ConcurrentSession(Session):
        first_lookup=True
        def scalar(self,statement,*args,**kwargs):
            result=super().scalar(statement,*args,**kwargs)
            if self.first_lookup and statement.column_descriptions[0]['entity'] is receipt_model:
                self.first_lookup=False;barrier.wait(timeout=10)
            return result
    if kind=='analysis':payload=AnalysisCreate(**analysis(str(sid)))
    else:payload=AgentObservationImport(agent_run_id=uuid4(),batch={'content_snapshots':[{'platform':'tiktok','platform_content_id':suffix,'source':'tiktok_studio','snapshot_at':'2026-10-02T07:00:00Z','views':0}]})
    def deliver(_):
        with ConcurrentSession(engine) as db:
            # Each HTTP request receives its own validated payload instance.
            own=type(payload).model_validate_json(payload.model_dump_json())
            result=create_analysis(cid,own,db) if kind=='analysis' else agent_import(own,db)
            return str(result['id']) if kind=='analysis' else result
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(deliver,range(2)))
    assert results[0]==results[1]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(receipt_model).where(receipt_model.agent_run_id==payload.agent_run_id))==1
        assert db.scalar(select(func.count()).select_from(m.ContentSnapshot).where(m.ContentSnapshot.content_id==cid))==(1 if kind=='analysis' else 2)
    # Direct SQL must hit the append-only trigger too.
    with engine.begin() as conn:
        table=schema+'.'+receipt_model.__tablename__
        for sql in (f"UPDATE {table} SET request_hash='changed' WHERE agent_run_id=:run",f'DELETE FROM {table} WHERE agent_run_id=:run'):
            with pytest.raises(DBAPIError,match='append-only'):
                with conn.begin_nested():conn.execute(text(sql),{'run':payload.agent_run_id})
