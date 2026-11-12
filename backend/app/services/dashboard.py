from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ConnectedAccount, Conversation, Draft, Email, User


def get_dashboard_overview(session: Session, user: User) -> dict[str, int]:
    def count(model, *filters) -> int:
        return int(
            session.scalar(
                select(func.count()).select_from(model).where(model.user_id == user.id, *filters)
            )
            or 0
        )

    gmail_connected = session.scalar(
        select(ConnectedAccount.id).where(
            ConnectedAccount.user_id == user.id,
            ConnectedAccount.provider == "gmail",
        )
    ) is not None
    email_source = "gmail" if gmail_connected else "sample"
    return {
        "total_emails": count(Email, Email.source == email_source),
        "unread_emails": count(Email, Email.source == email_source, Email.is_read.is_(False)),
        "starred_emails": count(Email, Email.source == email_source, Email.is_starred.is_(True)),
        "priority_emails": count(Email, Email.source == email_source, Email.is_priority.is_(True)),
        "drafts": count(Draft, Draft.status == "draft"),
        "conversations": count(Conversation),
    }
