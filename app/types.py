from datetime import datetime, timezone
from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """Require aware inputs; use TIMESTAMPTZ on PostgreSQL and UTC on every dialect."""
    impl = DateTime(timezone=True)
    cache_ok = True

    @property
    def python_type(self):
        return datetime

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timezone offset is required")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def utc_now():
    return datetime.now(timezone.utc)
