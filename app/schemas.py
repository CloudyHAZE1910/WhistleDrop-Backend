from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from .models import Category, Status


# ---------- reporter side ----------
class ReportCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    category: Category
    description: str = Field(min_length=20, max_length=5000)
    evidence_url: HttpUrl | None = None


class ReportCreated(BaseModel):
    case_code: str
    status: Status
    message: str


class StatusUpdateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    new_status: Status
    message: str
    created_at: datetime


class EvidenceFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content_type: str
    size_bytes: int
    created_at: datetime


class EvidenceUploaded(BaseModel):
    message: str
    file: EvidenceFileOut


class PublicReportOut(BaseModel):
    category: Category
    status: Status
    submitted_at: datetime
    last_updated: datetime
    updates: list[StatusUpdateOut]
    evidence_file_count: int


# ---------- moderator side ----------
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ModeratorReportOut(BaseModel):
    """What moderators see. Notice: no reporter information exists here at all."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    category: Category
    description: str
    evidence_url: str | None
    status: Status
    created_at: datetime
    updated_at: datetime
    updates: list[StatusUpdateOut]
    evidence_files: list[EvidenceFileOut]
    allowed_next_statuses: list[Status]


class StatusChange(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    status: Status
    message: str = Field(min_length=1, max_length=500)


class NoteCreate(BaseModel):
    """Add a comment to a report WITHOUT changing its status."""

    model_config = ConfigDict(str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=500)


class DashboardCounts(BaseModel):
    total: int
    by_status: dict[str, int]
    by_category: dict[str, int]


class DashboardSummary(BaseModel):
    counts: DashboardCounts
    recent_reports: list[ModeratorReportOut]
