from datetime import date, datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import ConnectedAccount, Email, User


def get_analytics_overview(
    session: Session,
    user: User,
    *,
    period_days: int,
    today: date | None = None,
) -> dict[str, object]:
    current_day = today or datetime.now(timezone.utc).date()
    start_day = current_day - timedelta(days=period_days - 1)
    start_at = datetime.combine(start_day, datetime.min.time(), timezone.utc)
    source = (
        "gmail"
        if session.scalar(
            select(ConnectedAccount.id).where(
                ConnectedAccount.user_id == user.id,
                ConnectedAccount.provider == "gmail",
                ConnectedAccount.status == "connected",
            )
        )
        is not None
        else "sample"
    )
    day_column = func.date(Email.received_at).label("day")
    received_count = func.sum(case((Email.is_sent.is_(False), 1), else_=0))
    sent_count = func.sum(case((Email.is_sent.is_(True), 1), else_=0))
    rows = session.execute(
        select(
            day_column,
            received_count.label("received"),
            sent_count.label("sent"),
        )
        .where(
            Email.user_id == user.id,
            Email.source == source,
            Email.received_at >= start_at,
        )
        .group_by(day_column)
        .order_by(day_column)
    )
    daily_counts = {
        row.day.isoformat() if isinstance(row.day, date) else str(row.day): (
            int(row.received or 0),
            int(row.sent or 0),
        )
        for row in rows
    }
    daily = [
        {
            "day": start_day + timedelta(days=offset),
            "received": daily_counts.get(
                (start_day + timedelta(days=offset)).isoformat(), (0, 0)
            )[0],
            "sent": daily_counts.get(
                (start_day + timedelta(days=offset)).isoformat(), (0, 0)
            )[1],
        }
        for offset in range(period_days)
    ]
    base = (
        Email.user_id == user.id,
        Email.source == source,
        Email.received_at >= start_at,
    )

    def count(*filters) -> int:
        return int(
            session.scalar(
                select(func.count()).select_from(Email).where(*base, *filters)
            )
            or 0
        )

    return {
        "source": source,
        "period_days": period_days,
        "total_received": sum(item["received"] for item in daily),
        "total_sent": sum(item["sent"] for item in daily),
        "unread": count(Email.is_sent.is_(False), Email.is_read.is_(False)),
        "starred": count(Email.is_starred.is_(True)),
        "priority": count(Email.is_priority.is_(True)),
        "daily": daily,
        "generated_at": datetime.now(timezone.utc),
    }
