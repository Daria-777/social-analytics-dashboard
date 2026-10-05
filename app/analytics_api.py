from collections import defaultdict
from typing import Literal
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,Query
from sqlalchemy import select,func
from app.api import authenticate,DB,require
from app import models as m,schemas as s
from app.analytics import derived_metrics,summary,sample_guard,velocity

router=APIRouter(dependencies=[Depends(authenticate)])
Group=Literal['platform','hook_type','series','topic','format','cta_type','content_pillar']
METRICS=('views','unique_viewers','likes','comments','shares','saves','profile_visits','followers_gained','completion_rate','watch_time_avg_seconds','average_watch_pct','like_rate','comment_rate','share_rate','save_rate','follow_conversion','profile_visit_rate','returning_viewer_rate')


def comparable(snapshot):
    return (snapshot.metric_scope=='lifetime' and snapshot.source_period_start is None and snapshot.source_period_end is None) or (snapshot.metric_scope=='range' and snapshot.source_period_start is not None and snapshot.source_period_end is not None)


def latest_snapshots(source=None,date_from=None,date_to=None):
    if date_from and date_to and date_from>date_to: raise HTTPException(422,'Observation start must precede end')
    model=m.ContentSnapshot
    query=select(model.id,func.row_number().over(partition_by=[model.content_id,model.source,model.metric_scope,model.source_period_start,model.source_period_end],order_by=[model.snapshot_at.desc(),model.created_at.desc(),model.id.desc()]).label('position'))
    if source: query=query.where(model.source==source)
    if date_from: query=query.where(model.snapshot_at>=date_from)
    if date_to: query=query.where(model.snapshot_at<=date_to)
    return query.subquery()


def serialize(content,snapshot):
    return {'content':s.ContentRead.model_validate(content).model_dump(mode='json'),'snapshot':s.ContentSnapshotRead.model_validate(snapshot).model_dump(mode='json',exclude={'raw_payload'}),'derived':derived_metrics(content,snapshot),'comparable_period':comparable(snapshot)}


@router.get('/analytics/content-comparison')
def comparison(db:DB,platform:s.Platform|None=None,source:s.Source|None=None,date_from:s.UTCStamp|None=None,date_to:s.UTCStamp|None=None,snapshot_from:s.UTCStamp|None=None,snapshot_to:s.UTCStamp|None=None,series:str|None=None,topic:str|None=None,hook_type:str|None=None,content_pillar:str|None=None,format:str|None=None,cta_type:str|None=None,group_by:Group='hook_type',offset:int=Query(0,ge=0),limit:int=Query(200,ge=1,le=1000)):
    if date_from and date_to and date_from>date_to: raise HTTPException(422,'Publication start must precede end')
    latest=latest_snapshots(source,snapshot_from,snapshot_to)
    query=select(m.Content,m.ContentSnapshot).join(m.ContentSnapshot,m.ContentSnapshot.content_id==m.Content.id).join(latest,latest.c.id==m.ContentSnapshot.id).where(latest.c.position==1)
    if platform: query=query.where(m.Content.platform==platform)
    if date_from: query=query.where(m.Content.published_at>=date_from)
    if date_to: query=query.where(m.Content.published_at<=date_to)
    for key,value in {'series':series,'topic':topic,'hook_type':hook_type,'content_pillar':content_pillar,'format':format,'cta_type':cta_type}.items():
        if value is not None: query=query.where(getattr(m.Content,key)==value)
    selected=db.execute(query.order_by(m.Content.published_at.desc(),m.Content.id,m.ContentSnapshot.source,m.ContentSnapshot.snapshot_at.desc()).offset(offset).limit(limit+1)).all()
    rows=[];buckets=defaultdict(list)
    for content,snapshot in selected[:limit]:
        row=serialize(content,snapshot);rows.append(row)
        key=(content.platform.value,snapshot.source.value,snapshot.metric_scope,snapshot.source_period_start,snapshot.source_period_end,snapshot.snapshot_status.value,getattr(content,group_by))
        buckets[key].append(row)
    groups=[]
    for key,members in buckets.items():
        platform_key,source_key,scope,start,end,status,label=key
        known=all(row['comparable_period'] for row in members)
        metrics={metric:summary([(row['derived'].get(metric) if metric in row['derived'] else row['snapshot'].get(metric)) for row in members] if known else []) for metric in METRICS}
        n=len({row['content']['id'] for row in members})
        groups.append({'platform':platform_key,'source':source_key,'metric_scope':scope,'source_period_start':start,'source_period_end':end,'snapshot_status':status,'group':label,'sample_size':n,'guardrail':sample_guard(n),'comparable_period':known,'metrics':metrics})
    return {'rows':rows,'groups':groups,'truncated':len(selected)>limit,'offset':offset,'limit':limit,'notes':'Separate source/period/status groups; observations are not causal and lifetime counts may have different ages. Unknown periods have no aggregate means.'}


@router.get('/analytics/content/{content_id}')
def detail(content_id:UUID,db:DB,source:s.Source|None=None):
    content=require(db,m.Content,content_id);latest=latest_snapshots(source)
    snapshots=db.scalars(select(m.ContentSnapshot).join(latest,latest.c.id==m.ContentSnapshot.id).where(latest.c.position==1,m.ContentSnapshot.content_id==content_id).order_by(m.ContentSnapshot.snapshot_at.desc())).all()
    return {'content':s.ContentRead.model_validate(content),'latest':[serialize(content,row) for row in snapshots]}


@router.get('/analytics/content/{content_id}/velocity')
def content_velocity(content_id:UUID,db:DB,source:s.Source):
    content=require(db,m.Content,content_id)
    snapshots=db.scalars(select(m.ContentSnapshot).where(m.ContentSnapshot.content_id==content_id,m.ContentSnapshot.source==source,m.ContentSnapshot.metric_scope=='lifetime')).all()
    return {'content_id':content_id,'source':source,'points':velocity(content,snapshots),'method':'Nearest available lifetime observation; no interpolation; deviation is actual minus requested age.'}


@router.patch('/content/{content_id}/tags',response_model=s.ContentRead)
def update_tags(content_id:UUID,payload:s.ContentTagsPatch,db:DB):
    content=require(db,m.Content,content_id)
    if payload.experiment_id is not None: require(db,m.Experiment,payload.experiment_id)
    for key,value in payload.model_dump(exclude_unset=True).items(): setattr(content,key,value)
    db.commit();db.refresh(content);return content


@router.get('/experiments',response_model=list[s.ExperimentRead])
def experiments(db:DB,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=1000)):
    return db.scalars(select(m.Experiment).order_by(m.Experiment.created_at.desc(),m.Experiment.id).offset(offset).limit(limit)).all()


@router.patch('/experiments/{experiment_id}',response_model=s.ExperimentRead)
def update_experiment(experiment_id:UUID,payload:s.ExperimentPatch,db:DB):
    from pydantic import ValidationError
    row=require(db,m.Experiment,experiment_id)
    current=s.ExperimentRead.model_validate(row).model_dump(exclude={'id','created_at'})
    try: validated=s.ExperimentCreate.model_validate({**current,**payload.model_dump(exclude_unset=True)})
    except ValidationError: raise HTTPException(422,'Invalid experiment fields or date range') from None
    for key,value in validated.model_dump().items(): setattr(row,key,value)
    db.commit();db.refresh(row);return row


@router.get('/content/{content_id}/experiments')
def content_experiments(content_id:UUID,db:DB):
    content=require(db,m.Content,content_id)
    query=select(m.Experiment,m.ContentExperiment.variant).join(m.ContentExperiment,m.ContentExperiment.experiment_id==m.Experiment.id).where(m.ContentExperiment.content_id==content_id)
    linked=[{'experiment':s.ExperimentRead.model_validate(row),'variant':variant} for row,variant in db.execute(query)]
    return {'primary_experiment_id':content.experiment_id,'links':linked}
