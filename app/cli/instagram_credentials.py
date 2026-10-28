"""Private Docker-volume bootstrap and renewal check; never print token values."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import sys
from app.config import Settings
from app.connectors.instagram.credentials import Credential, CredentialStore, CredentialError, resolve_settings
from app.connectors.instagram.client import InstagramClient
from app.connectors.instagram.errors import InstagramError


def main(argv=None, *, settings=None, transport=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed-stdin',action='store_true',help='Read verified OAuth metadata from private stdin; refuse an existing store')
    args=parser.parse_args(argv)
    try:
        settings=settings or Settings()
        if not settings.instagram_credential_store: raise CredentialError()
        store=CredentialStore(settings.instagram_credential_store)
        if args.seed_stdin:
            payload=sys.stdin.buffer.read(65537)
            if len(payload)>65536: raise CredentialError()
            record=Credential.model_validate_json(payload)
            now=datetime.now(timezone.utc)
            if not record.issued_at<=now<record.issued_at+timedelta(seconds=record.expires_in): raise CredentialError()
            if settings.instagram_user_id and record.user_id!=settings.instagram_user_id: raise CredentialError()
            with InstagramClient(record.access_token.get_secret_value(),settings.instagram_api_version,transport=transport) as client:
                owner=client.get('me',operation='credential_owner_check',params={'fields':'user_id,username'})
            if str(owner.get('user_id'))!=record.user_id or str(owner.get('username','')).casefold()!=settings.instagram_expected_username.casefold(): raise CredentialError()
            store.seed(record)
        else:
            resolve_settings(settings,allow_refresh=True,transport=transport)
        record=store.read()
        print(json.dumps({'status':'ready','issued_at':record.issued_at.isoformat(),'expires_at':(record.issued_at+timedelta(seconds=record.expires_in)).isoformat(),'auto_refresh_from':(record.issued_at+timedelta(seconds=record.expires_in)-timedelta(days=7)).isoformat(),'auto_refresh_enabled':settings.instagram_auto_refresh_enabled}))
        return 0
    except (InstagramError, ValueError, OSError):
        print('Instagram private credentials unavailable; values hidden',file=sys.stderr)
        return 1


if __name__=='__main__': raise SystemExit(main())
