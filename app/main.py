from typing import Annotated
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.database import get_session

app = FastAPI(title="SOCIAL ANALYTICS — Social Analytics", version="0.1.0")


@app.get("/health")
def health(db: Annotated[Session, Depends(get_session)]):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "error", "database": "unavailable"})
    return {"status": "ok", "database": "ok"}

from app.api import router
app.include_router(router)
from app.collectors_api import router as collectors_router
app.include_router(collectors_router)
from app.manual_api import router as manual_router
app.include_router(manual_router)
from app.analytics_api import router as analytics_router
app.include_router(analytics_router)
from app.dashboard_api import router as dashboard_router
app.include_router(dashboard_router)
from app.content_preview import router as preview_router
app.include_router(preview_router)
from app.reports_api import router as reports_router
app.include_router(reports_router)


@app.middleware('http')
async def private_response_headers(request,call_next):
    response=await call_next(request)
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    if request.url.path.startswith('/dashboard') or request.url.path in ('/terms','/privacy'):
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://*.cdninstagram.com https://cdninstagram.com https://*.fbcdn.net https://fbcdn.net https://*.tiktokcdn.com https://tiktokcdn.com https://*.tiktokcdn-us.com https://tiktokcdn-us.com https://*.tiktokcdn-eu.com https://tiktokcdn-eu.com https://*.ibytedtos.com https://ibytedtos.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response
