"""One-shot, bounded HTTP loopback receiver. Never log OAuth request targets."""
from app.cli.loopback_callback import LoopbackCallback
from urllib.parse import parse_qs, urlsplit


def parse_desktop_redirect(received, expected, state):
    target, uri = urlsplit(expected), urlsplit(received)
    if target.scheme != 'http' or target.hostname not in ('localhost', '127.0.0.1') or not target.port:
        raise ValueError('Desktop HTTP loopback callback required')
    if target.query or target.fragment or target.username or target.password:
        raise ValueError('Invalid desktop callback configuration')
    if (uri.scheme, uri.netloc, uri.path) != (target.scheme, target.netloc, target.path) or uri.fragment:
        raise ValueError('Desktop callback does not match')
    try:
        params = parse_qs(uri.query, keep_blank_values=True, strict_parsing=True, max_num_fields=8, errors='strict')
        if len(uri.query) > 8192 or set(params) - {'code', 'state', 'scopes', 'error', 'error_description'}:
            raise ValueError()
        if any(len(values) != 1 for values in params.values()) or not params.get('state', [''])[0]:
            raise ValueError()
        if 'error' in params:
            if 'code' in params: raise ValueError()
            state.consume(params['state'][0])
            raise ValueError()
        if 'error_description' in params or not params.get('code', [''])[0].strip():
            raise ValueError()
        state.consume(params['state'][0])
        return params['code'][0]
    except (ValueError, UnicodeError):
        raise ValueError('Desktop authorization response is canceled or invalid') from None


class DesktopCallback(LoopbackCallback):
    def __init__(self, settings, state, *, timeout=300):
        settings.require_tiktok_oauth()
        if settings.tiktok_oauth_mode!='desktop': raise ValueError('Desktop mode required')
        super().__init__(settings.tiktok_redirect_uri,settings.tiktok_redirect_uri,state,parse_desktop_redirect,timeout=timeout)
