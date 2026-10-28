"""Private Instagram token store; writers coordinate within one Unix runtime."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import json
import logging
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
from pydantic import ConfigDict, Field, field_validator, model_validator
from .auth import InstagramAuth, SCOPES
from .errors import InstagramError
from .schemas import Token

log = logging.getLogger(__name__)


class CredentialError(InstagramError):
    def __init__(self): super().__init__('local_credentials', 'private_store_validation')


class Credential(Token):
    model_config = ConfigDict(extra='forbid')
    issued_at: datetime
    expires_in: int = Field(gt=86400, strict=True)
    user_id: str = Field(pattern=r'^\d+$')
    scopes: list[str]

    @field_validator('issued_at')
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None: raise ValueError('Aware issuance time required')
        return value.astimezone(timezone.utc)

    @field_validator('scopes')
    @classmethod
    def read_only(cls, value):
        if len(value) != len(SCOPES) or set(value) != set(SCOPES): raise ValueError('Exact read-only grant required')
        return sorted(value)

    @model_validator(mode='after')
    def valid_expiry(self):
        try: self.issued_at + timedelta(seconds=self.expires_in)
        except OverflowError: raise ValueError('Invalid expiry') from None
        return self


class CredentialStore:
    def __init__(self, path):
        self.directory = Path(path)
        if self.directory.name != '.instagram-credentials': raise CredentialError()
        self.path = self.directory/'credentials.json'

    def _directory(self, create=False):
        if create:
            try: self.directory.mkdir(mode=0o700)
            except FileExistsError: pass
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid(): raise CredentialError()

    def _open(self, path, flags):
        fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.geteuid():
            os.close(fd); raise CredentialError()
        return fd

    def read(self):
        try:
            self._directory()
            with os.fdopen(self._open(self.path, os.O_RDONLY), 'rb') as source: payload = source.read(65537)
            if len(payload) > 65536: raise CredentialError()
            return Credential.model_validate_json(payload)
        except (OSError, ValueError): raise CredentialError() from None

    @contextmanager
    def locked(self):
        fd = None
        try:
            self._directory(create=True)
            fd = self._open(self.directory/'rotation.lock', os.O_CREAT | os.O_RDWR)
            deadline = time.monotonic()+10
            while True:
                try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); break
                except BlockingIOError:
                    if time.monotonic() >= deadline: raise CredentialError()
                    time.sleep(.05)
            yield
        except (OSError, ValueError): raise CredentialError() from None
        finally:
            if fd is not None: os.close(fd)

    def _write(self, record):
        temporary = None
        try:
            record = Credential.model_validate(record.model_dump())
            payload = record.model_dump(mode='json')
            payload['access_token'] = record.access_token.get_secret_value()
            serialized = json.dumps(payload)
            if len(serialized.encode()) > 65536: raise CredentialError()
            with tempfile.NamedTemporaryFile(mode='w', dir=self.directory, prefix='.credential-', delete=False) as output:
                temporary = output.name; os.chmod(temporary, 0o600)
                output.write(serialized); output.flush(); os.fsync(output.fileno())
            os.replace(temporary, self.path); temporary = None
        except (OSError, ValueError): raise CredentialError() from None
        finally:
            if temporary is not None:
                try: os.unlink(temporary)
                except OSError: pass

    def seed(self, record):
        with self.locked():
            if self.path.exists() or self.path.is_symlink(): raise CredentialError()
            self._write(record)


def resolve_settings(settings, *, allow_refresh=False, transport=None, now=None):
    if not settings.instagram_credential_store:
        if settings.instagram_auto_refresh_enabled: raise CredentialError()
        return settings
    if allow_refresh and settings.instagram_renewal_runtime == 'docker' and (sys.platform == 'darwin' or not Path('/.dockerenv').is_file()): raise CredentialError()
    store = CredentialStore(settings.instagram_credential_store)
    fixed_now = now
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None: raise CredentialError()

    def checked():
        value = store.read()
        current = fixed_now or datetime.now(timezone.utc)
        if value.issued_at > current or value.issued_at+timedelta(seconds=value.expires_in) <= current: raise CredentialError()
        if settings.instagram_user_id and settings.instagram_user_id != value.user_id: raise CredentialError()
        return value

    def due(value):
        return value.issued_at+timedelta(days=1) <= now and value.issued_at+timedelta(seconds=value.expires_in) <= now+timedelta(days=7)

    record = checked()
    if allow_refresh and settings.instagram_auto_refresh_enabled and due(record):
        with store.locked():
            record = checked()  # Another API/scheduler worker may have renewed it.
            if due(record):
                try:
                    with InstagramAuth(settings, transport=transport) as auth: token = auth.refresh(record.access_token.get_secret_value())
                    renewed = Credential.model_validate({**record.model_dump(), **token.model_dump(), 'issued_at':now})
                except (InstagramError, ValueError):
                    # Keep the valid old token; collection will report revoked access.
                    log.warning('Instagram token renewal failed; existing token retained')
                else:
                    store._write(renewed); record = renewed
                    log.info('Instagram token renewed and saved privately')
    return settings.model_copy(update={'instagram_access_token':record.access_token, 'instagram_user_id':record.user_id, 'instagram_granted_scopes':','.join(record.scopes)})
