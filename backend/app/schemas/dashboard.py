from app.schemas.common import APIModel


class DashboardOverview(APIModel):
    total_emails: int
    unread_emails: int
    starred_emails: int
    priority_emails: int
    drafts: int
    conversations: int
