class InstagramError(Exception):
    """Only allowlisted context, never provider messages or request URLs."""
    def __init__(self, endpoint, operation, http_status=None, meta_code=None):
        self.endpoint = endpoint
        self.operation = operation
        self.http_status = http_status
        self.meta_code = meta_code
        super().__init__(f"{type(self).__name__}: operation={operation} endpoint={endpoint} http_status={http_status} meta_code={meta_code}")


class InstagramAuthError(InstagramError): pass
class InstagramPermissionError(InstagramError): pass
class InstagramRateLimitError(InstagramError): pass
class InstagramAPIError(InstagramError): pass
class InstagramInvalidResponseError(InstagramError): pass
class InstagramUnsupportedMetricError(InstagramError): pass
class InstagramPaginationError(InstagramError): pass

class InstagramIdentityError(InstagramError): pass
class InstagramDatabaseError(InstagramError): pass
class InstagramUnavailableMetricError(InstagramError): pass
