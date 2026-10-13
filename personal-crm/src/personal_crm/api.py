import hmac
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from .adapters import FixtureInterpreter
from .config import Settings
from .db import sessions
from .models import Profile, Proposal, Source, SourceVersion, Task
from .schema import Deadline, Incoming, Strict
from .service import CRMError, CRMService, snapshot


class Intake(Incoming):
    channel: Literal["owner", "forward"] = "owner"


class Command(Strict):
    version: int = Field(gt=0)
    action: Literal["close", "reminder", "deadline", "title"]
    at: str | None = None
    deadline: Deadline | None = None
    title: str | None = Field(default=None, min_length=1, max_length=2000)


class Confirmation(Strict):
    version: int = Field(gt=0)
    accept: bool = True


def create_app(settings=None, interpreter=None):
    settings = settings or Settings.from_env()
    factory = sessions(settings.database_url)
    interpreter = interpreter or FixtureInterpreter.from_file("fixtures/demo.json")
    service = CRMService(factory, interpreter)
    app = FastAPI(title="Personal CRM — fake adapters", version="0.1.0")
    app.state.service = service

    def actor(authorization: str | None = Header(default=None)):
        if not settings.owner_id or not settings.owner_token:
            raise HTTPException(503, "owner_not_configured")
        expected = f"Bearer {settings.owner_token}"
        if not authorization or not hmac.compare_digest(authorization.encode(), expected.encode()):
            raise HTTPException(401, "unauthorized")
        service.register(settings.owner_id, settings.timezone)
        return settings.owner_id

    @app.exception_handler(CRMError)
    async def crm_error(request: Request, error: CRMError):
        return JSONResponse({"detail": error.code}, status_code=error.status)

    @app.exception_handler(SQLAlchemyError)
    async def db_error(request: Request, error):
        return JSONResponse({"detail": "database_unavailable"}, status_code=503)

    @app.get("/health")
    def health():
        return {"status": "alive", "adapters": "fake"}

    @app.get("/ready")
    def ready():
        if not settings.owner_id or not settings.owner_token:
            raise HTTPException(503, "owner_not_configured")
        with factory() as s:
            s.execute(text("SELECT 1 FROM alembic_version"))
            s.execute(select(Profile).limit(1))
        return {"status": "ready", "adapters": "fake"}

    @app.post("/sources")
    def intake(body: Intake, owner=Depends(actor)):
        version_id = service.ingest(owner, body.channel, body)
        return service.process(owner, version_id)

    @app.post("/adapters/fake-mail")
    def fake_mail(body: Incoming, x_connector_token: str | None = Header(default=None)):
        if not settings.mail_token or not settings.owner_id or not settings.owner_token:
            raise HTTPException(503, "connector_not_configured")
        if not x_connector_token or not hmac.compare_digest(x_connector_token.encode(), settings.mail_token.encode()):
            raise HTTPException(401, "unauthorized")
        service.register(settings.owner_id, settings.timezone)
        version_id = service.ingest(settings.owner_id, "mail", body)
        return service.process(settings.owner_id, version_id)

    @app.post("/sources/{version_id}/retry")
    def retry(version_id: str, owner=Depends(actor)):
        return service.process(owner, version_id)

    @app.get("/sources")
    def sources(owner=Depends(actor)):
        with factory() as s:
            versions = s.scalars(select(SourceVersion).join(Source).where(Source.owner_id == owner)).all()
            return [{"id": v.id, "revision": v.revision, "status": v.status, "text": v.text,
                     "error_code": v.error_code} for v in versions]

    @app.get("/tasks")
    def tasks(owner=Depends(actor)):
        with factory() as s:
            return [snapshot(t) for t in s.scalars(select(Task).where(Task.owner_id == owner))]

    @app.get("/proposals")
    def proposals(owner=Depends(actor)):
        with factory() as s:
            return [{"id": p.id, "version": p.version, "status": p.status, "payload": p.payload}
                    for p in s.scalars(select(Proposal).where(Proposal.owner_id == owner))]

    @app.post("/tasks/{task_id}/commands")
    def command(task_id: str, body: Command, owner=Depends(actor)):
        from datetime import datetime
        try:
            at = datetime.fromisoformat(body.at.replace("Z", "+00:00")) if body.at else None
        except ValueError:
            raise HTTPException(422, "invalid_date")
        return service.command(owner, task_id, body.version, body.action,
                               at=at, deadline=body.deadline, title=body.title)

    @app.post("/proposals/{proposal_id}/confirm")
    def confirm(proposal_id: str, body: Confirmation, owner=Depends(actor)):
        return service.confirm(owner, proposal_id, body.version, body.accept)

    return app
