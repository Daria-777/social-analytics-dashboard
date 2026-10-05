"""Only opt-in, isolated local PostgreSQL test_dash; never read DATABASE_URL."""
import os
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


def test_engine():
    import pytest
    value=os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.skip("PostgreSQL unavailable: set isolated TEST_DATABASE_URL for test_dash")
    url=make_url(value)
    if url.get_backend_name()!="postgresql" or url.database!="test_dash" or url.host not in ("localhost","127.0.0.1","::1","postgres"):
        raise ValueError("Only local PostgreSQL test_dash is allowed")
    return create_engine(url,hide_parameters=True)
