from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.dependencies import CurrentUser, CsrfProtectedUser, DatabaseSession
from app.schemas.automation import (
    AutomationCreate,
    AutomationRead,
    AutomationUpdate,
    BackgroundJobRead,
    JobPage,
    NotificationPage,
    NotificationRead,
    NotificationReadUpdate,
)
from app.services import automation as automation_service

router = APIRouter(tags=["Automations and notifications"])


def _raise_not_found(error: LookupError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Automation, job, or notification not found",
    )


def _raise_queue_limit(error: ValueError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Automation queue limit reached; wait for pending jobs to finish",
    )


@router.get("/automations", response_model=list[AutomationRead])
def automation_list(
    session: DatabaseSession,
    user: CurrentUser,
) -> list[AutomationRead]:
    return [
        AutomationRead.model_validate(rule)
        for rule in automation_service.list_automations(session, user)
    ]


@router.post(
    "/automations",
    response_model=AutomationRead,
    status_code=status.HTTP_201_CREATED,
)
def automation_create(
    payload: AutomationCreate,
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> AutomationRead:
    try:
        rule = automation_service.create_automation(
            session,
            user,
            kind=payload.kind,
            interval_minutes=payload.interval_minutes,
            enabled=payload.enabled,
        )
    except automation_service.AutomationAlreadyExists as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An automation of this type already exists",
        ) from error
    return AutomationRead.model_validate(rule)


@router.patch("/automations/{automation_id}", response_model=AutomationRead)
def automation_update(
    automation_id: UUID,
    payload: AutomationUpdate,
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> AutomationRead:
    try:
        rule = automation_service.update_automation(
            session,
            user,
            automation_id,
            interval_minutes=payload.interval_minutes,
            enabled=payload.enabled,
        )
    except automation_service.AutomationNotFound as error:
        raise _raise_not_found(error) from error
    return AutomationRead.model_validate(rule)


@router.delete(
    "/automations/{automation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def automation_delete(
    automation_id: UUID,
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> Response:
    try:
        automation_service.delete_automation(session, user, automation_id)
    except automation_service.AutomationNotFound as error:
        raise _raise_not_found(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/automations/{automation_id}/run",
    response_model=BackgroundJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def automation_run(
    automation_id: UUID,
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> BackgroundJobRead:
    try:
        job = automation_service.request_manual_run(
            session, user, automation_id
        )
    except automation_service.AutomationNotFound as error:
        raise _raise_not_found(error) from error
    except automation_service.AutomationQueueLimit as error:
        raise _raise_queue_limit(error) from error
    return BackgroundJobRead.model_validate(job)


@router.get("/jobs", response_model=JobPage)
def job_list(
    session: DatabaseSession,
    user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> JobPage:
    items, total = automation_service.list_jobs(
        session, user, page=page, page_size=page_size
    )
    return JobPage(
        items=[BackgroundJobRead.model_validate(job) for job in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/jobs/{job_id}/cancel", response_model=BackgroundJobRead)
def job_cancel(
    job_id: UUID,
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> BackgroundJobRead:
    try:
        job = automation_service.cancel_job(session, user, job_id)
    except automation_service.JobNotFound as error:
        raise _raise_not_found(error) from error
    except automation_service.JobNotCancellable as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only queued jobs can be cancelled",
        ) from error
    return BackgroundJobRead.model_validate(job)


@router.get("/notifications", response_model=NotificationPage)
def notification_list(
    session: DatabaseSession,
    user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> NotificationPage:
    items, total, unread_count = automation_service.list_notifications(
        session, user, page=page, page_size=page_size
    )
    return NotificationPage(
        items=[NotificationRead.model_validate(item) for item in items],
        total=total,
        unread_count=unread_count,
        page=page,
        page_size=page_size,
    )


@router.patch(
    "/notifications/{notification_id}",
    response_model=NotificationRead,
)
def notification_update(
    notification_id: UUID,
    payload: NotificationReadUpdate,
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> NotificationRead:
    try:
        notification = automation_service.update_notification_read(
            session,
            user,
            notification_id,
            read=payload.read,
        )
    except LookupError as error:
        raise _raise_not_found(error) from error
    return NotificationRead.model_validate(notification)
