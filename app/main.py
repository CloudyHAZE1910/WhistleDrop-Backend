from fastapi import FastAPI
from fastapi.responses import FileResponse

from .bootstrap import bootstrap_moderator
from .database import Base, engine
from .routers import moderator, reports

# Creates the tables on first run. (For a bigger project you would use Alembic migrations.)
Base.metadata.create_all(bind=engine)
bootstrap_moderator()

app = FastAPI(
    title="WhistleDrop",
    description="Confidential reporting backend: submit anonymously, track with a case code, "
    "moderators review without ever seeing who reported.",
    version="1.0.0",
)

app.include_router(reports.router)
app.include_router(moderator.router)


@app.get("/health", tags=["Meta"])
def health():
    return {"status": "ok"}


@app.get("/dashboard", tags=["Meta"], include_in_schema=False)
def dashboard_page():
    """A small built-in moderator dashboard: login, filter reports, change status, add
    notes, view evidence. It is a plain HTML/JS page that calls the same public API."""
    return FileResponse("app/static/dashboard.html")
