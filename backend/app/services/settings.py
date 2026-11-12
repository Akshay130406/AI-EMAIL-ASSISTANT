from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User, UserSettings


def get_or_create_settings(session: Session, user: User) -> UserSettings:
    settings = session.scalar(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )
    if settings is None:
        settings = UserSettings(user_id=user.id)
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings


def update_settings(
    session: Session,
    settings: UserSettings,
    changes: dict,
) -> UserSettings:
    for key, value in changes.items():
        if key in {"notification_preferences", "ai_preferences"}:
            current = getattr(settings, key).copy()
            current.update(value)
            setattr(settings, key, current)
        else:
            setattr(settings, key, value)
    session.commit()
    session.refresh(settings)
    return settings
