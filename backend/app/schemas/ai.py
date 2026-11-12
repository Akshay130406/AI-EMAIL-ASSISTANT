from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.common import APIModel

Tone = Literal[
    "Professional",
    "Friendly",
    "Formal",
    "Concise",
    "Persuasive",
    "Appreciative",
]


class DeadlineEvidence(APIModel):
    date_text: str = Field(min_length=1, max_length=120)
    evidence: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def date_is_in_evidence(self) -> "DeadlineEvidence":
        if self.date_text.casefold() not in self.evidence.casefold():
            raise ValueError("The cited evidence must contain the date text")
        return self


class EmailClassification(APIModel):
    category: Literal[
        "Important", "Work", "Personal", "Promotions", "Social", "Finance", "Updates", "Other"
    ]
    priority: Literal["High", "Medium", "Low"]
    urgency: Literal["High", "Medium", "Low", "Unclear"]
    response_required: bool | None
    deadlines: list[DeadlineEvidence] = Field(max_length=8)
    confidence: float = Field(ge=0, le=1)
    explanation: str = Field(min_length=1, max_length=500)


class ActionEvidence(APIModel):
    text: str = Field(min_length=1, max_length=500)
    evidence: str = Field(min_length=1, max_length=500)


class EmailSummary(APIModel):
    summary: str = Field(min_length=1, max_length=2000)
    important_points: list[ActionEvidence] = Field(max_length=8)
    action_items: list[ActionEvidence] = Field(max_length=8)
    deadlines: list[DeadlineEvidence] = Field(max_length=8)
    people_or_organizations: list[ActionEvidence] = Field(max_length=12)
    questions_requiring_response: list[ActionEvidence] = Field(max_length=8)


class WriteRequest(APIModel):
    action: Literal["generate", "subject_lines"] = "generate"
    instructions: str = Field(min_length=1, max_length=4000)
    recipient: str | None = Field(default=None, max_length=320)
    subject: str | None = Field(default=None, max_length=998)
    body: str | None = Field(default=None, max_length=12000)
    tone: Tone = "Professional"


class WriteResponse(APIModel):
    subject: str = Field(default="", max_length=998)
    body: str = Field(default="", max_length=12000)
    subject_suggestions: list[str] = Field(default_factory=list, max_length=5)


class RewriteRequest(APIModel):
    action: Literal["rewrite", "improve", "shorten", "expand"]
    content: str = Field(min_length=1, max_length=12000)
    tone: Tone = "Professional"
    instructions: str | None = Field(default=None, max_length=2000)


class RewriteResponse(APIModel):
    content: str = Field(min_length=1, max_length=12000)


class ReplySuggestion(APIModel):
    subject: str = Field(default="", max_length=998)
    body: str = Field(min_length=1, max_length=12000)


class CopilotRequest(APIModel):
    question: str = Field(min_length=1, max_length=2000)
    email_id: UUID | None = None
    thread_id: str | None = Field(default=None, min_length=1, max_length=255)


class CopilotSource(APIModel):
    email_id: UUID
    subject: str
    sender: str


class CopilotResponse(APIModel):
    answer: str = Field(min_length=1, max_length=6000)
    source_indexes: list[int] = Field(max_length=10)


class CopilotResult(APIModel):
    answer: str
    sources: list[CopilotSource]


class InsightComputation(APIModel):
    unread_emails: int = Field(ge=0)
    important_unread_emails: int = Field(ge=0)
    starred_emails: int = Field(ge=0)


class AIInsightItem(APIModel):
    text: str = Field(min_length=1, max_length=500)
    source_index: int = Field(ge=0, le=9)
    evidence: str = Field(min_length=1, max_length=500)


class AIInsightsNarrative(APIModel):
    waiting_for_reply: int | None = Field(default=None, ge=0)
    briefing: str | None = Field(default=None, max_length=2000)
    priorities: list[AIInsightItem] = Field(default_factory=list, max_length=5)
    urgent: list[AIInsightItem] = Field(default_factory=list, max_length=5)
    deadlines: list[AIInsightItem] = Field(default_factory=list, max_length=5)


class AIInsightsResponse(APIModel):
    computed: InsightComputation
    ai_generated: AIInsightsNarrative
    sources: list[CopilotSource] = Field(default_factory=list, max_length=10)
    generated_at: str | None = None
