from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from app.api import authenticate, DB
from app.config import Settings
from app.models import CollectorRun
from app.enums import Platform, CollectorStatus
from app.connectors.tiktok.client import TikTokClient
from app.connectors.tiktok.credentials import resolve_settings
from app.connectors.tiktok.errors import TikTokError
from app.connectors.tiktok.service import TikTokCollector
from app.connectors.instagram.client import InstagramClient
from app.connectors.instagram.service import InstagramCollector, CollectionBusyError

router=APIRouter(dependencies=[Depends(authenticate)])


class RunRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    run_id: UUID | None = None
    dry_run: bool = False


def get_instagram_settings():
    try:
        settings=Settings()
        settings.require_instagram_token()
        return settings
    except (ValueError,ValidationError):
        raise HTTPException(503,"Instagram server configuration is incomplete or invalid") from None


def get_instagram_http(settings: Annotated[Settings,Depends(get_instagram_settings)]):
    with InstagramClient(settings.require_instagram_token(),settings.instagram_api_version) as http:
        yield http


@router.post("/collectors/instagram/run")
def run_instagram(payload: RunRequest,db: DB,settings: Annotated[Settings,Depends(get_instagram_settings)],http: Annotated[InstagramClient,Depends(get_instagram_http)]):
    try:
        return InstagramCollector(settings,db,http).collect(run_id=payload.run_id,dry_run=payload.dry_run)
    except CollectionBusyError:
        raise HTTPException(409,"Collection run is already running or claimed") from None
    except ValueError:
        raise HTTPException(422,"Invalid collection run identity") from None


@router.get("/collectors/status")
def collector_status(db: DB):
    result={}
    for platform in Platform:
        base=select(CollectorRun).where(CollectorRun.platform==platform)
        last=db.scalar(base.order_by(CollectorRun.started_at.desc(),CollectorRun.id.desc()).limit(1))
        success=db.scalar(base.where(CollectorRun.status==CollectorStatus.SUCCESS).order_by(CollectorRun.finished_at.desc()).limit(1))
        result[platform.value]={"last_started_at":last.started_at if last else None,"last_success_at":success.finished_at if success else None,"last_status":last.status if last else None,"last_error_type":last.error_type if last else None}
    return result


def get_tiktok_settings():
    try:
        settings=resolve_settings(Settings(),allow_refresh=True);settings.require_tiktok_token();return settings
    except (ValueError,ValidationError,TikTokError):
        raise HTTPException(503,"TikTok server configuration is incomplete or invalid") from None


def get_tiktok_http(settings: Annotated[Settings,Depends(get_tiktok_settings)]):
    with TikTokClient(settings.require_tiktok_token()) as http: yield http


@router.post("/collectors/tiktok/run")
def run_tiktok(payload: RunRequest,db: DB,settings: Annotated[Settings,Depends(get_tiktok_settings)],http: Annotated[TikTokClient,Depends(get_tiktok_http)]):
    try: return TikTokCollector(settings,db,http).collect(run_id=payload.run_id,dry_run=payload.dry_run)
    except CollectionBusyError:
        raise HTTPException(409,"Collection run is already running or claimed") from None
    except ValueError:
        raise HTTPException(422,"Invalid collection run identity") from None


@router.get('/collectors/runs')
def run_history(db:DB,platform:Platform|None=None,limit:int=100):
    if not 1<=limit<=500: raise HTTPException(422,'Limit must be between 1 and 500')
    query=select(CollectorRun).order_by(CollectorRun.started_at.desc(),CollectorRun.id.desc()).limit(limit)
    if platform: query=query.where(CollectorRun.platform==platform)
    return [{'id':row.id,'platform':row.platform,'platform_account_id':row.platform_account_id,'started_at':row.started_at,'finished_at':row.finished_at,'status':row.status,'error_type':row.error_type,'summary':{key:(row.summary or {}).get(key) for key in ('media_discovered','new_media','content_snapshots','account_snapshots','failures','schedule')}} for row in db.scalars(query)]
