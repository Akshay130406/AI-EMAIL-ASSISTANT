from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Email, User
from app.services.pagination import paginate


def list_emails(
    session: Session,
    user: User,
    *,
    source: str,
    page: int,
    page_size: int,
    search: str | None,
    unread: bool | None,
    sent: bool | None,
    starred: bool | None,
    priority: bool | None,
):
    statement = select(Email).where(Email.user_id == user.id, Email.source == source)
    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            or_(Email.sender.ilike(term), Email.subject.ilike(term), Email.preview.ilike(term))
        )
    if unread is not None:
        statement = statement.where(Email.is_read.is_(not unread))
    if sent is not None:
        statement = statement.where(Email.is_sent.is_(sent))
    if starred is not None:
        statement = statement.where(Email.is_starred.is_(starred))
    if priority is not None:
        statement = statement.where(Email.is_priority.is_(priority))
    statement = statement.order_by(Email.received_at.desc().nullslast(), Email.created_at.desc())
    return paginate(session, statement, page=page, page_size=page_size)


def get_email(session: Session, user: User, email_id):
    return session.scalar(
        select(Email).where(Email.id == email_id, Email.user_id == user.id)
    )


def update_email(session: Session, email: Email, changes: dict[str, bool]) -> Email:
    for key, value in changes.items():
        setattr(email, key, value)
    session.commit()
    session.refresh(email)
    return email
