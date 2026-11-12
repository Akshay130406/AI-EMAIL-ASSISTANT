import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import DatabaseSession
from app.schemas.health import HealthResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health_check() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse, tags=["health"])
def readiness_check(session: DatabaseSession) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        logger.warning("Database readiness probe failed (%s)", type(error).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from error
    return HealthResponse(status="ok")
