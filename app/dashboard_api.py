import json
from pathlib import Path
from secrets import compare_digest
import time
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.responses import FileResponse,JSONResponse
from sqlalchemy.engine import make_url
from app.api import authenticate
from app.config import Settings
from app.connectors.tiktok.credentials import resolve_settings
from app.connectors.tiktok.errors import TikTokError
from app.dashboard_auth import COOKIE,session_token,same_origin

router=APIRouter()
WEB=Path(__file__).parent/'web'
_FAILURES={}


@router.get('/dashboard',include_in_schema=False)
def dashboard(): return FileResponse(WEB/'dashboard.html')


@router.get('/terms',include_in_schema=False)
def terms(): return FileResponse(WEB/'terms.html')


@router.get('/privacy',include_in_schema=False)
def privacy(): return FileResponse(WEB/'privacy.html')


@router.get('/dashboard/assets/{name}',include_in_schema=False)
def assets(name:Literal['dashboard.css','dashboard.js','dashboard-core.js','dashboard-detail.js','dashboard-forms.js','dashboard-preview.js','dashboard-presentation.js','dashboard-charts.js','platform-instagram.svg','platform-tiktok.svg','collection-automatic.svg','collection-manual.svg','favicon.svg']): return FileResponse(WEB/name)


@router.get('/favicon.ico',include_in_schema=False)
def favicon(): return FileResponse(WEB/'favicon.svg',media_type='image/svg+xml')


@router.post('/dashboard/session',include_in_schema=False)
async def login(request:Request):
    same_origin(request)
    body=b''
    async for chunk in request.stream():
        body+=chunk
        if len(body)>4096: raise HTTPException(413,'Login request too large')
    try:
        payload=json.loads(body)
        supplied=payload.get('api_key') if isinstance(payload,dict) else None
        remember_browser=payload.get('remember_browser',False) if isinstance(payload,dict) else False
        if not isinstance(supplied,str) or not isinstance(remember_browser,bool): raise ValueError()
    except (ValueError,TypeError): raise HTTPException(422,'Invalid login request') from None
    settings=Settings();expected=settings.internal_api_key
    if not expected or not expected.get_secret_value().strip(): raise HTTPException(503,'Access key is not configured')
    now=time.time();address=request.client.host if request.client else 'local'
    if len(_FAILURES)>256: _FAILURES.clear()
    attempts,start=_FAILURES.get(address,(0,now))
    if now-start>60: attempts,start=0,now
    if attempts>=5: raise HTTPException(429,'Too many login attempts; wait one minute')
    if not compare_digest(supplied.encode(),expected.get_secret_value().encode()):
        _FAILURES[address]=(attempts+1,start);raise HTTPException(401,'Invalid access key')
    _FAILURES.pop(address,None)
    seconds=30*86400 if remember_browser else settings.dashboard_session_hours*3600
    response=JSONResponse({'status':'ok'})
    response.set_cookie(COOKIE,session_token(expected.get_secret_value(),now+seconds),max_age=seconds,httponly=True,secure=request.url.scheme=='https',samesite='strict',path='/')
    return response


@router.post('/dashboard/logout',include_in_schema=False)
def logout(request:Request):
    same_origin(request)
    response=JSONResponse({'status':'ok'});response.delete_cookie(COOKIE,path='/');return response


@router.get('/dashboard/config',dependencies=[Depends(authenticate)],include_in_schema=False)
def configuration():
    settings=Settings()
    try:
        tiktok_settings=resolve_settings(settings)  # Status reads never trigger renewal.
        tiktok_ready=bool(tiktok_settings.tiktok_access_token and tiktok_settings.tiktok_access_token.get_secret_value().strip())
    except TikTokError:
        tiktok_ready=False
    return {'display_timezone':settings.display_timezone,'test_database':make_url(settings.database_url.get_secret_value()).database=='test_dash','scheduler_configured':settings.scheduler_enabled,'instagram_ready':bool(settings.instagram_access_token and settings.instagram_access_token.get_secret_value().strip()),'tiktok_ready':tiktok_ready}
