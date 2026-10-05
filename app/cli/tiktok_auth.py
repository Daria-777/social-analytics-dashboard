"""Controlled local Web/Desktop OAuth bootstrap; refresh saves rotated tokens together."""
import argparse
from datetime import datetime,timezone
from pathlib import Path
from getpass import getpass
import sys
from pydantic import ValidationError
from app.config import Settings
from app.cli.instagram_auth import parse_redirect
from app.cli.secret_env import save_env
from app.cli.tiktok_desktop import DesktopCallback
from app.connectors.tiktok.credentials import Credential,CredentialStore,resolve_settings
from app.connectors.tiktok.auth import TikTokAuth,OAuthState,DesktopPKCE,validate_grant
from app.connectors.tiktok.schemas import Token
from app.connectors.tiktok.errors import TikTokError,TikTokInvalidResponseError,TikTokPermissionError


def save_token(path,token):
    try: token=Token.model_validate(token.model_dump())
    except ValidationError: raise TikTokInvalidResponseError('local_env','token_storage_validation') from None
    validate_grant(token.scope,endpoint='local_env')
    save_env(path,{'TIKTOK_ACCESS_TOKEN':token.access_token.get_secret_value(),'TIKTOK_REFRESH_TOKEN':token.refresh_token.get_secret_value(),'TIKTOK_OPEN_ID':token.open_id,'TIKTOK_SCOPES':token.scope,'TIKTOK_TOKEN_ISSUED_AT':datetime.now(timezone.utc).isoformat(),'TIKTOK_TOKEN_EXPIRES_IN':str(token.expires_in),'TIKTOK_REFRESH_EXPIRES_IN':str(token.refresh_expires_in)})


def main(argv=None):
    parser=argparse.ArgumentParser(description='Private TikTok read-only Web/Desktop OAuth bootstrap')
    parser.add_argument('--env-file',default='.env');parser.add_argument('--refresh',action='store_true')
    parser.add_argument("--mode",choices=("web","desktop"))
    parser.add_argument("--timeout",type=int,default=300,help="Desktop callback deadline in seconds (1–600)")
    parser.add_argument("--credential-store",type=Path,help="Explicit private .tiktok-credentials directory; never copies .env")
    parser.add_argument("--confirm-owner",action="store_true",help="Confirm you are authorizing the configured owner account")
    parser.add_argument("--confirm-workers-stopped",action="store_true",help="Confirm all Docker credential workers are stopped before Mac seed/reseed")
    args=parser.parse_args(argv)
    try:
        settings=Settings(_env_file=args.env_file)
        if args.mode: settings.tiktok_oauth_mode=args.mode
        if args.credential_store:settings.tiktok_credential_store=args.credential_store
        store_path=settings.tiktok_credential_store
        if store_path:
            if args.refresh:
                resolve_settings(settings,allow_refresh=True,force_refresh=True)
                print("TikTok private store renewed; workers reload it before collection.");return 0
            if not args.confirm_owner:raise ValueError("Explicit owner confirmation required")
            if sys.platform=="darwin" and settings.tiktok_renewal_runtime=="docker" and not args.confirm_workers_stopped:
                raise ValueError("Docker workers must be stopped before Mac seeding")
        settings.require_tiktok_oauth()
        if not 1 <= args.timeout <= 600: raise ValueError("Invalid callback timeout")
        with TikTokAuth(settings) as auth:
            if args.refresh:
                if not settings.tiktok_refresh_token: raise ValueError('Refresh token required')
                token=auth.refresh(settings.tiktok_refresh_token.get_secret_value())
            elif settings.tiktok_oauth_mode=="desktop":
                state=OAuthState(ttl=args.timeout);pkce=DesktopPKCE()
                with DesktopCallback(settings,state,timeout=args.timeout) as callback:
                    print("Open the read-only authorization URL:")
                    print(auth.authorization_url(state,pkce=pkce))
                    code=callback.wait()
                token=auth.exchange_code(code,pkce=pkce)
            else:
                state=OAuthState();print('Open the read-only authorization URL:');print(auth.authorization_url(state))
                received=getpass('Paste the full HTTPS redirect URL (hidden input): ')
                code=parse_redirect(received,settings.tiktok_redirect_uri,state,allowed_extra=("scopes",))
                token=auth.exchange_code(code)
            if store_path:
                record=Credential.from_token(token,issued_at=datetime.now(timezone.utc),owner_confirmed=args.confirm_owner)
                CredentialStore(store_path).seed(record)
            else:save_token(args.env_file,token)
        print('TikTok credentials saved to private store; workers reload before collection.' if store_path else 'TikTok credentials saved privately. Restart workers to load rotated tokens.')
        return 0
    except (ValueError,ValidationError,TikTokError,OSError):
        print('TikTok authorization failed: verify app, OAuth mode, registered redirect, callback port/deadline, state, permissions and private env file',file=sys.stderr);return 1
    except (KeyboardInterrupt,EOFError):
        print('TikTok authorization canceled',file=sys.stderr);return 1


if __name__=='__main__': raise SystemExit(main())
