"""Only provider CDN image URLs; no fetching or signed-query rewriting."""
from urllib.parse import urlsplit, parse_qsl
import re

CDN_DOMAINS = ('cdninstagram.com', 'fbcdn.net', 'tiktokcdn.com', 'tiktokcdn-us.com', 'tiktokcdn-eu.com', 'ibytedtos.com')


def safe_preview_url(value):
    if not isinstance(value, str) or not value or len(value) > 8192 or any(c.isspace() or ord(c) < 32 for c in value):
        return None
    try:
        url = urlsplit(value)
        if url.scheme != 'https' or url.username or url.password or url.port not in (None, 443):
            return None
        host = (url.hostname or '').lower()
        if not any(host == domain or host.endswith('.' + domain) for domain in CDN_DOMAINS):
            return None
        query = parse_qsl(url.query, keep_blank_values=True)
        # TikTok's signed CDN uses an 8-hex refresh_token cache marker, not OAuth.
        marker = [(k, v) for k, v in query if k.lower() == 'refresh_token']
        tiktok = any(host == d or host.endswith('.' + d) for d in CDN_DOMAINS[2:5])
        fields = dict(query)
        cdn_marker = (tiktok and len(marker) == 1 and marker[0][0] == 'refresh_token'
                      and re.fullmatch(r'[0-9a-f]{8}', marker[0][1])
                      and fields.get('x-expires', '').isdigit() and bool(fields.get('x-signature')))
        if any(k.lower() in ('access_token', 'client_secret', 'authorization', 'code') for k, _ in query) or (marker and not cdn_marker):
            return None
    except ValueError:
        return None
    return value
