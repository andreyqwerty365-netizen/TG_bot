import hmac
import logging
from datetime import date
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import Field
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from .adapters import FixtureInterpreter
from .config import Settings
from .db import sessions
from .models import Guidance, History, Job, Profile, Proposal, Source, SourceVersion, Task
from .schema import Deadline, Incoming, Strict
from .service import CRMError, CRMService, snapshot
from .openai_adapter import ContextInterpreter, ResponsesAdapter
from .telegram import TelegramIngress


class Intake(Incoming):
    channel: Literal["owner", "forward"] = "owner"


class Command(Strict):
    version: int = Field(gt=0)
    action: Literal["close", "reminder", "deadline", "title", "plan", "defer", "resume", "cancel", "focus", "start", "activate"]
    at: str | None = None
    deadline: Deadline | None = None
    title: str | None = Field(default=None, min_length=1, max_length=2000)
    planned_on: date | None = None
    return_on: date | None = None
    focused: bool | None = None


class Confirmation(Strict):
    version: int = Field(gt=0)
    accept: bool = True


class AccessPrivacyFilter(logging.Filter):
    def filter(self, record):
        # Uvicorn's access tuple contains the raw URL, including typed task searches.
        if isinstance(record.args, tuple) and len(record.args) == 5 and isinstance(record.args[2], str):
            values = list(record.args)
            values[2] = values[2].split("?", 1)[0]
            record.args = tuple(values)
        return True


def create_app(settings=None, interpreter=None, mail_provider=None):
    settings = settings or Settings.from_env()
    if settings.environment == 'production':
        if not settings.owner_id or not settings.web_auth.valid(settings.environment):
            raise ValueError('production_web_auth_required')
        if mail_provider is not None and not (settings.mail.enabled and settings.mail.consent):
            raise ValueError('production_synthetic_provider_forbidden')
    factory = sessions(settings.database_url)
    interpreter = interpreter or ContextInterpreter(ResponsesAdapter(factory, settings.ai),
        FixtureInterpreter() if settings.environment == 'production' else FixtureInterpreter.from_file('fixtures/demo.json'))
    service = CRMService(factory, interpreter)
    app = FastAPI(title="Personal CRM",version="0.3.0",docs_url=None if settings.environment=='production' else '/docs',
                  redoc_url=None if settings.environment=='production' else '/redoc',
                  openapi_url=None if settings.environment=='production' else '/openapi.json')
    app.state.service = service

    @app.exception_handler(RequestValidationError)
    async def safe_validation(request: Request,error: RequestValidationError):
        return JSONResponse({'detail':[{'loc':e['loc'],'type':e['type'],'msg':e['msg']} for e in error.errors()]},status_code=422)
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, AccessPrivacyFilter) for item in access_logger.filters):
        access_logger.addFilter(AccessPrivacyFilter())

    @app.middleware("http")
    async def browser_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path not in ("/docs", "/redoc", "/openapi.json"):
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        if request.headers.get("authorization") or request.headers.get('cookie') or request.url.path.startswith('/auth/'):
            response.headers["Cache-Control"] = "no-store"
        return response

    from .web_auth import install_auth
    actor = install_auth(app,service,settings)

    @app.exception_handler(CRMError)
    async def crm_error(request: Request, error: CRMError):
        return JSONResponse({"detail": error.code}, status_code=error.status)

    from .mail import MailError

    @app.exception_handler(MailError)
    async def mail_error(request: Request, error: MailError):
        return JSONResponse({"detail": error.code}, status_code=409)

    @app.exception_handler(SQLAlchemyError)
    async def db_error(request: Request, error):
        return JSONResponse({"detail": "database_unavailable"}, status_code=503)

    @app.get("/health")
    def health():
        return {"status": "alive", "mail_enabled": settings.mail.enabled and settings.mail.consent}

    from .mail_api import install_mail
    install_mail(app, settings, service, actor, mail_provider)

    @app.get("/ready")
    def ready():
        if not settings.owner_id or not (settings.owner_token or settings.web_auth.password_hash):
            raise HTTPException(503, "owner_not_configured")
        with factory() as s:
            from .recovery import SCHEMA
            if s.scalar(text('SELECT version_num FROM alembic_version'))!=SCHEMA:
                raise HTTPException(503,'schema_not_ready')
            s.execute(select(Profile).limit(1))
            profile=s.get(Profile,settings.owner_id)
            if profile and profile.recovery_hold:
                raise HTTPException(503,'recovery_hold')
        if settings.environment=='production':
            from .operations import overview
            from .recovery import BackupConfig
            view=overview(factory,settings.owner_id,now=service.clock(),delivery_enabled=settings.telegram.send_enabled,
                          backup_enabled=BackupConfig.from_env().enabled)
            required=['source']+(['delivery'] if settings.telegram.send_enabled else [])+(['backup'] if BackupConfig.from_env().enabled else [])
            if any(view['workers'][role]['status'] not in ('running','idle') for role in required):
                raise HTTPException(503,'workers_not_ready')
            if view['workers']['source']['status']=='disabled' or view['backup']['status'] in ('missing','overdue'):
                raise HTTPException(503,'workers_not_ready')
        return {'status':'ready'}

    @app.post("/sources")
    def intake(body: Intake, owner=Depends(actor)):
        version_id = service.ingest(owner, body.channel, body)
        return service.process(owner, version_id)

    @app.post("/adapters/synthetic-telegram")
    def synthetic_telegram(payload: dict, owner=Depends(actor)):
        return TelegramIngress(service, settings.telegram, owner).accept(payload)

    @app.post("/telegram/webhook")
    def telegram_webhook(payload: dict, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
        ingress = TelegramIngress(service, settings.telegram, settings.owner_id)
        ingress.authenticate_webhook(x_telegram_bot_api_secret_token)
        if not settings.owner_id or not settings.owner_token:
            raise HTTPException(503, "owner_not_configured")
        service.register(settings.owner_id, settings.timezone, initialize_only=True)
        return ingress.accept(payload)

    @app.get("/ai/status")
    def ai_status(owner=Depends(actor)):
        from .budget import BudgetLedger
        return {"enabled": settings.ai.enabled, "model": settings.ai.model,
                "budget": BudgetLedger(factory, service.clock).status(owner)}

    @app.post("/adapters/fake-mail")
    def fake_mail(body: Incoming, x_connector_token: str | None = Header(default=None)):
        if not settings.mail_token or not settings.owner_id or not settings.owner_token:
            raise HTTPException(503, "connector_not_configured")
        if not x_connector_token or not hmac.compare_digest(x_connector_token.encode(), settings.mail_token.encode()):
            raise HTTPException(401, "unauthorized")
        service.register(settings.owner_id, settings.timezone, initialize_only=True)
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

    @app.get("/overview")
    def owner_overview(owner=Depends(actor)):
        return service.overview(owner)

    @app.get("/tasks/{task_id}/history")
    def history(task_id: str, owner=Depends(actor)):
        with factory.begin() as s:
            service.owner(s, owner)
            service.task(s, owner, task_id)
            return [{"id": h.id, "task_version": h.task_version, "actor": h.actor,
                     "reason": h.reason, "before": h.before, "after": h.after}
                    for h in s.scalars(select(History).where(History.task_id == task_id, History.owner_id == owner)
                                      .order_by(History.created_at, History.task_version))]

    @app.get("/deliveries")
    def deliveries(owner=Depends(actor)):
        with factory() as s:
            return [{"id": j.id, "kind": j.kind, "status": j.status, "run_at": j.run_at,
                     "cancel_reason": j.cancel_reason, "attempts": j.attempts}
                    for j in s.scalars(select(Job).where(Job.owner_id == owner).order_by(Job.run_at))]

    @app.get("/guidance")
    def guidance(owner=Depends(actor)):
        with factory() as s:
            return [{"id": g.id, "task_id": g.task_id, "task_version": g.task_version,
                     "kind": g.kind, "status": g.status, "payload": g.payload,
                     "created_at": g.created_at, "delivered_at": g.delivered_at}
                    for g in s.scalars(select(Guidance).where(Guidance.owner_id == owner).order_by(Guidance.created_at))]

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
                               at=at, deadline=body.deadline, title=body.title, planned_on=body.planned_on,
                               return_on=body.return_on, focused=body.focused)

    @app.post("/proposals/{proposal_id}/confirm")
    def confirm(proposal_id: str, body: Confirmation, owner=Depends(actor)):
        return service.confirm(owner, proposal_id, body.version, body.accept)

    from .workspace_api import install_workspace
    install_workspace(app, service, settings, actor)
    from .planning_api import install_planning
    install_planning(app, service, actor)
    from .suggestions import install_suggestions
    install_suggestions(app, service, actor, settings.planning)
    return app
