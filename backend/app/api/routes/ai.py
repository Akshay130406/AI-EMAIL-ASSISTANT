from uuid import UUID

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status

from app.api.dependencies import CurrentUser, CsrfProtectedUser, DatabaseSession
from app.schemas.ai import (
    AIInsightsResponse,
    CopilotRequest,
    CopilotResult,
    EmailClassification,
    EmailSummary,
    ReplySuggestion,
    RewriteRequest,
    RewriteResponse,
    WriteRequest,
    WriteResponse,
)
from app.services import ai as ai_service

router = APIRouter(prefix="/ai", tags=["AI email assistant"])


def _raise_ai_error(error: Exception) -> None:
    if isinstance(error, ai_service.AIGmailNotConnected):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connect Gmail and synchronize messages before using email intelligence",
        ) from error
    if isinstance(error, ai_service.AIConfigurationMissing):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemini is not configured",
        ) from error
    if isinstance(error, ai_service.AIUsageLimitExceeded):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="AI usage limit reached; try again shortly",
        ) from error
    if isinstance(error, ai_service.AIProviderRateLimited):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Gemini is rate limited; try again shortly",
        ) from error
    if isinstance(error, ai_service.AIProviderTimeout):
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Gemini did not respond in time",
        ) from error
    if isinstance(error, ai_service.AIInputTooLarge):
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Email context exceeds the configured AI input limit",
        ) from error
    if isinstance(error, ai_service.AIInvalidOutput):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gemini returned an invalid response; try again",
        ) from error
    if isinstance(error, ai_service.AIProviderUnavailable):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gemini is temporarily unavailable",
        ) from error
    if isinstance(error, LookupError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email or thread not found",
        ) from error
    raise error


@router.post("/classify/{email_id}", response_model=EmailClassification)
def classify_email(
    email_id: UUID,
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> EmailClassification:
    try:
        return ai_service.classify_email(session, user, email_id)
    except ai_service.AIError as error:
        _raise_ai_error(error)
    except LookupError as error:
        _raise_ai_error(error)


@router.post("/summarize/{email_id}", response_model=EmailSummary)
def summarize_email(
    email_id: UUID,
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> EmailSummary:
    try:
        return ai_service.summarize_email(session, user, email_id)
    except ai_service.AIError as error:
        _raise_ai_error(error)
    except LookupError as error:
        _raise_ai_error(error)


@router.post("/summarize-thread/{thread_id}", response_model=EmailSummary)
def summarize_thread(
    thread_id: Annotated[str, Path(min_length=1, max_length=255)],
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> EmailSummary:
    try:
        return ai_service.summarize_thread(session, user, thread_id)
    except ai_service.AIError as error:
        _raise_ai_error(error)
    except LookupError as error:
        _raise_ai_error(error)


@router.post("/write", response_model=WriteResponse)
def write_email(
    payload: WriteRequest,
    user: CsrfProtectedUser,
) -> WriteResponse:
    try:
        return ai_service.write_email(user, payload)
    except ai_service.AIError as error:
        _raise_ai_error(error)


@router.post("/rewrite", response_model=RewriteResponse)
def rewrite_email(
    payload: RewriteRequest,
    user: CsrfProtectedUser,
) -> RewriteResponse:
    try:
        return ai_service.rewrite_email(user, payload)
    except ai_service.AIError as error:
        _raise_ai_error(error)


@router.post("/reply-suggestion/{email_id}", response_model=ReplySuggestion)
def suggest_reply(
    email_id: UUID,
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> ReplySuggestion:
    try:
        return ai_service.suggest_reply(session, user, email_id)
    except ai_service.AIError as error:
        _raise_ai_error(error)
    except LookupError as error:
        _raise_ai_error(error)


@router.post("/copilot", response_model=CopilotResult)
def copilot(
    payload: CopilotRequest,
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> CopilotResult:
    try:
        response, sources = ai_service.copilot(session, user, payload)
        return CopilotResult(
            answer=response.answer,
            sources=sources,
        )
    except ai_service.AIError as error:
        _raise_ai_error(error)
    except LookupError as error:
        _raise_ai_error(error)


@router.get("/insights", response_model=AIInsightsResponse)
def insights(
    session: DatabaseSession,
    user: CurrentUser,
) -> AIInsightsResponse:
    try:
        return ai_service.get_insights(session, user)
    except ai_service.AIError as error:
        _raise_ai_error(error)
