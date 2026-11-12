from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUser, DatabaseSession
from app.schemas.analytics import AnalyticsOverview
from app.services.analytics import get_analytics_overview

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/overview", response_model=AnalyticsOverview)
def analytics_overview(
    session: DatabaseSession,
    user: CurrentUser,
    period_days: Annotated[int, Query(ge=7, le=90)] = 7,
) -> AnalyticsOverview:
    return AnalyticsOverview.model_validate(
        get_analytics_overview(
            session,
            user,
            period_days=period_days,
        )
    )
