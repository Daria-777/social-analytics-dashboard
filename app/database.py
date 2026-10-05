from functools import lru_cache
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.config import Settings


@lru_cache
def get_engine():
    return create_engine(Settings().database_url.get_secret_value(), pool_pre_ping=True, hide_parameters=True)


def get_session():
    with Session(get_engine()) as session:
        yield session
