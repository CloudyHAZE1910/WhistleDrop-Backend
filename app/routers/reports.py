from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..evidence import MAX_FILES_PER_REPORT, MAX_UPLOAD_BYTES, InvalidEvidence, sanitize_image
from ..models import EvidenceFile, Report, Status
from ..schemas import (
    EvidenceUploaded,
    PublicReportOut,
    ReportCreate,
    ReportCreated,
    StatusUpdateOut,
)
from ..security import generate_case_code, hash_case_code

router = APIRouter(prefix="/reports", tags=["Reporters (public, no login)"])


def _get_report_or_404(db: Session, case_code: str) -> Report:
    report = db.scalar(select(Report).where(Report.case_code_hash == hash_case_code(case_code)))
    if report is None:
        # Same answer for "wrong code" and "code never existed": reveals nothing.
        raise HTTPException(status_code=404, detail="Case not found")
    return report


@router.post("", response_model=ReportCreated, status_code=201)
def submit_report(payload: ReportCreate, db: Session = Depends(get_db)):
    """Submit a report anonymously. Returns a case code - save it, it is shown only once."""
    case_code = generate_case_code()
    report = Report(
        case_code_hash=hash_case_code(case_code),
        category=payload.category,
        description=payload.description,
        evidence_url=str(payload.evidence_url) if payload.evidence_url else None,
    )
    db.add(report)
    db.commit()
    return ReportCreated(
        case_code=case_code,
        status=Status.SUBMITTED,
        message="Save this case code. It is the only way to check your report and it cannot be recovered.",
    )


@router.get("/{case_code}", response_model=PublicReportOut)
def check_report_status(case_code: str, db: Session = Depends(get_db)):
    """Check the status and moderator updates of a report using only its case code."""
    report = _get_report_or_404(db, case_code)
    return PublicReportOut(
        category=report.category,
        status=report.status,
        submitted_at=report.created_at,
        last_updated=report.updated_at,
        updates=[StatusUpdateOut.model_validate(u) for u in report.updates],
        evidence_file_count=len(report.evidence_files),
    )


@router.post("/{case_code}/evidence", response_model=EvidenceUploaded, status_code=201)
async def upload_evidence(case_code: str, file: UploadFile, db: Session = Depends(get_db)):
    """Attach a PNG or JPEG image to a report. Metadata (GPS, camera, timestamps) is stripped
    before it is stored, since that metadata could identify the reporter. Closed cases (RESOLVED
    or DISMISSED) no longer accept new evidence."""
    report = _get_report_or_404(db, case_code)

    if report.is_closed:
        raise HTTPException(status_code=409, detail="This case is closed and no longer accepts evidence.")
    if len(report.evidence_files) >= MAX_FILES_PER_REPORT:
        raise HTTPException(status_code=409, detail=f"Maximum {MAX_FILES_PER_REPORT} evidence files per report.")

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large. Maximum {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    if not raw:
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")

    try:
        clean_bytes, content_type = sanitize_image(raw)
    except InvalidEvidence as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    evidence = EvidenceFile(
        report_id=report.id,
        content_type=content_type,
        size_bytes=len(clean_bytes),
        data=clean_bytes,
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return EvidenceUploaded(message="Evidence uploaded. Its metadata was removed for your privacy.", file=evidence)
