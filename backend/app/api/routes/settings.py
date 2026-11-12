from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import CurrentUser, CsrfProtectedUser, DatabaseSession
from app.schemas.settings import SettingsPatch, SettingsRead
from app.services.settings import get_or_create_settings, update_settings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsRead)
def settings_read(session: DatabaseSession, user: CurrentUser) -> SettingsRead:
    settings = get_or_create_settings(session, user)
    return SettingsRead.model_validate(settings)


@router.patch("", response_model=SettingsRead)
def settings_update(
    payload: SettingsPatch, session: DatabaseSession, user: CsrfProtectedUser
) -> SettingsRead:
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="At least one settings property must be provided",
        )
    settings = get_or_create_settings(session, user)
    return SettingsRead.model_validate(update_settings(session, settings, changes))
