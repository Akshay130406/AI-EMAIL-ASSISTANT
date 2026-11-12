from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Email, User
from app.schemas.calendar import (
    CalendarEventRead,
    MeetingAssistantRead,
    MeetingAssistantRequest,
)
from app.services import ai
from app.services.calendar import (
    build_calendar_service,
    get_event,
    require_calendar_account,
)


def generate_meeting_assistance(
    session: Session,
    user: User,
    payload: MeetingAssistantRequest,
) -> MeetingAssistantRead:
    event: CalendarEventRead | None = None
    if payload.event_id:
        account = require_calendar_account(session, user)
        event = CalendarEventRead.model_validate(
            get_event(
                build_calendar_service(account, session),
                payload.calendar_id,
                payload.event_id,
            )
        )

    emails = (
        list(
            session.scalars(
                select(Email).where(
                    Email.user_id == user.id,
                    Email.source == "gmail",
                    Email.id.in_(payload.email_ids),
                )
            )
        )
        if payload.email_ids
        else []
    )
    email_by_id = {email.id: email for email in emails}
    if len(email_by_id) != len(set(payload.email_ids)):
        raise LookupError("Selected Gmail message was not found")

    messages = [
        {
            "id": str(email.id),
            "sender": email.sender,
            "recipients": email.recipients,
            "subject": email.subject,
            "received_at": email.received_at.isoformat() if email.received_at else None,
            "body": email.body or email.preview or "",
        }
        for email in emails
    ]
    response = ai._generate(
        user.id,
        "meeting-assistant",
        MeetingAssistantRead,
        {
            "operation": payload.operation,
            "question": payload.question,
            "calendar_event": event.model_dump(mode="json") if event else None,
            "messages": messages,
        },
        cache=True,
    )

    known_attendees = set(event.attendees if event else [])
    for email in emails:
        known_attendees.add(email.sender)
        known_attendees.update(email.recipients or [])
    known_attendees_normalized = {known.casefold() for known in known_attendees}
    return response.model_copy(
        update={
            "attendees": [
                attendee
                for attendee in response.attendees
                if attendee.casefold() in known_attendees_normalized
            ],
            "source_email_ids": [email.id for email in emails],
            "calendar_availability_confirmed": False,
        }
    )
