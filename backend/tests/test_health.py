import asyncio

import httpx

from app.main import app


def request(
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, headers=headers)

    return asyncio.run(send_request())


def test_health_endpoint_returns_ok() -> None:
    response = request("GET", "/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_endpoint_checks_database(client) -> None:
    response = client.get("/api/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_endpoint_reports_database_dependency_failure(client) -> None:
    from fastapi import HTTPException

    from app.database.session import get_db

    def unavailable_database():
        raise HTTPException(status_code=503, detail="Database is not configured")

    app.dependency_overrides[get_db] = unavailable_database
    response = client.get("/api/ready")

    assert response.status_code == 503


def test_health_endpoint_allows_local_frontend_origin() -> None:
    response = request(
        "OPTIONS",
        "/api/health",
        {
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5174"


def test_mutating_api_preflight_allows_patch_from_local_frontend() -> None:
    response = request(
        "OPTIONS",
        "/api/emails/00000000-0000-0000-0000-000000000000",
        {
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5174"
    assert "PATCH" in response.headers["access-control-allow-methods"]
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "x-csrf-token" in response.headers["access-control-allow-headers"].lower()
