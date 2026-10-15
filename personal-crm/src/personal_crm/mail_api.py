from fastapi import Depends
from pydantic import Field
from sqlalchemy import select

from .mail import MailError, MailSync, build_provider
from .models import MailAccount, Proposal, Source, SourceVersion
from .schema import Interpretation, Strict
from .service import CRMError


def evidence(version):
    meta = version.channel_metadata or {}
    if not meta.get("mail_sync"):
        return None
    return {"subject": meta.get("subject", ""), "sender": meta.get("sender", ""),
            "excerpt": meta.get("evidence", ""), "original_at": meta.get("evidence_at"),
            "direction": meta.get("direction"), "thread_id": meta.get("mail_thread_id"),
            "attachments_unanalysed": bool(meta.get("attachments_unanalysed")),
            "content_incomplete": bool(meta.get("content_incomplete"))}


def proposal_view(s, proposal):
    return {"id": proposal.id, "version": proposal.version, "status": proposal.status,
            "payload": proposal.payload, "evidence": evidence(s.get(SourceVersion, proposal.source_version_id))}


class ManualProposal(Strict):
    title: str = Field(min_length=1, max_length=2000)


def install_mail(app, settings, service, actor, provider=None):
    factory = service.factory

    def available():
        return provider is not None or (settings.mail.enabled and settings.mail.consent)

    def worker():
        if not available():
            raise MailError("mail_disabled")
        return MailSync(service, provider if provider is not None else build_provider(settings.mail), settings.mail.batch_size)

    @app.get("/workspace/mail")
    def status(owner=Depends(actor)):
        with factory() as s:
            account = s.get(MailAccount, owner)
            return {"available": available(), "status": account.status if account else "idle" if available() else "disabled",
                    "provider": account.provider if account else provider.name if provider else "imap" if available() else None,
                    "read_only": True, "window_days": 7, "poll_seconds": 300,
                    "last_success_at": account.last_success_at if account else None,
                    "next_sync_at": account.next_sync_at if account else None,
                    "error_code": account.error_code if account else None,
                    "failures": account.failures if account else 0,
                    "saved_count": account.saved_count if account else 0,
                    "reset_count": account.reset_count if account else 0}

    @app.post("/workspace/mail/sync")
    def sync(owner=Depends(actor)):
        return worker().run(owner, force=True)

    @app.post("/workspace/mail/disconnect")
    def disconnect(owner=Depends(actor)):
        # Disconnect works even if configuration/credentials have since been removed.
        return MailSync(service, provider).disconnect(owner)

    @app.post("/workspace/mail/reviews/{identity}/propose")
    def propose(identity: str, body: ManualProposal, owner=Depends(actor)):
        if not body.title.strip():
            raise CRMError("title_required", 422)
        with factory.begin() as s:
            service.owner(s, owner)
            version = s.scalar(select(SourceVersion).join(Source).where(SourceVersion.id == identity,
                Source.owner_id == owner, Source.channel == "mail").with_for_update(of=SourceVersion))
            if not version:
                raise CRMError("not_found", 404)
            newer = s.scalar(select(SourceVersion.id).where(SourceVersion.source_id == version.source_id,
                             SourceVersion.revision > version.revision))
            if newer or (version.result or {}).get("status") != "review" or not (version.channel_metadata or {}).get("mail_sync"):
                raise CRMError("proposal_conflict")
            output = Interpretation(source_version_id=identity, operation="create", title=body.title.strip())
            result = service._apply_interpretation(s, owner, s.get(Source, version.source_id), version, output)
            version.result = result
            return result

    @app.post("/workspace/mail/reviews/{identity}/dismiss")
    def dismiss(identity: str, owner=Depends(actor)):
        with factory.begin() as s:
            service.owner(s, owner)
            version = s.scalar(select(SourceVersion).join(Source).where(SourceVersion.id == identity,
                Source.owner_id == owner, Source.channel == "mail").with_for_update(of=SourceVersion))
            if not version:
                raise CRMError("not_found", 404)
            if (version.result or {}).get("status") != "review":
                raise CRMError("proposal_conflict")
            version.result = {"status": "ignored", "source_version_id": identity, "reviewed_by_owner": True}
            return {"status": "ignored"}
