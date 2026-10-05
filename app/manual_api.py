from uuid import UUID
from pydantic import ValidationError
from fastapi import APIRouter,Depends,HTTPException,Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.api import authenticate,DB,require,history
from app import schemas as s,models as m
from app.manual_import import import_batch,ImportMissingError,ImportIdentityError

router=APIRouter(dependencies=[Depends(authenticate)])


def batch_for(**records):
    try: return s.ImportBatch(**records)
    except ValidationError: raise HTTPException(422,'Invalid source or metric period') from None


def persist(db,batch):
    try: return import_batch(db,batch)
    except ImportMissingError: raise HTTPException(404,'Exact platform identifier not found; create/discover parent first') from None
    except ImportIdentityError: raise HTTPException(422,'Source or parent identifier mismatch') from None
    except IntegrityError: raise HTTPException(409,'Import conflicts with database constraints; entire batch rolled back') from None


@router.post('/manual-snapshots/import',status_code=201)
def import_observations(payload:s.ImportBatch,db:DB): return persist(db,payload)


@router.post('/manual-snapshots/content',response_model=s.ContentSnapshotRead,status_code=201)
def content_observation(payload:s.ManualContentRecord,db:DB):
    if payload.source not in (s.Source.MANUAL,s.Source.INSTAGRAM_UI,s.Source.TIKTOK_STUDIO): raise HTTPException(422,'Only manual/UI sources allowed')
    ids=persist(db,batch_for(content_snapshots=[payload]))
    return db.get(m.ContentSnapshot,ids['content'][0])


@router.post('/manual-snapshots/account',response_model=s.AccountSnapshotRead,status_code=201)
def account_observation(payload:s.ManualAccountRecord,db:DB):
    if payload.source not in (s.Source.MANUAL,s.Source.INSTAGRAM_UI,s.Source.TIKTOK_STUDIO): raise HTTPException(422,'Only manual/UI sources allowed')
    ids=persist(db,batch_for(account_snapshots=[payload]))
    return db.get(m.AccountSnapshot,ids['account'][0])


@router.post('/manual-snapshots/retention',response_model=s.RetentionRead,status_code=201)
def retention_observation(payload:s.ManualRetentionRecord,db:DB):
    if payload.source not in (s.Source.MANUAL,s.Source.INSTAGRAM_UI,s.Source.TIKTOK_STUDIO): raise HTTPException(422,'Only manual/UI sources allowed')
    ids=persist(db,batch_for(retention_snapshots=[payload]))
    return db.get(m.ContentRetentionSnapshot,ids['retention'][0])


@router.get('/content/{content_id}/retention',response_model=list[s.RetentionRead])
def retention_history(content_id:UUID,db:DB,source:s.Source|None=None,date_from:s.UTCStamp|None=None,date_to:s.UTCStamp|None=None,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=1000)):
    require(db,m.Content,content_id)
    return history(db,m.ContentRetentionSnapshot,m.ContentRetentionSnapshot.content_id,content_id,source,date_from,date_to,offset,limit)


@router.get('/content-snapshots/{snapshot_id}/geography',response_model=list[s.GeographyRead])
def geography(snapshot_id:UUID,db:DB):
    require(db,m.ContentSnapshot,snapshot_id)
    return db.scalars(select(m.ContentGeoSnapshot).where(m.ContentGeoSnapshot.content_snapshot_id==snapshot_id).order_by(m.ContentGeoSnapshot.country_code)).all()
