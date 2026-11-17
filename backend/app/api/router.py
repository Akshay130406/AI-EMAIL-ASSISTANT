from fastapi import APIRouter

from app.api.routes import (
    analytics,
    ai,
    auto_replies,
    automation,
    auth,
    calendar,
    conversations,
    dashboard,
    drafts,
    emails,
    gmail,
    gmail_drafts,
    health,
    settings,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(analytics.router)
api_router.include_router(automation.router)
api_router.include_router(auth.router)
api_router.include_router(dashboard.router)
api_router.include_router(emails.router)
api_router.include_router(gmail.router)
api_router.include_router(gmail_drafts.router)
api_router.include_router(calendar.router)
api_router.include_router(ai.router)
api_router.include_router(auto_replies.router)
api_router.include_router(drafts.router)
api_router.include_router(conversations.router)
api_router.include_router(settings.router)
