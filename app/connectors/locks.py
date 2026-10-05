"""Session-level PostgreSQL advisory locks survive collector commits."""
from contextlib import contextmanager
from functools import wraps
from hashlib import blake2b
from threading import Lock
from sqlalchemy import text
from app.connectors.persistence import CollectionBusyError

_LOCAL={}


@contextmanager
def advisory_lock(db,name):
    bind=db.get_bind()
    if bind.dialect.name=='sqlite':
        lock=_LOCAL.setdefault(name,Lock())
        acquired=lock.acquire(blocking=False)
        try: yield acquired
        finally:
            if acquired: lock.release()
        return
    if bind.dialect.name!='postgresql': raise ValueError('Collector locks require PostgreSQL')
    engine=bind.engine
    key=int.from_bytes(blake2b(('dash:'+name).encode(),digest_size=8).digest(),'big',signed=True)
    with engine.connect() as connection:
        acquired=connection.scalar(text('SELECT pg_try_advisory_lock(:key)'),{'key':key})
        try: yield bool(acquired)
        finally:
            if acquired: connection.execute(text('SELECT pg_advisory_unlock(:key)'),{'key':key})


def guard_collection(function):
    @wraps(function)
    def guarded(self,*,run_id=None,dry_run=False):
        if dry_run: return function(self,run_id=run_id,dry_run=True)
        if self.db is None: raise ValueError('Database session is required')
        # MVP config has one owner per platform. Serialize every worker for it.
        with advisory_lock(self.db,'collector:'+self.platform.value) as acquired:
            if not acquired: raise CollectionBusyError('Platform collector is already active')
            return function(self,run_id=run_id,dry_run=False)
    return guarded
