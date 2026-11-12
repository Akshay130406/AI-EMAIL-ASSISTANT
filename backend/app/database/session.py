from collections.abc import Generator

from fastapi import HTTPException, status
from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_database_url


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def _build_engine() -> Engine | None:
    database_url = get_database_url()
    if not database_url:
        return None

    database_url = normalize_database_url(database_url)

    engine_options = {"pool_pre_ping": True}
    if database_url.startswith("sqlite:"):
        engine_options["connect_args"] = {"check_same_thread": False}
    database_engine = create_engine(database_url, **engine_options)
    if database_engine.dialect.name == "sqlite":
        @event.listens_for(database_engine, "connect")
        def enable_sqlite_foreign_keys(connection, _record) -> None:
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return database_engine


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not configured",
        )

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
