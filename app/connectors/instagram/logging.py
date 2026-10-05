"""Render allowlisted log-record context without request headers or payloads."""
import json
import logging
import re
from datetime import datetime,timezone


class InstagramLogFormatter(logging.Formatter):
    def format(self,record):
        fields={"timestamp":datetime.fromtimestamp(record.created,timezone.utc).isoformat(),
                "level":record.levelname,"logger":record.name,"message":re.sub(r"((?:access_token|client_secret|code)=)[^&\s\"']+",r"\1[REDACTED]",record.getMessage())}
        for key in ("platform","operation","content_id","status","request_duration","error_type"):
            fields[key]=getattr(record,key,None)
        return json.dumps(fields,ensure_ascii=False)
