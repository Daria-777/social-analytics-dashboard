"""Display API only. POST video/list and video/query are reads; OAuth POST is never retried."""
import logging
import time
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
import httpx
from app.connectors.instagram.client import SecretFilter
from .errors import TikTokAPIError,TikTokAuthError,TikTokPermissionError,TikTokRateLimitError,TikTokInvalidResponseError

log=logging.getLogger(__name__)
VIDEO_FIELDS='id,create_time,duration,video_description,title,share_url,cover_image_url,view_count,like_count,comment_count,share_count'
USER_FIELDS='open_id,username,display_name'
CODES={'ok','access_token_invalid','scope_not_authorized','scope_permission_missed','rate_limit_exceeded','internal_error','invalid_params','invalid_client','invalid_grant','invalid_request','unauthorized_client','unsupported_grant_type','invalid_scope'}
LOGGERS=('httpx','httpcore','httpcore.connection','httpcore.http11','httpcore.http2')


class TikTokClient:
    def __init__(self,token,*,transport=None,max_retries=2,sleep=time.sleep,secrets=()):
        self.token,self.max_retries,self.sleep=token,max_retries,sleep
        self.http=httpx.Client(transport=transport,timeout=httpx.Timeout(connect=5,read=25,write=10,pool=5),follow_redirects=False)
        self.filter=SecretFilter((token,*secrets))
        for name in LOGGERS: logging.getLogger(name).addFilter(self.filter)
    def __enter__(self): return self
    def __exit__(self,*_): self.close()
    def close(self):
        self.http.close()
        for name in LOGGERS: logging.getLogger(name).removeFilter(self.filter)
    def user(self,*,stats=False):
        fields='open_id,follower_count,following_count,likes_count,video_count' if stats else USER_FIELDS
        return self.request('GET','/v2/user/info/',params={'fields':fields})
    def videos(self,cursor):
        body={'max_count':20}
        if cursor is not None: body['cursor']=cursor
        return self.request('POST','/v2/video/list/',params={'fields':VIDEO_FIELDS},json=body)
    def cover(self,video_id):
        if not isinstance(video_id,str) or not video_id.isdigit(): raise ValueError('Invalid video ID')
        return self.request('POST','/v2/video/query/',params={'fields':'id,cover_image_url'},json={'filters':{'video_ids':[video_id]}})
    def oauth(self,data):
        self.filter.secrets+=tuple(v for k,v in data.items() if k in ('client_secret','code','code_verifier','refresh_token') and v)
        return self.request('POST','/v2/oauth/token/',data=data)
    def request(self,method,path,**kwargs):
        if (method,path) not in (('GET','/v2/user/info/'),('POST','/v2/video/list/'),('POST','/v2/video/query/'),('POST','/v2/oauth/token/')):
            raise ValueError('Only Display API reads and token exchange are permitted')
        oauth=path=='/v2/oauth/token/'
        for attempt in range(1 if oauth else self.max_retries+1):
            response=None;start=time.monotonic()
            try:
                response=self.http.request(method,'https://open.tiktokapis.com'+path,headers={} if oauth else {'Authorization':f'Bearer {self.token}'},**kwargs)
                try: payload=response.json()
                except ValueError:
                    if response.status_code>=300: payload={}
                    else: raise TikTokInvalidResponseError(path,'normalize_json',response.status_code) from None
                if not isinstance(payload,dict):
                    if response.status_code>=300: payload={}
                    else: raise TikTokInvalidResponseError(path,'normalize_json',response.status_code)
                error=payload.get('error')
                raw_code=error.get('code') if isinstance(error,dict) else error
                code=raw_code if isinstance(raw_code,str) and raw_code in CODES else 'unknown' if raw_code else None
                if response.status_code>=300 or (error is not None and code!='ok'):
                    status=response.status_code
                    if code in ('scope_not_authorized','scope_permission_missed'): kind=TikTokPermissionError
                    elif status==401 or code=='access_token_invalid': kind=TikTokAuthError
                    elif status==429 or code=='rate_limit_exceeded': kind=TikTokRateLimitError
                    else: kind=TikTokAPIError
                    raise kind(path,'oauth_token' if oauth else 'display_read',status,code)
                if not oauth and (not isinstance(error,dict) or code!='ok' or not isinstance(payload.get('data'),dict)):
                    raise TikTokInvalidResponseError(path,'normalize_envelope',response.status_code)
                log.info('TikTok request',extra={'platform':'tiktok','operation':'oauth_token' if oauth else 'display_read','status':response.status_code,'request_duration':time.monotonic()-start})
                return payload
            except (TikTokAuthError,TikTokPermissionError,TikTokInvalidResponseError) as error:
                log.warning('TikTok request rejected',extra={'platform':'tiktok','operation':error.operation,'status':error.http_status,'request_duration':time.monotonic()-start,'error_type':type(error).__name__})
                raise error from None
            except httpx.TransportError:
                failure=TikTokAPIError(path,'oauth_token' if oauth else 'display_read')
            except (TikTokAPIError,TikTokRateLimitError) as error:
                failure=error
            log.warning('TikTok request failed',extra={'platform':'tiktok','operation':failure.operation,'status':failure.http_status,'request_duration':time.monotonic()-start,'error_type':type(failure).__name__})
            retryable=isinstance(failure,TikTokRateLimitError) or failure.http_status is None or failure.http_status>=500
            if oauth or not retryable or attempt==self.max_retries: raise failure from None
            delay=2**attempt
            if response is not None and response.headers.get('Retry-After'):
                value=response.headers['Retry-After']
                try: delay=max(delay,float(value))
                except ValueError:
                    try: delay=max(delay,(parsedate_to_datetime(value)-datetime.now(timezone.utc)).total_seconds())
                    except (ValueError,TypeError,OverflowError): pass
            if delay>60: raise failure from None
            self.sleep(max(0,delay))
