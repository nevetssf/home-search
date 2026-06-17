"""SQLAlchemy engine/session setup.

SQLite now, Postgres-swappable via DATABASE_URL (PLAN.md §11). The SQLite-only
``check_same_thread`` arg is applied conditionally so a Postgres URL is a clean
drop-in. Avoid SQLite-only SQL in models/queries to keep the port honest.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency yielding a session that always closes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create tables for first-run / tests. Production schema is Alembic-managed."""
    from . import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(bind=engine)
