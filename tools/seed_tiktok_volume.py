"""First seed only: validated token fields travel over stdin, never argv/logs."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

from dotenv import dotenv_values

RECEIVER = """
import sys
from app.connectors.tiktok.credentials import Credential, CredentialStore
try:
    payload = sys.stdin.buffer.read(65537)
    if len(payload) > 65536: raise ValueError()
    store = CredentialStore('/run/dash-tiktok/.tiktok-credentials')
    if store.path.exists() or store.path.is_symlink(): raise ValueError()
    store.seed(Credential.model_validate_json(payload))
except Exception:
    raise SystemExit('Private credential seed refused') from None
print('Private credentials seeded')
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default='social-analytics')
    parser.add_argument('--env-file', default='.env')
    parser.add_argument('--confirm-owner', action='store_true')
    parser.add_argument('--confirm-workers-stopped', action='store_true')
    args = parser.parse_args(argv)
    try:
        if not (args.confirm_owner and args.confirm_workers_stopped): raise ValueError()
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}', args.project): raise ValueError()
        path = Path(args.env_file)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.geteuid():
            raise ValueError()
        v = dotenv_values(path)
        payload = {
            'access_token': v['TIKTOK_ACCESS_TOKEN'],
            'refresh_token': v['TIKTOK_REFRESH_TOKEN'],
            'open_id': v['TIKTOK_OPEN_ID'],
            'scope': v['TIKTOK_SCOPES'],
            'issued_at': v['TIKTOK_TOKEN_ISSUED_AT'],
            'expires_in': int(v['TIKTOK_TOKEN_EXPIRES_IN']),
            'refresh_expires_in': int(v['TIKTOK_REFRESH_EXPIRES_IN']),
            'token_type': 'Bearer',
            'grant_verified': True,
            'owner_verified': True,
        }
        from app.connectors.tiktok.credentials import Credential
        record = Credential.model_validate(payload)
        now = datetime.now(timezone.utc)
        if record.issued_at > now or record.issued_at + timedelta(seconds=record.refresh_expires_in) <= now:
            raise ValueError()
        docker = shutil.which('docker') or '/Applications/Docker.app/Contents/Resources/bin/docker'
        root = Path(__file__).resolve().parents[1]
        cmd = [docker, 'compose', '-p', args.project, '--env-file', str(path.resolve()),
               '-f', str(root/'compose.yaml'), '-f', str(root/'compose.tiktok-volume.yaml'), '--profile', 'scheduler']
        running = subprocess.check_output(cmd+['ps', '--status', 'running', '-q', 'api', 'scheduler'], stderr=subprocess.PIPE)
        if running.strip(): raise ValueError()
        subprocess.run(cmd+['run', '--rm', '--no-deps', 'tiktok-credentials-init'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(cmd+['run', '--rm', '--no-deps', '-T', 'api', 'python', '-c', RECEIVER],
                       input=json.dumps(payload).encode(), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print('Private token-only Docker volume seeded; .env unchanged.')
        return 0
    except Exception:
        print('Seed refused: verify private env, owner, stopped workers and empty volume; values hidden.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
