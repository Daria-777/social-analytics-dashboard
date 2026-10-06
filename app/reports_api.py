from typing import Literal
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from app.api import DB, authenticate
from app.reports import load_report, report_summary, xlsx_report, pdf_report

router = APIRouter(prefix='/reports', dependencies=[Depends(authenticate)])


@router.get('/summary')
def summary(db: DB, days: Literal['7', '30'] = '7', timezone: str = Query('UTC', max_length=100)):
    return report_summary(load_report(db, int(days), timezone))


@router.get('/export.{format}')
def export(db: DB, format: Literal['xlsx', 'pdf'], days: Literal['7', '30'] = '7', timezone: str = Query('UTC', max_length=100)):
    report = load_report(db, int(days), timezone)
    content = xlsx_report(report) if format == 'xlsx' else pdf_report(report)
    media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if format == 'xlsx' else 'application/pdf'
    filename = f'dash-report-{report.start.astimezone(report.zone):%Y-%m-%d}-{report.end.astimezone(report.zone):%Y-%m-%d}.{format}'
    return Response(content, media_type=media, headers={'Content-Disposition': f'attachment; filename="{filename}"'})
