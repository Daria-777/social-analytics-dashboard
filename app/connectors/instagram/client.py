"""HTTP only. Graph reads use bearer auth; OAuth queries follow Meta's contract."""
import logging
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
import httpx
from .errors import (InstagramAPIError, InstagramAuthError, InstagramPermissionError,
                     InstagramRateLimitError, InstagramInvalidResponseError, InstagramUnsupportedMetricError)

log = logging.getLogger(__name__)


class SecretFilter(logging.Filter):
    def __init__(self, secrets):
        super().__init__(); self.secrets = tuple(s for s in secrets if s)
    def filter(self, record):
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "[REDACTED]")
        message = re.sub(r"((?:access_token|client_secret|code)=)[^&\s\"']+", r"\1[REDACTED]", message)
        record.msg, record.args = message, ()
        return True


class InstagramClient:
    def __init__(self, token, version, *, transport=None, max_retries=2, sleep=time.sleep, secrets=()):
        if not re.fullmatch(r"v\d+\.\d+", version):
            raise ValueError("Invalid Instagram API version")
        self.token, self.version = token, version
        self.max_retries, self.sleep = max_retries, sleep
        self.http = httpx.Client(transport=transport, timeout=httpx.Timeout(connect=5,read=25,write=10,pool=5), follow_redirects=False)
        self.filter = SecretFilter((token, *secrets))
        for name in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
            logging.getLogger(name).addFilter(self.filter)

    def __enter__(self): return self
    def __exit__(self, *_): self.close()
    def close(self):
        self.http.close()
        for name in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
            logging.getLogger(name).removeFilter(self.filter)

    def get(self, endpoint, *, operation, params=None):
        if not re.fullmatch(r"(?:me|\d+)(?:/media|/insights)?", endpoint):
            raise ValueError("Invalid Graph endpoint")
        return self.request("GET", f"https://graph.instagram.com/{self.version}/{endpoint}",
                            endpoint=endpoint, operation=operation, params=params, bearer=True, retry=True)

    def request(self, method, url, *, endpoint, operation, params=None, data=None, bearer=False, retry=False):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc not in ("graph.instagram.com", "api.instagram.com") or parsed.query:
            raise ValueError("Only official Instagram HTTPS endpoints are allowed")
        graph_read = (parsed.netloc == "graph.instagram.com" and method == "GET"
                      and re.fullmatch(r"/v\d+\.\d+/(?:me|\d+)(?:/media|/insights)?", parsed.path))
        token_operation = (parsed.netloc == "graph.instagram.com" and method == "GET"
                           and parsed.path in ("/access_token", "/refresh_access_token"))
        code_exchange = (parsed.netloc == "api.instagram.com" and method == "POST"
                         and parsed.path == "/oauth/access_token")
        if not (graph_read or token_operation or code_exchange):
            raise ValueError("Only analytics reads and documented OAuth operations are allowed")
        if retry and not graph_read:
            raise ValueError("OAuth operations must not be automatically retried")
        for attempt in range(self.max_retries + 1 if retry else 1):
            start=time.monotonic(); response=None
            try:
                response=self.http.request(method,url,params=params,data=data,headers={"Authorization":f"Bearer {self.token}"} if bearer else {})
                try: payload=response.json()
                except ValueError:
                    if response.status_code >= 300:
                        payload={}
                    else: raise InstagramInvalidResponseError(endpoint,operation,response.status_code) from None
                if not isinstance(payload,dict):
                    if response.status_code>=300: payload={}
                    else: raise InstagramInvalidResponseError(endpoint,operation,response.status_code)
                provider_error=payload.get("error")
                if isinstance(provider_error, dict):
                    code=provider_error.get("code")
                    code=code if isinstance(code,int) else None
                else: code=None
                if response.status_code>=300 or provider_error is not None or payload.get("error_type"):
                    status=response.status_code
                    if status==401 or code==190 or payload.get("error_type")=="OAuthException": cls=InstagramAuthError
                    elif status==429 or code in (4,17,32,613,80002): cls=InstagramRateLimitError
                    elif status==403 or code in (10,200): cls=InstagramPermissionError
                    elif code==100 and isinstance(provider_error,dict) and "metric" in str(provider_error.get("message","")).lower(): cls=InstagramUnsupportedMetricError
                    else: cls=InstagramAPIError
                    raise cls(endpoint,operation,status,code)
                log.info("instagram request",extra={"platform":"instagram","operation":operation,"content_id":endpoint.split('/')[0],"status":response.status_code,"request_duration":time.monotonic()-start,"error_type":None})
                return payload
            except httpx.TransportError:
                error=InstagramAPIError(endpoint,operation)
            except (InstagramAPIError,InstagramRateLimitError) as exc:
                error=exc
            except (InstagramAuthError,InstagramPermissionError,InstagramInvalidResponseError,InstagramUnsupportedMetricError) as exc:
                self._log_failure(endpoint,operation,start,exc)
                raise exc from None
            self._log_failure(endpoint,operation,start,error)
            safe_retry = isinstance(error,InstagramRateLimitError) or error.http_status is None or (error.http_status is not None and error.http_status>=500)
            if not retry or not safe_retry or attempt==self.max_retries:
                raise error from None
            delay=2**attempt
            if response is not None and response.headers.get("Retry-After"):
                value=response.headers["Retry-After"]
                try: delay=max(delay,float(value))
                except ValueError:
                    try: delay=max(delay,(parsedate_to_datetime(value)-datetime.now(timezone.utc)).total_seconds())
                    except (ValueError,TypeError,OverflowError): pass
            if delay>60:
                raise error from None  # Do not retry earlier than the provider requested.
            self.sleep(max(0,delay))

    def _log_failure(self,endpoint,operation,start,error):
        log.warning("instagram request failed",extra={"platform":"instagram","operation":operation,"content_id":endpoint.split('/')[0],"status":error.http_status,"request_duration":time.monotonic()-start,"error_type":type(error).__name__})
