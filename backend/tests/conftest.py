import asyncio
import sys
from collections.abc import Iterator
from pathlib import Path

backend_path = str(Path(__file__).resolve().parents[1])
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import SESSION_COOKIE_NAME, get_current_user
from app.database.session import get_db
from app.main import app
from app.models import Base, User
from app.services.auth import create_user_session


class APIClient:
    def __init__(
        self,
        application: FastAPI,
        session_token: str | None = None,
        csrf_token: str | None = None,
    ):
        self.application = application
        self.session_token = session_token
        self.csrf_token = csrf_token

    def set_session(self, session_token: str | None, csrf_token: str | None) -> None:
        self.session_token = session_token
        self.csrf_token = csrf_token

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.application)
            headers = dict(kwargs.pop("headers", {}))
            cookies = dict(kwargs.pop("cookies", {}))
            if self.session_token:
                cookies[SESSION_COOKIE_NAME] = self.session_token
            if method.upper() in {"POST", "PATCH", "PUT", "DELETE"}:
                headers.setdefault("Origin", "http://localhost:5173")
                if self.csrf_token:
                    headers.setdefault("X-CSRF-Token", self.csrf_token)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
                cookies=cookies,
            ) as client:
                return await client.request(method, url, headers=headers, **kwargs)

        return asyncio.run(send())

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def patch(self, url: str, **kwargs) -> httpx.Response:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs) -> httpx.Response:
        return self.request("DELETE", url, **kwargs)


@pytest.fixture
def db_session_factory() -> Iterator[sessionmaker[Session]]:
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(test_engine)
        test_engine.dispose()


@pytest.fixture
def client(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[APIClient]:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv(
        "SESSION_SECRET", "test-session-secret-with-more-than-thirty-two-characters"
    )
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )

    def get_test_db() -> Iterator[Session]:
        with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides.pop(get_current_user, None)
    with db_session_factory() as session:
        user = User(email="developer@example.test", display_name="Test User")
        session.add(user)
        session.commit()
        session.refresh(user)
        session_token, csrf_token, _ = create_user_session(session, user)
    try:
        yield APIClient(app, session_token, csrf_token)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(
    db_session_factory: sessionmaker[Session],
) -> Iterator[APIClient]:
    def get_test_db() -> Iterator[Session]:
        with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides.pop(get_current_user, None)
    try:
        yield APIClient(app)
    finally:
        app.dependency_overrides.clear()
