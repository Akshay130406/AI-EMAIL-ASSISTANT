from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.dependencies import CurrentUser, CsrfProtectedUser, DatabaseSession
from app.schemas.draft import DraftCreate, DraftListResponse, DraftPatch, DraftRead
from app.services.drafts import (
    create_draft,
    delete_draft,
    get_draft,
    list_drafts,
    update_draft,
)

router = APIRouter(prefix="/drafts", tags=["drafts"])


@router.get("", response_model=DraftListResponse)
def drafts_list(
    session: DatabaseSession,
    user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> DraftListResponse:
    return DraftListResponse(
        **list_drafts(session, user, page=page, page_size=page_size)
    )


@router.post("", response_model=DraftRead, status_code=status.HTTP_201_CREATED)
def draft_create(
    payload: DraftCreate, session: DatabaseSession, user: CsrfProtectedUser
) -> DraftRead:
    return DraftRead.model_validate(
        create_draft(session, user, payload.model_dump())
    )


@router.get("/{draft_id}", response_model=DraftRead)
def draft_detail(
    draft_id: UUID, session: DatabaseSession, user: CurrentUser
) -> DraftRead:
    draft = get_draft(session, user, draft_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    return DraftRead.model_validate(draft)


@router.patch("/{draft_id}", response_model=DraftRead)
def draft_update(
    draft_id: UUID,
    payload: DraftPatch,
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> DraftRead:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="At least one draft property must be provided",
        )
    draft = get_draft(session, user, draft_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    return DraftRead.model_validate(update_draft(session, draft, changes))


@router.delete("/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
def draft_delete(
    draft_id: UUID, session: DatabaseSession, user: CsrfProtectedUser
) -> Response:
    draft = get_draft(session, user, draft_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    delete_draft(session, draft)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
