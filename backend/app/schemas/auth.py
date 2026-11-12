from uuid import UUID

from pydantic import BaseModel


class AuthenticatedUserRead(BaseModel):
    id: UUID
    email: str
    display_name: str | None
    picture_url: str | None


class AuthMeRead(BaseModel):
    user: AuthenticatedUserRead
    csrf_token: str
