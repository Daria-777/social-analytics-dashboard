"""Controlled local OAuth bootstrap; no public callback or token in stdout."""
import argparse
from datetime import datetime, timezone
from getpass import getpass
import sys
from urllib.parse import parse_qs, urlsplit
from pydantic import ValidationError
from app.config import Settings
from app.cli.loopback_callback import LoopbackCallback
from app.connectors.instagram.auth import InstagramAuth, OAuthState, SCOPES
from app.connectors.instagram.errors import InstagramError, InstagramInvalidResponseError
from app.connectors.instagram.schemas import Token


def parse_redirect(received,expected,state,*,allowed_extra=()):
    uri,target=urlsplit(received),urlsplit(expected)
    if (uri.scheme,uri.netloc,uri.path)!=(target.scheme,target.netloc,target.path):
        raise ValueError("OAuth redirect does not match configured HTTPS URI")
    if target.scheme!='https' or target.query or target.fragment or uri.fragment not in ('','_') or len(uri.query)>8192:
        raise ValueError("Invalid OAuth redirect")
    try:
        params=parse_qs(uri.query,keep_blank_values=True,strict_parsing=True,max_num_fields=8,errors='strict')
        if set(params)-({'code','state','error','error_reason','error_description'} | set(allowed_extra)) or any(len(values)!=1 for values in params.values()): raise ValueError()
        if "error" in params or "error_reason" in params or "error_description" in params or not params.get('code',[''])[0].strip() or not params.get('state',[''])[0]:raise ValueError()
        state.consume(params['state'][0])
        return params['code'][0]
    except (ValueError,UnicodeError):raise ValueError('OAuth redirect is canceled or invalid') from None



def save_token(path,token,*,granted_scopes=None):
    # Revalidate even constructed/mutated models before touching the secret file.
    try:
        token=Token.model_validate(token.model_dump())
    except ValidationError:
        raise InstagramInvalidResponseError("local_env", "token_storage_validation") from None
    from app.cli.secret_env import save_env
    if granted_scopes is not None and set(granted_scopes)!=set(SCOPES):
        raise ValueError("Exact read-only grant required")
    updates={"INSTAGRAM_ACCESS_TOKEN":token.access_token.get_secret_value(),"INSTAGRAM_TOKEN_ISSUED_AT":datetime.now(timezone.utc).isoformat(),"INSTAGRAM_TOKEN_EXPIRES_IN":str(token.expires_in)}
    if granted_scopes is not None:updates["INSTAGRAM_GRANTED_SCOPES"]=",".join(sorted(granted_scopes))
    save_env(path,updates)


def main(argv=None):
    parser=argparse.ArgumentParser(description="Instagram OAuth bootstrap into a private .env file")
    parser.add_argument("--env-file",default=".env")
    parser.add_argument("--refresh",action="store_true")
    parser.add_argument("--callback-port",type=int,help="Dedicated local callback port behind a separately approved HTTPS tunnel")
    parser.add_argument("--timeout",type=int,default=300)
    args=parser.parse_args(argv)
    try:
        settings=Settings(_env_file=args.env_file)
        with InstagramAuth(settings) as auth:
            if args.refresh:
                token=auth.refresh(settings.require_instagram_token())
            else:
                settings.require_instagram_oauth()
                if not 1<=args.timeout<=600:raise ValueError("Invalid callback timeout")
                state=OAuthState(ttl=args.timeout)
                if args.callback_port is not None:
                    if not 1<=args.callback_port<=65535 or args.callback_port==8000:raise ValueError('Dedicated callback port required')
                    path=urlsplit(settings.instagram_redirect_uri).path
                    if not path.startswith("/"):raise ValueError("Explicit callback path required")
                    with LoopbackCallback(f'http://127.0.0.1:{args.callback_port}{path}',settings.instagram_redirect_uri,state,parse_redirect,timeout=args.timeout) as callback:
                        print('Open this read-only authorization URL in your browser:')
                        print(auth.authorization_url(state))
                        code=callback.wait()
                else:
                    print("Open this read-only authorization URL in your browser:")
                    print(auth.authorization_url(state))
                    received=getpass("Paste the full final HTTPS redirect URL (hidden input): ")
                    code=parse_redirect(received,settings.instagram_redirect_uri,state)
                token=auth.exchange_code(code)
            save_token(args.env_file,token,granted_scopes=auth.granted_scopes if not args.refresh else None)
        print("Instagram token saved to private environment file; token is not printed. Restart containers after updating host .env.")
        return 0
    except (ValueError,ValidationError,InstagramError,OSError):
        print("Instagram authorization failed: verify app settings, redirect, state, permissions and private env file",file=sys.stderr)
        return 1
    except (KeyboardInterrupt,EOFError):
        print("Instagram authorization canceled",file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
