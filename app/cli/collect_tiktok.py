"""python -m app.cli.collect_tiktok [--dry-run] [--run-id UUID]"""
import argparse
import json
import logging
import sys
from uuid import UUID
from pydantic import ValidationError
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.config import Settings
from app.database import get_engine
from app.connectors.persistence import CollectionBusyError
from app.connectors.instagram.logging import InstagramLogFormatter
from app.connectors.tiktok.client import TikTokClient
from app.connectors.tiktok.credentials import resolve_settings
from app.connectors.tiktok.errors import TikTokError
from app.connectors.tiktok.service import TikTokCollector


def main(argv=None,*,settings=None,transport=None,engine_factory=get_engine):
    parser=argparse.ArgumentParser(description='TikTok Display API read-only collection')
    parser.add_argument('--dry-run',action='store_true');parser.add_argument('--run-id',type=UUID);parser.add_argument('--json',action='store_true')
    args=parser.parse_args(argv)
    try:
        settings=resolve_settings(settings or Settings(),allow_refresh=True,transport=transport);token=settings.require_tiktok_token()
    except (ValueError,ValidationError,TikTokError):
        print('Configuration error: set TikTok server environment variables',file=sys.stderr);return 2
    handler=logging.StreamHandler();handler.setFormatter(InstagramLogFormatter());logging.basicConfig(level=logging.INFO,handlers=[handler])
    try:
        with TikTokClient(token,transport=transport) as http:
            if args.dry_run: summary=TikTokCollector(settings,None,http).collect(dry_run=True)
            else:
                with Session(engine_factory()) as db: summary=TikTokCollector(settings,db,http).collect(run_id=args.run_id)
    except CollectionBusyError:
        print('Run already running; confirm worker is stopped before operator recovery',file=sys.stderr);return 1
    except (ValueError,SQLAlchemyError):
        print('Collection failed: verify database migrations and configuration',file=sys.stderr);return 1
    if args.json: print(json.dumps(summary,ensure_ascii=False))
    else:
        print('TikTok dry run complete' if args.dry_run else 'TikTok collection complete')
        for key in ('run_id','status','account','media_discovered','content_snapshots','account_snapshots','failures'):
            print(f'{key}: {summary[key]}')
        print(f"New media: {summary['new_media'] if summary['new_media'] is not None else 'unknown (no DB reads)'}")
    return 0 if summary['status']=='success' else 1


if __name__=='__main__': raise SystemExit(main())
