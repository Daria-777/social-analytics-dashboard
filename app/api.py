from secrets import compare_digest
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.config import Settings
from app.database import get_session
from app.enums import Source
from app import models as m, schemas as s

DB = Annotated[Session, Depends(get_session)]


def authenticate(request: Request, x_api_key: Annotated[str | None, Header()] = None):
    from app.dashboard_auth import COOKIE,valid_session,same_origin
    expected = Settings().internal_api_key
    if expected is None or not expected.get_secret_value().strip():
        raise HTTPException(503, "Internal API key is not configured")
    key=expected.get_secret_value()
    if x_api_key is not None:
        if compare_digest(x_api_key.encode(),key.encode()): return
        raise HTTPException(401,"Invalid internal API key")
    if valid_session(request.cookies.get(COOKIE),key):
        if request.method not in ('GET','HEAD','OPTIONS'): same_origin(request)
        return
    raise HTTPException(401, "Authentication required")


router = APIRouter(dependencies=[Depends(authenticate)])


def require(db, model, object_id):
    obj = db.get(model, object_id)
    if obj is None:
        raise HTTPException(404, "Record not found")
    return obj


def insert(db, model, payload):
    row = model(**payload.model_dump())
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Record conflicts with database constraints") from None
    db.refresh(row)
    return row


def check_source(platform, source):
    if source != Source.MANUAL and not source.value.startswith(platform.value + "_"):
        raise HTTPException(422, "Source does not match the parent platform")


@router.post("/accounts", response_model=s.AccountRead, status_code=201)
def create_account(payload: s.AccountCreate, db: DB):
    return insert(db, m.SocialAccount, payload)


@router.get("/accounts", response_model=list[s.AccountRead])
def accounts(db: DB, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    return db.scalars(select(m.SocialAccount).order_by(m.SocialAccount.created_at, m.SocialAccount.id).offset(offset).limit(limit)).all()


@router.post("/content", response_model=s.ContentRead, status_code=201)
def create_content(payload: s.ContentCreate, db: DB):
    account = require(db, m.SocialAccount, payload.account_id)
    if account.platform != payload.platform:
        raise HTTPException(422, "Content platform must match account platform")
    if payload.experiment_id:
        require(db, m.Experiment, payload.experiment_id)
    return insert(db, m.Content, payload)


@router.get("/content", response_model=list[s.ContentRead])
def contents(db: DB, account_id: UUID | None = None, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    query = select(m.Content).order_by(m.Content.created_at, m.Content.id)
    if account_id:
        query = query.where(m.Content.account_id == account_id)
    return db.scalars(query.offset(offset).limit(limit)).all()


@router.get("/content/{content_id}", response_model=s.ContentRead)
def get_content(content_id: UUID, db: DB):
    return require(db, m.Content, content_id)


@router.post("/account-snapshots", response_model=s.AccountSnapshotRead, status_code=201)
def account_snapshot(payload: s.AccountSnapshotCreate, db: DB):
    account = require(db, m.SocialAccount, payload.account_id)
    check_source(account.platform, payload.source)
    return insert(db, m.AccountSnapshot, payload)


@router.post("/content-snapshots", response_model=s.ContentSnapshotRead, status_code=201)
def content_snapshot(payload: s.ContentSnapshotCreate, db: DB):
    content = require(db, m.Content, payload.content_id)
    check_source(content.platform, payload.source)
    return insert(db, m.ContentSnapshot, payload)


def history(db, model, parent_key, parent_id, source, date_from, date_to, offset, limit):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must be <= date_to")
    query = select(model).where(parent_key == parent_id)
    if source:
        query = query.where(model.source == source)
    if date_from:
        query = query.where(model.snapshot_at >= date_from)
    if date_to:
        query = query.where(model.snapshot_at <= date_to)
    return db.scalars(query.order_by(model.snapshot_at, model.created_at, model.id).offset(offset).limit(limit)).all()


@router.get("/accounts/{account_id}/history", response_model=list[s.AccountSnapshotRead])
def account_history(account_id: UUID, db: DB, source: Source | None = None,
                    date_from: s.UTCStamp | None = None, date_to: s.UTCStamp | None = None,
                    offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    require(db, m.SocialAccount, account_id)
    return history(db, m.AccountSnapshot, m.AccountSnapshot.account_id, account_id, source, date_from, date_to, offset, limit)


@router.get("/content/{content_id}/history", response_model=list[s.ContentSnapshotRead])
def content_history(content_id: UUID, db: DB, source: Source | None = None,
                    date_from: s.UTCStamp | None = None, date_to: s.UTCStamp | None = None,
                    offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    require(db, m.Content, content_id)
    return history(db, m.ContentSnapshot, m.ContentSnapshot.content_id, content_id, source, date_from, date_to, offset, limit)


@router.post("/experiments", response_model=s.ExperimentRead, status_code=201)
def experiment(payload: s.ExperimentCreate, db: DB):
    return insert(db, m.Experiment, payload)


@router.post("/content-experiments", response_model=s.ContentExperimentCreate, status_code=201)
def link_experiment(payload: s.ContentExperimentCreate, db: DB):
    require(db, m.Content, payload.content_id)
    require(db, m.Experiment, payload.experiment_id)
    return insert(db, m.ContentExperiment, payload)
