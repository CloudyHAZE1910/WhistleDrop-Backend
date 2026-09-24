import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Moderator
from app.security import hash_password

VALID_REPORT = {
    "category": "SECURITY",
    "description": "The server room door has been left unlocked every night this week.",
    "evidence_url": "https://example.com/photo-of-door",
}


def make_png_bytes(color="red", size=(20, 10)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def client():
    """A fresh in-memory database for every test, with one moderator ('mod')."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with TestingSession() as db:
        db.add(Moderator(username="mod", password_hash=hash_password("secret123")))
        db.commit()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def moderator_headers(client):
    res = client.post("/moderator/login", json={"username": "mod", "password": "secret123"})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def submit(client, **overrides):
    res = client.post("/reports", json={**VALID_REPORT, **overrides})
    assert res.status_code == 201
    return res.json()["case_code"]


def get_report_id(client, headers, index=0):
    reports = client.get("/moderator/reports", headers=headers).json()
    return reports[index]["id"]


# ---------- reporter ----------
def test_submit_returns_case_code_and_submitted_status(client):
    res = client.post("/reports", json=VALID_REPORT)
    assert res.status_code == 201
    body = res.json()
    assert body["case_code"].startswith("WD-")
    assert len(body["case_code"]) > 20
    assert body["status"] == "SUBMITTED"


def test_case_codes_are_unique(client):
    assert len({submit(client) for _ in range(20)}) == 20


def test_reporter_can_check_status_with_case_code(client):
    code = submit(client)
    res = client.get(f"/reports/{code}")
    assert res.status_code == 200
    assert res.json()["status"] == "SUBMITTED"
    assert res.json()["updates"] == []
    assert res.json()["evidence_file_count"] == 0


def test_unknown_case_code_is_404(client):
    assert client.get("/reports/WD-not-a-real-code").status_code == 404


def test_invalid_reports_are_rejected(client):
    assert client.post("/reports", json={**VALID_REPORT, "description": "too short"}).status_code == 422
    assert client.post("/reports", json={**VALID_REPORT, "category": "NOPE"}).status_code == 422
    assert client.post("/reports", json={**VALID_REPORT, "evidence_url": "not a url"}).status_code == 422
    assert client.post("/reports", json={"category": "SECURITY"}).status_code == 422


def test_evidence_url_is_optional(client):
    payload = {k: v for k, v in VALID_REPORT.items() if k != "evidence_url"}
    assert client.post("/reports", json=payload).status_code == 201


# ---------- evidence upload ----------
def test_reporter_can_upload_evidence_image(client):
    code = submit(client)
    files = {"file": ("photo.png", make_png_bytes(), "image/png")}
    res = client.post(f"/reports/{code}/evidence", files=files)
    assert res.status_code == 201
    assert res.json()["file"]["content_type"] == "image/png"
    assert client.get(f"/reports/{code}").json()["evidence_file_count"] == 1


def test_evidence_upload_rejects_non_image(client):
    code = submit(client)
    files = {"file": ("notes.txt", b"just some text", "text/plain")}
    res = client.post(f"/reports/{code}/evidence", files=files)
    assert res.status_code == 422


def test_evidence_upload_rejects_empty_file(client):
    code = submit(client)
    files = {"file": ("empty.png", b"", "image/png")}
    res = client.post(f"/reports/{code}/evidence", files=files)
    assert res.status_code == 422


def test_evidence_upload_unknown_case_code_is_404(client):
    files = {"file": ("photo.png", make_png_bytes(), "image/png")}
    assert client.post("/reports/WD-fake/evidence", files=files).status_code == 404


def test_evidence_upload_limit_enforced(client):
    code = submit(client)
    for _ in range(3):
        files = {"file": ("photo.png", make_png_bytes(), "image/png")}
        assert client.post(f"/reports/{code}/evidence", files=files).status_code == 201
    files = {"file": ("photo.png", make_png_bytes(), "image/png")}
    res = client.post(f"/reports/{code}/evidence", files=files)
    assert res.status_code == 409


def test_evidence_strips_metadata():
    """Unit-level check that the sanitizer used by the endpoint removes EXIF data."""
    from app.evidence import sanitize_image

    img = Image.new("RGB", (10, 10), "blue")
    exif = Image.Exif()
    exif[0x010F] = "SecretCameraMaker"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)

    clean_bytes, content_type = sanitize_image(buf.getvalue())
    assert content_type == "image/jpeg"
    assert b"SecretCameraMaker" not in clean_bytes


def test_moderator_can_view_evidence_file(client):
    code = submit(client)
    files = {"file": ("photo.png", make_png_bytes(), "image/png")}
    upload = client.post(f"/reports/{code}/evidence", files=files).json()
    headers = moderator_headers(client)
    report_id = get_report_id(client, headers)
    file_id = upload["file"]["id"]

    res = client.get(f"/moderator/reports/{report_id}/evidence/{file_id}", headers=headers)
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"


def test_evidence_file_requires_moderator_login(client):
    code = submit(client)
    files = {"file": ("photo.png", make_png_bytes(), "image/png")}
    upload = client.post(f"/reports/{code}/evidence", files=files).json()
    headers = moderator_headers(client)
    report_id = get_report_id(client, headers)
    file_id = upload["file"]["id"]

    assert client.get(f"/moderator/reports/{report_id}/evidence/{file_id}").status_code == 401


def test_closed_case_rejects_new_evidence(client):
    code = submit(client)
    headers = moderator_headers(client)
    report_id = get_report_id(client, headers)
    client.patch(f"/moderator/reports/{report_id}/status", json={"status": "UNDER_REVIEW", "message": "ok"}, headers=headers)
    client.patch(f"/moderator/reports/{report_id}/status", json={"status": "DISMISSED", "message": "closing"}, headers=headers)

    files = {"file": ("photo.png", make_png_bytes(), "image/png")}
    res = client.post(f"/reports/{code}/evidence", files=files)
    assert res.status_code == 409


# ---------- moderator access ----------
def test_moderator_routes_require_login(client):
    assert client.get("/moderator/reports").status_code == 401
    assert client.get("/moderator/dashboard").status_code == 401
    assert client.patch("/moderator/reports/1/status", json={"status": "UNDER_REVIEW", "message": "x"}).status_code == 401
    assert client.post("/moderator/reports/1/notes", json={"message": "x"}).status_code == 401


def test_login_with_wrong_password_fails(client):
    res = client.post("/moderator/login", json={"username": "mod", "password": "wrong"})
    assert res.status_code == 401


def test_moderator_can_list_and_filter(client):
    submit(client, category="SECURITY")
    submit(client, category="HARASSMENT")
    headers = moderator_headers(client)

    assert len(client.get("/moderator/reports", headers=headers).json()) == 2
    only_harassment = client.get("/moderator/reports?category=HARASSMENT", headers=headers).json()
    assert len(only_harassment) == 1
    assert only_harassment[0]["category"] == "HARASSMENT"
    assert client.get("/moderator/reports?status=RESOLVED", headers=headers).json() == []


def test_moderator_view_contains_no_reporter_identity(client):
    submit(client)
    headers = moderator_headers(client)
    report = client.get("/moderator/reports", headers=headers).json()[0]
    forbidden = {"ip", "ip_address", "user_agent", "email", "name", "reporter", "case_code", "case_code_hash"}
    assert forbidden.isdisjoint(report.keys())


# ---------- dashboard ----------
def test_dashboard_counts(client):
    submit(client, category="SECURITY")
    submit(client, category="HARASSMENT")
    headers = moderator_headers(client)
    report_id = get_report_id(client, headers)
    client.patch(f"/moderator/reports/{report_id}/status", json={"status": "UNDER_REVIEW", "message": "ok"}, headers=headers)

    summary = client.get("/moderator/dashboard", headers=headers).json()
    assert summary["counts"]["total"] == 2
    assert summary["counts"]["by_status"]["UNDER_REVIEW"] == 1
    assert summary["counts"]["by_status"]["SUBMITTED"] == 1
    assert summary["counts"]["by_category"]["SECURITY"] == 1
    assert len(summary["recent_reports"]) == 2


def test_dashboard_page_serves_html(client):
    res = client.get("/dashboard")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "WhistleDrop" in res.text


# ---------- workflow ----------
def test_full_workflow_and_reporter_sees_updates(client):
    code = submit(client)
    headers = moderator_headers(client)
    report_id = get_report_id(client, headers)

    res = client.patch(
        f"/moderator/reports/{report_id}/status",
        json={"status": "UNDER_REVIEW", "message": "We are looking into this."},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["status"] == "UNDER_REVIEW"
    assert res.json()["allowed_next_statuses"] == ["RESOLVED", "DISMISSED"]

    res = client.patch(
        f"/moderator/reports/{report_id}/status",
        json={"status": "RESOLVED", "message": "Door lock replaced."},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["allowed_next_statuses"] == []

    public = client.get(f"/reports/{code}").json()
    assert public["status"] == "RESOLVED"
    assert [u["message"] for u in public["updates"]] == ["We are looking into this.", "Door lock replaced."]


def test_invalid_status_transitions_are_409(client):
    submit(client)
    headers = moderator_headers(client)
    report_id = get_report_id(client, headers)

    # cannot skip UNDER_REVIEW
    res = client.patch(
        f"/moderator/reports/{report_id}/status",
        json={"status": "RESOLVED", "message": "skipping ahead"},
        headers=headers,
    )
    assert res.status_code == 409


def test_status_change_requires_message_and_existing_report(client):
    headers = moderator_headers(client)
    assert client.patch("/moderator/reports/999/status", json={"status": "UNDER_REVIEW", "message": "x"}, headers=headers).status_code == 404
    submit(client)
    report_id = get_report_id(client, headers)
    assert client.patch(f"/moderator/reports/{report_id}/status", json={"status": "UNDER_REVIEW"}, headers=headers).status_code == 422


# ---------- permanent closing ----------
def test_closed_case_cannot_be_reopened(client):
    submit(client)
    headers = moderator_headers(client)
    report_id = get_report_id(client, headers)
    client.patch(f"/moderator/reports/{report_id}/status", json={"status": "UNDER_REVIEW", "message": "ok"}, headers=headers)
    client.patch(f"/moderator/reports/{report_id}/status", json={"status": "DISMISSED", "message": "not valid"}, headers=headers)

    res = client.patch(
        f"/moderator/reports/{report_id}/status",
        json={"status": "UNDER_REVIEW", "message": "reopen"},
        headers=headers,
    )
    assert res.status_code == 409
    assert "permanently closed" in res.json()["detail"]


def test_closed_case_rejects_new_notes(client):
    submit(client)
    headers = moderator_headers(client)
    report_id = get_report_id(client, headers)
    client.patch(f"/moderator/reports/{report_id}/status", json={"status": "UNDER_REVIEW", "message": "ok"}, headers=headers)
    client.patch(f"/moderator/reports/{report_id}/status", json={"status": "RESOLVED", "message": "done"}, headers=headers)

    res = client.post(f"/moderator/reports/{report_id}/notes", json={"message": "one more thing"}, headers=headers)
    assert res.status_code == 409


# ---------- status notes (no status change) ----------
def test_moderator_can_add_note_without_changing_status(client):
    code = submit(client)
    headers = moderator_headers(client)
    report_id = get_report_id(client, headers)

    res = client.post(
        f"/moderator/reports/{report_id}/notes",
        json={"message": "Still investigating, thank you for your patience."},
        headers=headers,
    )
    assert res.status_code == 201
    assert res.json()["status"] == "SUBMITTED"  # unchanged
    assert len(res.json()["updates"]) == 1

    public = client.get(f"/reports/{code}").json()
    assert public["status"] == "SUBMITTED"
    assert public["updates"][0]["message"] == "Still investigating, thank you for your patience."
    assert public["updates"][0]["new_status"] == "SUBMITTED"


def test_note_requires_message_and_existing_report(client):
    headers = moderator_headers(client)
    assert client.post("/moderator/reports/999/notes", json={"message": "x"}, headers=headers).status_code == 404
    submit(client)
    report_id = get_report_id(client, headers)
    assert client.post(f"/moderator/reports/{report_id}/notes", json={"message": ""}, headers=headers).status_code == 422
