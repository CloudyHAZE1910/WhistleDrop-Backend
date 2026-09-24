from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_moderator
from ..models import ALLOWED_TRANSITIONS, Category, EvidenceFile, Moderator, Report, Status, StatusUpdate
from ..schemas import (
    DashboardCounts,
    DashboardSummary,
    LoginRequest,
    ModeratorReportOut,
    NoteCreate,
    StatusChange,
    TokenOut,
)
from ..security import create_access_token, verify_password

router = APIRouter(prefix="/moderator", tags=["Moderators (login required)"])


@router.post("/login", response_model=TokenOut)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    moderator = db.scalar(select(Moderator).where(Moderator.username == payload.username))
    if moderator is None or not verify_password(payload.password, moderator.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return TokenOut(access_token=create_access_token(moderator.username))


@router.get("/reports", response_model=list[ModeratorReportOut])
def list_reports(
    category: Category | None = None,
    status: Status | None = None,
    q: str | None = Query(default=None, max_length=100, description="Search text in the description"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _moderator: Moderator = Depends(get_current_moderator),
):
    stmt = select(Report).order_by(Report.id.desc())
    if category is not None:
        stmt = stmt.where(Report.category == category)
    if status is not None:
        stmt = stmt.where(Report.status == status)
    if q:
        stmt = stmt.where(Report.description.ilike(f"%{q}%"))
    return db.scalars(stmt.limit(limit).offset(offset)).all()


@router.get("/dashboard", response_model=DashboardSummary)
def dashboard(db: Session = Depends(get_db), _moderator: Moderator = Depends(get_current_moderator)):
    """A one-screen overview: report counts by status and category, plus the newest reports."""
    total = db.scalar(select(func.count()).select_from(Report)) or 0

    by_status = {
        s.value: (db.scalar(select(func.count()).select_from(Report).where(Report.status == s)) or 0)
        for s in Status
    }
    by_category = {
        c.value: (db.scalar(select(func.count()).select_from(Report).where(Report.category == c)) or 0)
        for c in Category
    }
    recent = db.scalars(select(Report).order_by(Report.id.desc()).limit(10)).all()

    return DashboardSummary(
        counts=DashboardCounts(total=total, by_status=by_status, by_category=by_category),
        recent_reports=recent,
    )


@router.get("/reports/{report_id}", response_model=ModeratorReportOut)
def get_report(
    report_id: int,
    db: Session = Depends(get_db),
    _moderator: Moderator = Depends(get_current_moderator),
):
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.get("/reports/{report_id}/evidence/{file_id}")
def get_evidence_file(
    report_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    _moderator: Moderator = Depends(get_current_moderator),
):
    """Download one evidence image. Only moderators can view evidence."""
    evidence = db.get(EvidenceFile, file_id)
    if evidence is None or evidence.report_id != report_id:
        raise HTTPException(status_code=404, detail="Evidence file not found")
    return Response(content=evidence.data, media_type=evidence.content_type)


@router.patch("/reports/{report_id}/status", response_model=ModeratorReportOut)
def change_status(
    report_id: int,
    payload: StatusChange,
    db: Session = Depends(get_db),
    moderator: Moderator = Depends(get_current_moderator),
):
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    if report.is_closed:
        raise HTTPException(
            status_code=409,
            detail=f"This case is permanently closed ({report.status.value}) and cannot be reopened.",
        )
    if payload.status not in ALLOWED_TRANSITIONS[report.status]:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot change status from {report.status.value} to {payload.status.value}",
        )

    report.status = payload.status
    report.updates.append(
        StatusUpdate(
            new_status=payload.status,
            message=payload.message,
            moderator_id=moderator.id,
        )
    )
    db.commit()
    db.refresh(report)
    return report


@router.post("/reports/{report_id}/notes", response_model=ModeratorReportOut, status_code=201)
def add_note(
    report_id: int,
    payload: NoteCreate,
    db: Session = Depends(get_db),
    moderator: Moderator = Depends(get_current_moderator),
):
    """Add a short update the reporter can see, WITHOUT changing the report's status.
    For example: "Still investigating, thank you for your patience." Closed cases cannot
    receive new notes, since they are permanently closed."""
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.is_closed:
        raise HTTPException(
            status_code=409,
            detail=f"This case is permanently closed ({report.status.value}) and cannot receive new notes.",
        )

    report.updates.append(
        StatusUpdate(
            new_status=report.status,  # status is unchanged; this is a note, not a transition
            message=payload.message,
            moderator_id=moderator.id,
        )
    )
    db.commit()
    db.refresh(report)
    return report
