"""Narrow agent API. Credentials never grant access to collectors or owner routes."""
import hashlib
import json
from datetime import datetime, timezone, timedelta
from secrets import compare_digest
from statistics import median
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.api import DB, authenticate, require
from app.config import Settings
from app import models as m, schemas as s
from app.enums import Platform, DataStatus
from app.growth_schemas import AnalysisCreate, AgentObservationImport
from app.manual_import import import_batch, ImportMissingError, ImportIdentityError


def authenticate_growth(request:Request,x_api_key:Annotated[str|None,Header()]=None):
    settings=Settings()
    if x_api_key is not None:
        for credential in (settings.growth_api_key,settings.internal_api_key):
            if credential and credential.get_secret_value().strip() and compare_digest(x_api_key.encode(),credential.get_secret_value().encode()):
                return
        raise HTTPException(401,'Authentication required')
    authenticate(request)


router=APIRouter(prefix='/growth',dependencies=[Depends(authenticate_growth)])


def digest(payload):
    return hashlib.sha256(json.dumps(payload.model_dump(mode='json'),sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def safe_snapshot(row,content=None):
    # Explicit exclusion: raw platform responses can carry tokens or private transport data.
    data={c.name:getattr(row,c.name) for c in row.__table__.columns if c.name not in ('raw_payload','notes')}
    if content:
        data['published_at']=content.published_at
        data['publication_age_hours']=(row.snapshot_at-content.published_at).total_seconds()/3600 if content.published_at else None
    return jsonable_encoder(data)


def content_metadata(row):
    return s.ContentRead.model_validate(row).model_dump(mode='json',exclude={'preview_url','notes'})


@router.get('/content/resolve')
def resolve(platform:Platform,platform_content_id:Annotated[str,Query(min_length=1,max_length=300)],db:DB):
    content=db.scalar(select(m.Content).where(m.Content.platform==platform,m.Content.platform_content_id==platform_content_id))
    if content is None: raise HTTPException(404,'Publication not found')
    return {'content_id':content.id,**content_metadata(content)}


def measurements(db,content,cutoff=None,limit=1000,offset=0):
    query=select(m.ContentSnapshot).where(m.ContentSnapshot.content_id==content.id)
    if cutoff: query=query.where(m.ContentSnapshot.snapshot_at<=cutoff,m.ContentSnapshot.created_at<=cutoff)
    return db.scalars(query.order_by(m.ContentSnapshot.snapshot_at.desc(),m.ContentSnapshot.created_at.desc(),m.ContentSnapshot.id.desc()).offset(offset).limit(limit+1)).all()


def stream_key(row):
    return (row.source,row.metric_scope,row.source_period_start,row.source_period_end)


def velocity(rows):
    streams={}
    result=[]
    for row in sorted(rows,key=lambda r:(r.snapshot_at,r.created_at,str(r.id))):
        key=stream_key(row);previous=streams.get(key)
        # Only explicit lifetime scope supports cumulative-counter velocity.
        if previous and row.metric_scope=='lifetime' and row.source_period_start is None and row.source_period_end is None:
            hours=(row.snapshot_at-previous.snapshot_at).total_seconds()/3600
            if hours>0 and row.views is not None and previous.views is not None:
                result.append({'from_snapshot_id':previous.id,'to_snapshot_id':row.id,'source':row.source,'metric_scope':row.metric_scope,'elapsed_hours':hours,'views_delta':row.views-previous.views,'views_per_hour':(row.views-previous.views)/hours,'counter_decreased':row.views<previous.views})
        streams[key]=row
    return result


def cohort(db,content,rows):
    groups=[]
    # Conservative cohort: same account/platform/type, explicit lifetime scope,
    # measured within one hour of target's actual publication age. Never extrapolate.
    targets={}
    for row in rows:
        if row.metric_scope=='lifetime' and row.source_period_start is None and row.source_period_end is None:
            targets.setdefault(stream_key(row),row)
    peers=db.scalars(select(m.Content).where(m.Content.account_id==content.account_id,m.Content.platform==content.platform,m.Content.content_type==content.content_type,m.Content.id!=content.id).order_by(m.Content.published_at.desc()).limit(100)).all()
    for target in targets.values():
        if content.published_at is None or target.views is None: continue
        age=(target.snapshot_at-content.published_at).total_seconds()/3600
        if age<0: continue
        references=[]
        for peer in peers:
            if peer.published_at is None: continue
            candidates=db.scalars(select(m.ContentSnapshot).where(m.ContentSnapshot.content_id==peer.id,m.ContentSnapshot.source==target.source,m.ContentSnapshot.metric_scope=='lifetime',m.ContentSnapshot.source_period_start.is_(None),m.ContentSnapshot.source_period_end.is_(None),m.ContentSnapshot.snapshot_at<=target.snapshot_at,m.ContentSnapshot.snapshot_at>=peer.published_at+timedelta(hours=max(0,age-1)),m.ContentSnapshot.snapshot_at<=peer.published_at+timedelta(hours=age+1),m.ContentSnapshot.created_at<=target.created_at,m.ContentSnapshot.snapshot_status.in_([DataStatus.CONFIRMED,DataStatus.MANUAL]))).all()
            candidates=[r for r in candidates if r.views is not None and abs((r.snapshot_at-peer.published_at).total_seconds()/3600-age)<=1]
            if candidates:
                chosen=min(candidates,key=lambda r:(abs((r.snapshot_at-peer.published_at).total_seconds()/3600-age),str(r.id)))
                references.append({'content_id':peer.id,'snapshot_id':chosen.id,'views':chosen.views,'actual_age_hours':(chosen.snapshot_at-peer.published_at).total_seconds()/3600})
        groups.append({'source':target.source,'metric_scope':'lifetime','target_snapshot_id':target.id,'target_age_hours':age,'age_tolerance_hours':1,'cohort_size':len(references),'historical_median_views':median(r['views'] for r in references) if references else None,'references':references,'limitation':'Descriptive same-account/type cohort; not causal evidence. Max 100 recent peers.'})
    return groups


@router.get('/content/{content_id}/context')
def context(content_id:UUID,db:DB,limit:int=Query(500,ge=1,le=1000),offset:int=Query(0,ge=0)):
    content=require(db,m.Content,content_id)
    rows=measurements(db,content,limit=limit,offset=offset)
    retention=db.scalars(select(m.ContentRetentionSnapshot).where(m.ContentRetentionSnapshot.content_id==content_id).order_by(m.ContentRetentionSnapshot.snapshot_at.desc(),m.ContentRetentionSnapshot.id.desc()).offset(offset).limit(limit+1)).all()
    experiments=db.execute(select(m.Experiment,m.ContentExperiment.variant).join(m.ContentExperiment,m.ContentExperiment.experiment_id==m.Experiment.id).where(m.ContentExperiment.content_id==content_id)).all()
    experiment_ids={e.id for e,v in experiments}
    if content.experiment_id and content.experiment_id not in experiment_ids:
        legacy=db.get(m.Experiment,content.experiment_id)
        if legacy: experiments.append((legacy,None))
    truncated=len(rows)>limit
    rows=rows[:limit]
    return {'content':content_metadata(content),'snapshots':[safe_snapshot(r,content) for r in rows],'snapshots_truncated':truncated,'next_offset':offset+limit if truncated or len(retention)>limit else None,'retention':[safe_snapshot(r,content) for r in retention[:limit]],'retention_truncated':len(retention)>limit,'velocity':velocity(rows),'experiments':[{'experiment':s.ExperimentRead.model_validate(e).model_dump(mode='json'),'variant':v} for e,v in experiments],'comparable_context':cohort(db,content,rows),'checkpoint_policy':'24h/72h/7d are targets only; publication_age_hours is actual. Null is unknown, zero is measured.'}


def analysis_read(row):
    return {'id':row.id,'content_id':row.content_id,'created_at':row.created_at,'analysis_snapshot_at':row.analysis_snapshot_at,'data_cutoff_at':row.data_cutoff_at,'agent_version':row.agent_version,'agent_run_id':row.agent_run_id,**row.result,'provenance':row.provenance}


def replay(existing,request_hash,serializer):
    if existing.request_hash!=request_hash: raise HTTPException(409,'Delivery identifier already used with a different payload')
    return serializer(existing)


@router.get('/content/{content_id}/analyses')
def analyses(content_id:UUID,db:DB,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=1000)):
    require(db,m.Content,content_id)
    return [analysis_read(row) for row in db.scalars(select(m.GrowthAnalysis).where(m.GrowthAnalysis.content_id==content_id).order_by(m.GrowthAnalysis.created_at.desc(),m.GrowthAnalysis.id.desc()).offset(offset).limit(limit))]


@router.post('/content/{content_id}/analyses',status_code=201)
def create_analysis(content_id:UUID,payload:AnalysisCreate,db:DB):
    content=require(db,m.Content,content_id);request_hash=digest(payload)
    query=select(m.GrowthAnalysis).where(m.GrowthAnalysis.content_id==content_id,m.GrowthAnalysis.agent_run_id==payload.agent_run_id)
    existing=db.scalar(query)
    if existing: return replay(existing,request_hash,analysis_read)
    now=datetime.now(timezone.utc)
    if payload.analysis_snapshot_at>now: raise HTTPException(422,'Analysis time cannot be in the future')
    evidence={}
    for label,model,ids in [('snapshots',m.ContentSnapshot,payload.snapshot_ids),('retention',m.ContentRetentionSnapshot,payload.retention_snapshot_ids)]:
        rows=db.scalars(select(model).where(model.id.in_(ids),model.content_id==content_id)).all() if ids else []
        if len(rows)!=len(ids) or any(r.snapshot_at>payload.data_cutoff_at for r in rows):
            raise HTTPException(422,'Evidence must exist for this publication and not exceed cutoff')
        evidence[label]=[safe_snapshot(r,content) for r in sorted(rows,key=lambda r:str(r.id))]
    evidence['sources']=sorted({r['source'] for rows in (evidence['snapshots'],evidence['retention']) for r in rows})
    evidence['last_observed_at']=max(r['snapshot_at'] for rows in (evidence['snapshots'],evidence['retention']) for r in rows)
    evidence['content_at_analysis']=content_metadata(content)
    # Freeze linked experiment/hypothesis too; later owner edits cannot rewrite the interpretation.
    evidence['experiments']=context(content_id,db,limit=1,offset=0)['experiments']
    body=payload.model_dump(mode='json',exclude={'agent_run_id','analysis_snapshot_at','data_cutoff_at','agent_version','snapshot_ids','retention_snapshot_ids'})
    row=m.GrowthAnalysis(content_id=content_id,agent_run_id=payload.agent_run_id,request_hash=request_hash,analysis_snapshot_at=payload.analysis_snapshot_at,data_cutoff_at=payload.data_cutoff_at,agent_version=payload.agent_version,hypothesis_status=payload.hypothesis_status,confidence=payload.confidence,result=body,provenance=evidence)
    db.add(row)
    try: db.commit()
    except IntegrityError:
        db.rollback();existing=db.scalar(query)
        if existing: return replay(existing,request_hash,analysis_read)
        raise HTTPException(409,'Analysis conflicts with stored data') from None
    db.refresh(row)
    return analysis_read(row)


@router.post('/observations/import',status_code=201,dependencies=[Depends(authenticate)])
def agent_import(payload:AgentObservationImport,db:DB):
    # One stable UUID for the entire intent; receipt and observations commit together.
    request_hash=digest(payload);query=select(m.AgentImport).where(m.AgentImport.agent_run_id==payload.agent_run_id)
    existing=db.scalar(query)
    if existing:return replay(existing,request_hash,lambda row:row.response)
    row=m.AgentImport(agent_run_id=payload.agent_run_id,request_hash=request_hash,response={})
    try:
        for records in (payload.batch.content_snapshots,payload.batch.account_snapshots,payload.batch.retention_snapshots):
            for record in records:
                record.raw_payload={**(record.raw_payload or {}),'collection_method':'ai_agent','agent_run_id':str(payload.agent_run_id)}
        row.response=jsonable_encoder(import_batch(db,payload.batch,commit=False))
        # Receipt and observations are a single transaction. Concurrent losing
        # delivery rolls back all its tentative inserts on the unique constraint.
        db.add(row)
        db.commit()
    except IntegrityError:
        db.rollback();existing=db.scalar(query)
        if existing:return replay(existing,request_hash,lambda row:row.response)
        raise HTTPException(409,'Import conflicts with stored data') from None
    except ImportMissingError:
        db.rollback();raise HTTPException(404,'Exact publication/account not found') from None
    except ImportIdentityError:
        db.rollback();raise HTTPException(422,'Observation identity or source mismatch') from None
    return row.response
