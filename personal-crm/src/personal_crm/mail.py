"""Read-only mailbox boundary and durable, replayable PostgreSQL ingestion."""
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
import hashlib
from html.parser import HTMLParser
import json
import os
import re
from typing import Protocol

from sqlalchemy import select

from .models import Dialogue, MailAccount, MailMessage, Proposal, SourceVersion, Task, uid
from .schema import Incoming


class MailError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class MailConfig:
    enabled: bool = False
    consent: bool = False
    host: str = ""
    username: str = field(default="", repr=False)
    password: str = field(default="", repr=False)
    sent_folder: str = ""
    port: int = 993
    batch_size: int = 25
    max_bytes: int = 262144
    timeout: int = 10

    @classmethod
    def from_env(cls):
        return cls(enabled=os.getenv("CRM_MAIL_ENABLED", "false").lower() == "true",
                   consent=os.getenv("CRM_MAIL_READ_CONSENT", "false").lower() == "true",
                   host=os.getenv("CRM_MAIL_IMAP_HOST", ""), username=os.getenv("CRM_MAIL_USERNAME", ""),
                   password=os.getenv("CRM_MAIL_PASSWORD", ""), sent_folder=os.getenv("CRM_MAIL_SENT_FOLDER", ""),
                   port=int(os.getenv("CRM_MAIL_IMAP_PORT", "993")))


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_provider(config):
    # Check both permissions before constructing even an injectable network client.
    if not config.enabled or not config.consent:
        raise MailError("mail_disabled")
    if (not config.host or not config.username or not config.password or not config.sent_folder
            or not 1 <= config.port <= 65535 or not 1 <= config.batch_size <= 100
            or not 1 <= config.timeout <= 15):
        raise MailError("mail_configuration_invalid")
    from .mail_imap import IMAPProvider
    return IMAPProvider(config)


@dataclass
class MailItem:
    key: str
    message_id: str
    references: tuple[str, ...]
    folder: str
    original_at: datetime
    arrived_at: datetime
    subject: str
    sender: str
    text: str | None
    attachments: bool = False
    unsupported: bool = False
    flags: tuple[str, ...] = ()
    removed: bool = False
    pointer: dict | None = None


@dataclass
class MailPage:
    items: list[MailItem]
    cursor: dict
    has_more: bool = False
    reset: bool = False
    checked: tuple[str, ...] = ()


class MailProvider(Protocol):
    name: str
    account_key: str

    def changes(self, cursor: dict | None, since: datetime, limit: int, tracked: list[dict]) -> MailPage: ...


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.hidden += 1
        elif tag in ("p", "div", "br", "li", "tr") and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.hidden = max(0, self.hidden - 1)
        elif tag in ("p", "div", "li") and not self.hidden:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def parse_message(raw, folder, remote_key, arrived_at, max_bytes=262144):
    if len(raw) > max_bytes:
        raise MailError("mail_message_too_large")
    message = BytesParser(policy=policy.default).parsebytes(raw)
    try:
        original = parsedate_to_datetime(str(message.get("Date", "")))
        if original.tzinfo is None:
            original = arrived_at
    except (ValueError, TypeError, OverflowError):
        original = arrived_at
    ids = re.findall(r"<[^<>\s]{1,998}>", str(message.get("Message-ID", "")))
    identity = ids[0] if len(ids) == 1 else ""
    references = tuple(re.findall(r"<[^<>\s]{1,998}>", str(message.get("References", "")) + " " + str(message.get("In-Reply-To", ""))))[-50:]
    parts, html = [], []
    attachments = unsupported = False
    for part in message.walk():
        if part.is_multipart():
            continue
        if part.get_content_disposition() == "attachment" or part.get_filename():
            attachments = True
            continue
        if part.get_content_type() not in ("text/plain", "text/html"):
            unsupported = True
            continue
        try:
            value = part.get_content()
            if part.get_content_type() == "text/plain":
                parts.append(value)
            else:
                parser = PlainHTML(); parser.feed(value); html.append("".join(parser.parts))
        except (UnicodeError, LookupError, ValueError):
            unsupported = True
    body = "\n".join(parts or html)
    body = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", body).strip()
    if len(body) > 30000:
        body, unsupported = body[:30000], True
    return MailItem(key=identity or "mime:" + hashlib.sha256(raw).hexdigest(), message_id=identity, references=references, folder=folder,
                    original_at=original.astimezone(UTC), arrived_at=arrived_at.astimezone(UTC),
                    subject=str(message.get("Subject", ""))[:500], sender=str(message.get("From", ""))[:500],
                    text=body, attachments=attachments, unsupported=unsupported)


class MailSync:
    def __init__(self, service, provider: MailProvider, batch_size=25):
        self.service, self.factory, self.clock = service, service.factory, service.clock
        self.provider = provider
        self.batch_size = max(1, min(batch_size, 100))

    def run(self, owner, force=False):
        now, token = self.clock(), uid()
        with self.factory.begin() as s:
            self.service.owner(s, owner)
            account = s.get(MailAccount, owner)
            if not account:
                account = MailAccount(owner_id=owner, provider=self.provider.name, account_key=self.provider.account_key)
                s.add(account); s.flush()
            if account.account_key != self.provider.account_key or account.provider != self.provider.name:
                raise MailError("mail_account_mismatch")
            if not account.enabled:
                return {"status": "disabled", "saved": 0}
            if account.lease_until and account.lease_until > now:
                return {"status": "busy", "saved": 0}
            if not force and account.status in ("auth_error", "error"):
                return {"status": account.status, "saved": 0}
            if not force and account.next_sync_at and account.next_sync_at > now:
                return {"status": "not_due", "saved": 0}
            account.status, account.lease_token, account.lease_until = "syncing", token, now + timedelta(minutes=5)
            cursor = account.cursor
            tracked = [{"key": m.key, "pointer": m.pointer, "message_id": m.message_id} for m in s.scalars(select(MailMessage).where(
                MailMessage.owner_id == owner, MailMessage.removed.is_(False)).order_by(MailMessage.last_checked_at, MailMessage.id).limit(self.batch_size))]
        try:
            page = self.provider.changes(cursor, now - timedelta(days=7), self.batch_size, tracked)
            if len(page.items) > self.batch_size * 2 or len(json.dumps(page.cursor)) > 32000:
                raise MailError("mail_protocol_error")
            saved = 0
            with self.factory.begin() as s:
                self.service.owner(s, owner)
                account = s.get(MailAccount, owner)
                if account.lease_token != token or not account.enabled:
                    return {"status": "superseded", "saved": 0}
                for item in page.items:
                    saved += self._save(s, owner, account, item, now)
                for key in page.checked:
                    row = s.scalar(select(MailMessage).where(MailMessage.owner_id == owner, MailMessage.key == key))
                    if row:
                        row.last_checked_at = now
                # Sources, identity/revision and checkpoint commit together, before interpretation.
                account.cursor, account.status = page.cursor, "idle"
                account.last_success_at, account.next_sync_at = now, now + timedelta(seconds=5 if page.has_more else 300)
                account.error_code, account.failures = None, 0
                account.saved_count += saved
                account.reset_count += int(page.reset)
                account.lease_token = account.lease_until = None
            self.prune(owner)
            return {"status": "idle", "saved": saved, "has_more": page.has_more}
        except Exception as error:
            code = error.code if isinstance(error, MailError) and error.code in {
                "mail_auth_error", "mail_unavailable", "mail_protocol_error", "mail_configuration_invalid"} else "mail_unavailable"
            with self.factory.begin() as s:
                self.service.owner(s, owner)
                account = s.get(MailAccount, owner)
                if account.lease_token == token:
                    account.failures += 1
                    account.error_code = code
                    account.status = "auth_error" if code == "mail_auth_error" else "error" if account.failures >= 3 else "backoff"
                    account.next_sync_at = now + timedelta(seconds=min(3600, 300 * 2 ** min(account.failures - 1, 4)))
                    account.lease_token = account.lease_until = None
                    status = account.status
                else:
                    status = "superseded"
            if not isinstance(error, MailError):
                # Storage failure is not a successful sync. Do not swallow database errors.
                from sqlalchemy.exc import SQLAlchemyError
                if isinstance(error, SQLAlchemyError):
                    raise
            return {"status": status, "saved": 0, "code": code}

    def _save(self, s, owner, account, item, now):
        key = item.key if item.text is None else digest(item.message_id or item.key)
        row = s.scalar(select(MailMessage).where(MailMessage.owner_id == owner, MailMessage.key == key))
        if item.text is None:
            if row:
                row.flags, row.removed, row.last_checked_at = list(item.flags), item.removed, now
                row.pointer = item.pointer or row.pointer
            return 0
        if item.folder not in ("inbox", "sent") or any(f.lower() in ("\\draft", "\\deleted", "$junk", "\\junk") for f in item.flags):
            return 0
        if not row and (item.arrived_at < now - timedelta(days=7) or item.arrived_at > now + timedelta(minutes=5)):
            return 0
        fingerprint = digest(json.dumps([item.subject, item.sender, item.text, item.original_at.isoformat(), item.attachments, item.unsupported], ensure_ascii=False))
        if row and row.fingerprint == fingerprint:
            row.flags, row.removed, row.pointer, row.last_checked_at = list(item.flags), False, item.pointer, now
            return 0
        thread_id = row.thread_id if row else digest(item.references[0] if item.references else item.message_id or item.key)
        for reference in item.references:
            parent = s.scalar(select(MailMessage).where(MailMessage.owner_id == owner, MailMessage.key == digest(reference)))
            if parent:
                thread_id = parent.thread_id
                break
        revision = row.revision + 1 if row else 1
        metadata = {"mail_sync": True, "mail_thread_id": thread_id, "direction": item.folder,
                    "subject": item.subject, "sender": item.sender, "attachments_unanalysed": item.attachments,
                    "content_incomplete": item.unsupported, "evidence": (item.text or "")[:1000],
                    "evidence_at": item.original_at.isoformat(), "cache_expires_at": (now + timedelta(days=7)).isoformat()}
        identity = self.service._ingest(s, owner, "mail", Incoming(account=f"{account.provider}:{account.account_key}", external_id=key,
            revision=revision, text=item.text or "[Нет доступного текста]", original_at=item.original_at), metadata, now)
        version = s.get(SourceVersion, identity)
        if row:
            # A newer source invalidates undecided suggestions from the old revision.
            for proposal in s.scalars(select(Proposal).join(SourceVersion).where(Proposal.owner_id == owner,
                    SourceVersion.source_id == row.source_id, Proposal.status == "pending")):
                proposal.status, proposal.version = "stale", proposal.version + 1
                for question in s.scalars(select(Dialogue).where(Dialogue.proposal_id == proposal.id, Dialogue.status == "pending")):
                    question.status = "stale"
            row.fingerprint, row.revision = fingerprint, revision
        else:
            row = MailMessage(owner_id=owner, key=key, message_id=item.message_id, thread_id=thread_id,
                              source_id=version.source_id, fingerprint=fingerprint, revision=revision)
            s.add(row)
        row.pointer, row.flags, row.removed, row.last_checked_at = item.pointer, list(item.flags), False, now
        return 1

    def disconnect(self, owner):
        with self.factory.begin() as s:
            self.service.owner(s, owner)
            account = s.get(MailAccount, owner)
            if account:
                account.enabled, account.status = False, "disabled"
                account.lease_token = account.lease_until = None
        return {"status": "disabled"}

    def prune(self, owner):
        changed = 0
        with self.factory.begin() as s:
            self.service.owner(s, owner)
            rows = s.scalars(select(SourceVersion).join(MailMessage, MailMessage.source_id == SourceVersion.source_id).where(
                MailMessage.owner_id == owner, SourceVersion.status == "processed",
                SourceVersion.received_at < self.clock() - timedelta(days=7)))
            for version in rows:
                metadata = version.channel_metadata or {}
                if metadata.get("cache_pruned"):
                    continue
                retained = s.scalar(select(Proposal.id).where(Proposal.source_version_id == version.id,
                    Proposal.status.in_(["pending", "accepted"]))) or s.scalar(select(Task.id).where(Task.source_version_id == version.id))
                # Irrelevant full bodies are removed; linked evidence is retained as a bounded fragment.
                version.text = metadata.get("evidence", "") if retained else "[Почтовый кэш очищен]"
                version.channel_metadata = {**(metadata if retained else {"mail_sync": True}), "cache_pruned": True}
                changed += int(not retained)
        return changed
