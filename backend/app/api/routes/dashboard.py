from fastapi import APIRouter

from app.api.dependencies import CurrentUser, DatabaseSession
from app.schemas.dashboard import DashboardOverview
from app.services.dashboard import get_dashboard_overview

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview", response_model=DashboardOverview)
def dashboard_overview(session: DatabaseSession, user: CurrentUser) -> DashboardOverview:
    return DashboardOverview(**get_dashboard_overview(session, user))
