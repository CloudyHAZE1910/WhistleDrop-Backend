import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def coarse_now() -> datetime:
    """Current time rounded down to the hour.

    Privacy: an exact timestamp could let someone match a report to
    "the person who was online at 14:03". Hour precision is enough for
    moderators and much harder to correlate.
    """
    return utcnow().replace(minute=0, second=0, microsecond=0)


class Category(str, enum.Enum):
    SECURITY = "SECURITY"
    HARASSMENT = "HARASSMENT"
    CORRUPTION = "CORRUPTION"
    TECHNICAL = "TECHNICAL"
    OTHER = "OTHER"


class Status(str, enum.Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


# The workflow: SUBMITTED -> UNDER_REVIEW -> RESOLVED or DISMISSED.
# RESOLVED and DISMISSED have no way out: that is what "permanently closed" means.
ALLOWED_TRANSITIONS: dict[Status, set[Status]] = {
    Status.SUBMITTED: {Status.UNDER_REVIEW},
    Status.UNDER_REVIEW: {Status.RESOLVED, Status.DISMISSED},
    Status.RESOLVED: set(),
    Status.DISMISSED: set(),
}
CLOSED_STATUSES = {Status.RESOLVED, Status.DISMISSED}


class Moderator(Base):
    __tablename__ = "moderators"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    # We store only a HASH of the case code. Even if the database leaks,
    # nobody can use it to look up reports.
    case_code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    category: Mapped[Category] = mapped_column(Enum(Category))
    description: Mapped[str] = mapped_column(Text)
    evidence_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    status: Mapped[Status] = mapped_column(Enum(Status), default=Status.SUBMITTED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=coarse_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=coarse_now, onupdate=coarse_now
    )

    updates: Mapped[list["StatusUpdate"]] = relationship(
        back_populates="report",
        order_by="StatusUpdate.id",
        cascade="all, delete-orphan",
    )
    evidence_files: Mapped[list["EvidenceFile"]] = relationship(
        back_populates="report",
        order_by="EvidenceFile.id",
        cascade="all, delete-orphan",
    )

    @property
    def is_closed(self) -> bool:
        """A closed case is permanent: no status changes, notes or new evidence."""
        return self.status in CLOSED_STATUSES

    @property
    def allowed_next_statuses(self) -> list[Status]:
        return [s for s in Status if s in ALLOWED_TRANSITIONS[self.status]]

    # NOTE: there is deliberately NO column for IP, name, email, device, etc.
    # You cannot leak what you never stored.


class StatusUpdate(Base):
    __tablename__ = "status_updates"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True)
    moderator_id: Mapped[int] = mapped_column(ForeignKey("moderators.id"))  # audit trail, never exposed
    new_status: Mapped[Status] = mapped_column(Enum(Status))  # the status at the time of the update
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    report: Mapped["Report"] = relationship(back_populates="updates")


class EvidenceFile(Base):
    """An image attached to a report. Stored in the database (not on disk) so deployments
    with temporary file systems do not lose it. The original file name is never stored."""

    __tablename__ = "evidence_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True)
    content_type: Mapped[str] = mapped_column(String(50))
    size_bytes: Mapped[int] = mapped_column(Integer)
    # deferred: the image bytes are only loaded when actually needed (not in list queries)
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=coarse_now)

    report: Mapped["Report"] = relationship(back_populates="evidence_files")
