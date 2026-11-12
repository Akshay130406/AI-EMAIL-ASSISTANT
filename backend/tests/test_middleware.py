import asyncio

import pytest

from app.middleware import OAuthCallbackQueryRedactionMiddleware


@pytest.mark.parametrize(
    "path",
    [
        "/api/auth/google/callback",
        "/api/integrations/gmail/callback",
        "/api/integrations/calendar/callback",
    ],
)
def test_oauth_callback_query_is_available_to_routes_but_removed_from_outer_scope(path):
    scope = {
        "type": "http",
        "path": path,
        "query_string": b"state=sample-state&code=sample-auth-code",
    }
    routed_query = None

    async def app(application_scope, _receive, send):
        nonlocal routed_query
        routed_query = application_scope["query_string"]
        await send({"type": "http.response.start", "status": 400, "headers": []})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    middleware = OAuthCallbackQueryRedactionMiddleware(app)
    asyncio.run(middleware(scope, receive, send))

    assert routed_query == b"state=sample-state&code=sample-auth-code"
    assert scope["query_string"] == b""
