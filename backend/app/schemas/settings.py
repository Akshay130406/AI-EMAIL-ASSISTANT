from datetime import datetime
from typing import Literal
from uuid import UUID

from app.schemas.common import APIModel


class NotificationPreferences(APIModel):
    inbox_reminders: bool = True
    writing_suggestions: bool = True
    product_updates: bool = False


class AIPreferences(APIModel):
    default_tone: Literal["professional", "friendly", "formal", "concise"] = "professional"
    always_review_drafts: bool = True


class SettingsPatch(APIModel):
    theme: Literal["light", "dark", "system"] | None = None
    notification_preferences: NotificationPreferences | None = None
    ai_preferences: AIPreferences | None = None


class SettingsRead(APIModel):
    id: UUID
    user_id: UUID
    theme: Literal["light", "dark", "system"]
    notification_preferences: NotificationPreferences
    ai_preferences: AIPreferences
    created_at: datetime
    updated_at: datetime
