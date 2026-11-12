from datetime import date, datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import APIModel


class DailyAnalytics(APIModel):
    day: date
    received: int = Field(ge=0)
    sent: int = Field(ge=0)


class AnalyticsOverview(APIModel):
    source: Literal["gmail", "sample"]
    period_days: int
    total_received: int = Field(ge=0)
    total_sent: int = Field(ge=0)
    unread: int = Field(ge=0)
    starred: int = Field(ge=0)
    priority: int = Field(ge=0)
    daily: list[DailyAnalytics]
    generated_at: datetime
