class TikTokError(Exception):
    def __init__(self,endpoint,operation,http_status=None,code=None):
        self.endpoint,self.operation,self.http_status,self.code=endpoint,operation,http_status,code
        super().__init__(f'{type(self).__name__}: endpoint={endpoint} operation={operation} http_status={http_status} code={code}')


class TikTokAuthError(TikTokError): pass
class TikTokPermissionError(TikTokError): pass
class TikTokRateLimitError(TikTokError): pass
class TikTokInvalidResponseError(TikTokError): pass
class TikTokAPIError(TikTokError): pass
class TikTokIdentityError(TikTokError): pass
class TikTokPaginationError(TikTokError): pass
class TikTokDatabaseError(TikTokError): pass
