"""Opt-in local scheduler; startup never calls a social API without configuration."""
import argparse
import json
import logging
import sys
import time
from pydantic import ValidationError
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.config import Settings
from app.database import get_engine
from app.types import utc_now
from app.scheduler import planned_jobs,run_tick,configured
from app.enums import Platform
from app.connectors.instagram.logging import InstagramLogFormatter


def main(argv=None,*,settings=None,engine_factory=get_engine):
    parser=argparse.ArgumentParser(description='Read-only snapshot scheduler')
    parser.add_argument('--once',action='store_true');parser.add_argument('--plan',action='store_true')
    args=parser.parse_args(argv)
    try:
        settings=settings or Settings()
        if not args.plan and not settings.scheduler_enabled:
            print('Scheduler disabled: set SCHEDULER_ENABLED=true explicitly',file=sys.stderr);return 2
        if 'database_url' not in settings.model_fields_set:
            print('Set an explicit permanent DATABASE_URL before scheduler startup',file=sys.stderr);return 2
        if not any(configured(settings,p) for p in Platform):
            print('No configured Instagram/TikTok token; no jobs started',file=sys.stderr);return 2
        engine=engine_factory()
        if not args.plan and engine.dialect.name!='postgresql':
            print('Scheduler requires PostgreSQL cross-process locks',file=sys.stderr);return 2
    except (ValueError,ValidationError):
        print('Scheduler configuration invalid (values hidden)',file=sys.stderr);return 2
    handler=logging.StreamHandler();handler.setFormatter(InstagramLogFormatter());logging.basicConfig(level=logging.INFO,handlers=[handler])
    errors=0
    try:
        while True:
            try:
                with Session(engine) as db:
                    result=[job.public() for job in planned_jobs(db,settings,utc_now())] if args.plan else run_tick(db,settings,utc_now())
                print(json.dumps(result),flush=True);errors=0
                if args.once or args.plan: return 0
            except (ValueError,SQLAlchemyError):
                errors+=1
                print('Scheduler failed: verify database/configuration; values hidden',file=sys.stderr)
                if args.once or args.plan or errors>=3: return 1
            time.sleep(settings.scheduler_poll_seconds)
    except KeyboardInterrupt: return 0


if __name__=='__main__': raise SystemExit(main())
