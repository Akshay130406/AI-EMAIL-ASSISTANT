from starlette.types import ASGIApp, Receive, Scope, Send


class OAuthCallbackQueryRedactionMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        is_oauth_callback = scope["type"] == "http" and scope.get("path") in {
            "/api/auth/google/callback",
            "/api/integrations/gmail/callback",
            "/api/integrations/calendar/callback",
        }
        if not is_oauth_callback:
            await self.app(scope, receive, send)
            return

        application_scope = dict(scope)
        application_scope["query_string"] = scope["query_string"]
        scope["query_string"] = b""
        await self.app(application_scope, receive, send)
