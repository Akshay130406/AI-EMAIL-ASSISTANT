from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Draft, User
from app.services.pagination import paginate


def list_drafts(session: Session, user: User, *, page: int, page_size: int):
    statement = (
        select(Draft)
        .where(Draft.user_id == user.id)
        .order_by(Draft.updated_at.desc(), Draft.created_at.desc())
    )
    return paginate(session, statement, page=page, page_size=page_size)


def get_draft(session: Session, user: User, draft_id):
    return session.scalar(select(Draft).where(Draft.id == draft_id, Draft.user_id == user.id))


def create_draft(session: Session, user: User, data: dict) -> Draft:
    draft = Draft(user_id=user.id, **data)
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return draft


def update_draft(session: Session, draft: Draft, changes: dict) -> Draft:
    for key, value in changes.items():
        setattr(draft, key, value)
    session.commit()
    session.refresh(draft)
    return draft


def delete_draft(session: Session, draft: Draft) -> None:
    session.delete(draft)
    session.commit()
