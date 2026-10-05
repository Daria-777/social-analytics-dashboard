"""Unix private token directory; flock serializes read/refresh/atomic replacement."""
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import fcntl
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
from typing import Literal
from pydantic import ConfigDict,Field,ValidationError,field_validator,model_validator
from .auth import TikTokAuth,validate_grant
from .schemas import Token
from .errors import TikTokError


class CredentialError(TikTokError):
    def __init__(self):super().__init__('local_credentials','private_store_validation')


class Credential(Token):
    model_config=ConfigDict(extra='forbid')
    issued_at: datetime
    expires_in: int=Field(gt=0,strict=True)
    refresh_expires_in: int=Field(gt=0,strict=True)
    grant_verified: Literal[True]
    owner_verified: Literal[True]

    @field_validator('grant_verified','owner_verified',mode='before')
    @classmethod
    def verified(cls,value):
        if value is not True:raise ValueError('Verified metadata required')
        return value

    @field_validator('issued_at')
    @classmethod
    def aware(cls,value):
        if value.tzinfo is None:raise ValueError('Aware issuance time required')
        return value.astimezone(timezone.utc)

    @field_validator('scope')
    @classmethod
    def read_grants(cls,value):return validate_grant(value,endpoint='local_credentials')

    @field_validator('open_id')
    @classmethod
    def owner_id(cls,value):
        if not value.strip() or value!=value.strip():raise ValueError('Owner identity required')
        return value

    @model_validator(mode='after')
    def representable_expiries(self):
        try:
            for seconds in (self.expires_in,self.refresh_expires_in):self.issued_at+timedelta(seconds=seconds)
        except OverflowError:raise ValueError('Invalid expiry metadata') from None
        return self

    @classmethod
    def from_token(cls,token,*,issued_at,owner_confirmed):
        # Revalidate constructed and mutated models before serialization.
        try:return cls.model_validate({**token.model_dump(),'issued_at':issued_at,'grant_verified':True,'owner_verified':owner_confirmed})
        except (ValueError,ValidationError,TikTokError):raise CredentialError() from None


class CredentialStore:
    def __init__(self,path):
        self.directory=Path(path)
        if self.directory.name!='.tiktok-credentials':raise CredentialError()
        self.path=self.directory/'credentials.json'

    def _directory(self,*,create=False):
        if create:
            try:self.directory.mkdir(mode=0o700)
            except FileExistsError:pass
        info=self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o700 or info.st_uid!=os.geteuid():raise CredentialError()

    def _open(self,path,flags):
        fd=os.open(path,flags|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o600 or info.st_uid!=os.geteuid():
            os.close(fd);raise CredentialError()
        return fd

    def read(self):
        try:
            self._directory()
            with os.fdopen(self._open(self.path,os.O_RDONLY),'rb') as source:payload=source.read(65537)
            if len(payload)>65536:raise CredentialError()
            return Credential.model_validate_json(payload)
        except (OSError,ValueError,ValidationError,TikTokError):raise CredentialError() from None

    @contextmanager
    def locked(self):
        fd=None
        try:
            self._directory(create=True)
            fd=self._open(self.directory/'rotation.lock',os.O_CREAT|os.O_RDWR)
            deadline=time.monotonic()+10
            while True:
                try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                except BlockingIOError:
                    if time.monotonic()>=deadline:raise CredentialError()
                    time.sleep(.05)
            yield
        except (OSError,ValueError,ValidationError):raise CredentialError() from None
        finally:
            if fd is not None:os.close(fd)

    def _write(self,record):
        temporary=None
        try:
            record=Credential.model_validate(record.model_dump())
            payload=record.model_dump(mode='json')
            payload['access_token']=record.access_token.get_secret_value()
            payload['refresh_token']=record.refresh_token.get_secret_value()
            serialized=json.dumps(payload)
            if len(serialized.encode())>65536:raise CredentialError()
            with tempfile.NamedTemporaryFile(mode='w',dir=self.directory,prefix='.credential-',delete=False) as output:
                temporary=output.name;os.chmod(temporary,0o600)
                output.write(serialized);output.flush();os.fsync(output.fileno())
            os.replace(temporary,self.path);temporary=None
        except (OSError,ValueError,ValidationError,TikTokError):raise CredentialError() from None
        finally:
            if temporary is not None:
                try:os.unlink(temporary)
                except OSError:pass

    def seed(self,record):
        with self.locked():
            if self.path.exists() or self.path.is_symlink():
                existing=self.read()
                if record.open_id!=existing.open_id:raise CredentialError()
            self._write(record)


def resolve_settings(settings,*,allow_refresh=False,force_refresh=False,transport=None,now=None):
    if not settings.tiktok_credential_store:
        if settings.tiktok_auto_refresh_enabled or force_refresh:raise CredentialError()
        return settings
    if settings.tiktok_renewal_runtime=="docker" and (sys.platform=="darwin" or not Path("/.dockerenv").is_file()) and (allow_refresh or force_refresh):
        raise CredentialError()  # Darwin flock does not coordinate with this Docker Desktop guest.
    store=CredentialStore(settings.tiktok_credential_store)
    fixed_now=now
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise CredentialError()
    def checked():
        record=store.read()
        if record.issued_at>(fixed_now or datetime.now(timezone.utc)) or (settings.tiktok_open_id and settings.tiktok_open_id!=record.open_id):raise CredentialError()
        return record
    record=checked()
    def due(value):return value.issued_at+timedelta(seconds=value.expires_in)<=now+timedelta(seconds=settings.tiktok_refresh_skew_seconds)
    if allow_refresh and (force_refresh or settings.tiktok_auto_refresh_enabled) and (force_refresh or due(record)):
        with store.locked():
            record=checked()  # Another process may already have rotated it.
            if force_refresh or due(record):
                if record.issued_at+timedelta(seconds=record.refresh_expires_in)<=now:raise CredentialError()
                bound=settings.model_copy(update={'tiktok_open_id':record.open_id})
                try:bound.require_tiktok_client()
                except ValueError:raise CredentialError() from None
                with TikTokAuth(bound,transport=transport) as auth:token=auth.refresh(record.refresh_token.get_secret_value())
                record=Credential.from_token(token,issued_at=now,owner_confirmed=True)
                store._write(record)
    return settings.model_copy(update={'tiktok_access_token':record.access_token,'tiktok_refresh_token':record.refresh_token,'tiktok_open_id':record.open_id,'tiktok_scopes':record.scope})
