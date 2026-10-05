"""Validated atomic historical/UI JSON import; never creates guessed parents."""
import argparse
import json
from pathlib import Path
import sys
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.database import get_engine
from app.schemas import ImportBatch
from app.manual_import import import_batch


def main(argv=None,*,engine_factory=get_engine):
    parser=argparse.ArgumentParser(description='Atomic manual/UI snapshot import')
    parser.add_argument('file',nargs='?');parser.add_argument('--schema',action='store_true')
    args=parser.parse_args(argv)
    if args.schema:
        print(json.dumps(ImportBatch.model_json_schema(),indent=2));return 0
    if not args.file: parser.error('file.json is required unless --schema is used')
    try:
        path=Path(args.file)
        if path.stat().st_size>5_000_000: raise ValueError('Import too large')
        batch=ImportBatch.model_validate_json(path.read_text())
        with Session(engine_factory()) as db: ids=import_batch(db,batch)
    except (ValueError,ValidationError,SQLAlchemyError,OSError):
        print('Import rejected; check schema, timezone, exact parent IDs, source and database. Batch was not imported.',file=sys.stderr);return 1
    print(json.dumps({key:len(value) for key,value in ids.items()}));return 0


if __name__=='__main__': raise SystemExit(main())
