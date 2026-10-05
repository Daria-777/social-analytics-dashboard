"""python -m app.cli.collect_instagram [--dry-run] [--run-id UUID]"""
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
from app.connectors.instagram.client import InstagramClient
from app.connectors.instagram.logging import InstagramLogFormatter
from app.connectors.instagram.service import InstagramCollector, CollectionBusyError


def main(argv=None,*,settings=None,transport=None,engine_factory=get_engine):
    parser=argparse.ArgumentParser(description="Read-only Instagram analytics collection")
    parser.add_argument("--dry-run",action="store_true")
    parser.add_argument("--run-id",type=UUID,help="Reuse this UUID only for retries of the same collection job")
    parser.add_argument("--json",action="store_true",help="Print safe summary as JSON")
    args=parser.parse_args(argv)
    try:
        settings=settings or Settings()
        token=settings.require_instagram_token()
    except (ValueError,ValidationError):
        print("Configuration error: set valid Instagram server environment variables",file=sys.stderr)
        return 2
    handler=logging.StreamHandler()
    handler.setFormatter(InstagramLogFormatter())
    logging.basicConfig(level=logging.INFO,handlers=[handler])
    try:
        with InstagramClient(token,settings.instagram_api_version,transport=transport) as http:
            if args.dry_run:
                summary=InstagramCollector(settings,None,http).collect(dry_run=True)
            else:
                with Session(engine_factory()) as db:
                    summary=InstagramCollector(settings,db,http).collect(run_id=args.run_id)
    except CollectionBusyError:
        print("Collection run is already running; wait for the worker or recover the run only after verifying no worker is active",file=sys.stderr)
        return 1
    except (ValueError,SQLAlchemyError):
        print("Collection failed: check database migrations and server configuration",file=sys.stderr)
        return 1
    if args.json: print(json.dumps(summary,ensure_ascii=False))
    else:
        print("Instagram dry run complete" if args.dry_run else "Instagram collection complete")
        print(f"Run ID: {summary['run_id'] or 'none (dry run)'}")
        print(f"Status: {summary['status']}")
        print(f"Account: {summary['account'] or 'unavailable'}")
        print(f"Media discovered: {summary['media_discovered']}")
        print(f"New media: {summary['new_media'] if summary['new_media'] is not None else 'unknown (no DB reads)'}")
        label="Would collect" if args.dry_run else "Collected"
        print(f"{label} content snapshots: {summary['content_snapshots']}")
        print(f"{label} account snapshots: {summary['account_snapshots']}")
        print(f"Failures: {summary['failures']}")
        if args.dry_run:
            for media in summary.get("would_sync",[]):
                print(f"Media candidate: {media['platform_content_id']} ({media['content_type']})")
    return 0 if summary["status"]=="success" else 1


if __name__=="__main__":
    raise SystemExit(main())
