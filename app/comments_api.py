"""Count-based attention; never claim platform read status or fetch comment bodies."""
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel,ConfigDict
from sqlalchemy import select,func,and_,or_,tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from app.api import authenticate,DB,require
from app.models import Content,ContentSnapshot,CommentReview
from app.schemas import ContentRead
from app.enums import Platform,Source,DataStatus
from app.types import utc_now

router=APIRouter(dependencies=[Depends(authenticate)])
API_SOURCES=(Source.INSTAGRAM_API,Source.TIKTOK_API)
USABLE=(DataStatus.CONFIRMED,DataStatus.ESTIMATED)


def usable(snapshot,content):
    return (snapshot.source.value==content.platform.value+'_api' and snapshot.metric_scope=='lifetime'
        and snapshot.source_period_start is None and snapshot.source_period_end is None
        and snapshot.snapshot_status in USABLE and snapshot.comments is not None)


@router.get('/comments/attention')
def attention(db:DB,limit:int=Query(100,ge=1,le=1000),offset:int=Query(0,ge=0)):
    s=ContentSnapshot
    latest=select(s.id,func.row_number().over(partition_by=[s.content_id,s.source],
        order_by=[s.snapshot_at.desc(),s.created_at.desc(),s.id.desc()]).label('position')).where(
        s.source.in_(API_SOURCES),s.metric_scope=='lifetime',s.source_period_start.is_(None),
        s.source_period_end.is_(None),s.snapshot_status.in_(USABLE),s.comments.is_not(None)).subquery()
    query=select(Content,s,CommentReview).join(s,s.content_id==Content.id).join(latest,latest.c.id==s.id).outerjoin(
        CommentReview,CommentReview.content_id==Content.id).where(latest.c.position==1,
        or_(and_(Content.platform==Platform.INSTAGRAM,s.source==Source.INSTAGRAM_API),
            and_(Content.platform==Platform.TIKTOK,s.source==Source.TIKTOK_API)),
        s.comments>func.coalesce(CommentReview.comments,0)).order_by(s.snapshot_at.desc(),Content.id)
    selected=db.execute(query.offset(offset).limit(limit+1)).all()
    return {'rows':[{'content':ContentRead.model_validate(c).model_dump(mode='json'),
        'snapshot_id':str(snapshot.id),'snapshot_at':snapshot.snapshot_at.isoformat(),
        'comments':snapshot.comments,'new_comments':snapshot.comments-review.comments if review else None,
        'reviewed_at':review.reviewed_at.isoformat() if review else None}
        for c,snapshot,review in selected[:limit]],'truncated':len(selected)>limit,'offset':offset,'limit':limit}


class ReviewRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    content_id:UUID
    snapshot_id:UUID


@router.post('/comments/review')
def review(payload:ReviewRequest,db:DB):
    content=require(db,Content,payload.content_id)
    snapshot=require(db,ContentSnapshot,payload.snapshot_id)
    if snapshot.content_id!=content.id or not usable(snapshot,content):
        raise HTTPException(422,'Review must reference an available lifetime API count for this publication')
    # Use the displayed immutable snapshot, not a newer observation the user never saw.
    insert=pg_insert if db.bind.dialect.name=='postgresql' else sqlite_insert
    values={'content_id':content.id,'snapshot_id':snapshot.id,'snapshot_at':snapshot.snapshot_at,
        'snapshot_created_at':snapshot.created_at,'comments':snapshot.comments,'reviewed_at':utc_now()}
    statement=insert(CommentReview).values(**values)
    statement=statement.on_conflict_do_update(index_elements=['content_id'],
        set_={k:v for k,v in values.items() if k!='content_id'},
        where=tuple_(CommentReview.snapshot_at,CommentReview.snapshot_created_at,CommentReview.snapshot_id)
          <tuple_(snapshot.snapshot_at,snapshot.created_at,snapshot.id))
    db.execute(statement);db.commit()
    return {'status':'reviewed'}
