"""Isolated Bot API boundary. No polling and no webhook installation."""
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import json
import logging
import time

import httpx
from sqlalchemy import func, select

from .adapters import DeliveryError, DeliveryUnknown
from .models import Attempt, Job, OutgoingReply, Source, SourceVersion, TelegramReceipt
from .service import CRMError


def integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise CRMError("invalid_telegram_update", 422)
    return value


@dataclass
class TelegramInput:
    external_id: str
    account: str
    text: str
    revision: int
    original_at: datetime | None


class TelegramIngress:
    def __init__(self, service, config, owner_id):
        self.service, self.config, self.owner_id = service, config, owner_id

    def authenticate_webhook(self, secret):
        if not self.config.webhook_enabled:
            raise CRMError("telegram_webhook_disabled", 404)
        if not self.config.webhook_secret or not secret or not hmac.compare_digest(secret.encode(), self.config.webhook_secret.encode()):
            raise CRMError("unauthorized_webhook", 401)

    def accept(self, payload):
        cfg = self.config
        if not self.owner_id or not cfg.bot_id or not cfg.allowed_user_ids or not cfg.allowed_chat_ids:
            raise CRMError("telegram_not_configured", 503)
        try:
            update_id = integer(payload["update_id"])
            edited = "edited_message" in payload
            message = payload["edited_message" if edited else "message"]
            sender, chat = message["from"], message["chat"]
            user_id = integer(sender["id"], 1)
            chat_id = chat["id"]
            if type(chat_id) is not int or sender.get("is_bot") is not False:
                raise CRMError("forbidden_telegram_actor", 403)
            if user_id not in cfg.allowed_user_ids or chat_id not in cfg.allowed_chat_ids:
                raise CRMError("forbidden_telegram_actor", 403)
            if chat["type"] != "private" and not (cfg.allow_groups and chat["type"] in ("group", "supergroup")):
                raise CRMError("forbidden_telegram_chat", 403)
            message_id = integer(message["message_id"], 1)
            sent_at = datetime.fromtimestamp(integer(message["date"], 1), UTC)
            text = message.get("text", message.get("caption", ""))
            if not isinstance(text, str) or len(text) > 16000:
                raise CRMError("invalid_telegram_update", 422)
            origin = message.get("forward_origin")
            legacy_forward = message.get("forward_date")
            channel = "forward" if origin or legacy_forward else "owner"
            original_at = datetime.fromtimestamp(integer(origin["date"] if origin else legacy_forward, 1), UTC) if channel == "forward" else None
            if original_at and original_at > sent_at:
                raise CRMError("invalid_forward_date", 422)
            account = f"telegram:{cfg.bot_id}:{chat_id}"
            metadata = {"reply_required": True, "message_id": message_id, "message_date": sent_at.isoformat(),
                        "bot_id": cfg.bot_id, "edited": edited, "unsupported_media": not text,
                        "forward_origin_type": origin.get("type", "unknown") if origin else "legacy" if legacy_forward else None}
            if edited:
                integer(message["edit_date"], 1)
            digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            raise CRMError("invalid_telegram_update", 422)
        version_id, duplicate = self._store(account, update_id, digest, message, message_id, metadata, edited, text, channel, original_at)
        if duplicate:
            with self.service.factory() as s:
                version = s.get(SourceVersion, version_id)
                resumable = version.status == "pending" or (version.status == "processing" and
                            version.parse_until <= self.service.clock())
            if not resumable:
                return {"status": "duplicate", "source_version_id": version_id}
        return self.service.process(self.owner_id, version_id)

    def _store(self, account, update_id, digest, message, message_id, metadata, edited, text, channel, original_at):
        cfg = self.config
        with self.service.factory.begin() as s:
            self.service.owner(s, self.owner_id)
            receipt = s.scalar(select(TelegramReceipt).where(TelegramReceipt.owner_id == self.owner_id,
                                TelegramReceipt.account == account, TelegramReceipt.update_id == update_id))
            if receipt:
                if receipt.payload_digest != digest:
                    raise CRMError("telegram_update_conflict")
                return receipt.source_version_id, True
            referenced = message.get("reply_to_message", {})
            reply_id = referenced.get("message_id")
            if type(reply_id) is int:
                # Owned inbound message, or a recorded outbound bot reply. No trust in quoted text.
                linked = s.scalar(select(SourceVersion).join(Source).where(Source.owner_id == self.owner_id,
                    Source.account == account, Source.external_id == str(reply_id)).order_by(SourceVersion.revision.desc()).limit(1))
                if not linked and str(referenced.get("from", {}).get("id", "")) == cfg.bot_id:
                    linked = s.scalar(select(SourceVersion).join(OutgoingReply, OutgoingReply.source_version_id == SourceVersion.id)
                        .join(Job, Job.reply_id == OutgoingReply.id).join(Attempt, Attempt.job_id == Job.id)
                        .join(Source, Source.id == SourceVersion.source_id).where(
                        Source.owner_id == self.owner_id, Source.account == account,
                        Attempt.provider_id == f"telegram:{reply_id}", Attempt.outcome == "success"))
                if linked:
                    metadata["reply_source_version_id"] = linked.id
            previous = s.scalar(select(SourceVersion).join(Source).where(Source.owner_id == self.owner_id,
                                Source.account == account, Source.external_id == str(message_id))
                                .order_by(SourceVersion.revision.desc()).limit(1))
            revision = previous.revision + 1 if edited and previous else 1
            if edited and previous:
                # An edit may omit forwarding fields, but cannot upgrade source trust.
                channel = s.get(Source, previous.source_id).channel
                original_at = previous.original_at
                metadata["forward_origin_type"] = (previous.channel_metadata or {}).get("forward_origin_type")
            incoming = TelegramInput(str(message_id), account, text, revision, original_at)
            version_id = self.service._ingest(s, self.owner_id, channel, incoming, metadata)
            s.add(TelegramReceipt(owner_id=self.owner_id, account=account, update_id=update_id,
                                  payload_digest=digest, source_version_id=version_id))
            replay_message = previous is not None and not edited
        return version_id, replay_message


class TelegramTransport:
    """Plain text to an explicitly configured dedicated test bot/chat; unknown delivery stops retries."""
    def __init__(self, config, owner_id, client=None):
        self.config, self.owner_id = config, owner_id
        self.client = client
        self.verified = False

    def _call(self, method, payload):
        for name in ("httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.WARNING)
        client = self.client or httpx.Client(timeout=httpx.Timeout(3), follow_redirects=False)
        try:
            started = time.monotonic()
            with client.stream("POST", f"https://api.telegram.org/bot{self.config.test_token}/{method}", json=payload,
                               timeout=httpx.Timeout(3)) as response:
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 65536 or time.monotonic() - started > 5:
                        raise DeliveryUnknown()
                    chunks.append(chunk)
                body = json.loads(b"".join(chunks))
            if body.get("ok") is False:
                raise DeliveryError()
            if response.status_code >= 400 or body.get("ok") is not True:
                raise DeliveryUnknown()
            return body["result"]
        except DeliveryError:
            raise
        except Exception:
            raise DeliveryUnknown() from None
        finally:
            if self.client is None:
                client.close()

    def send(self, delivery_id, owner_id, text):
        cfg = self.config
        if (not cfg.send_enabled or not cfg.test_token or not cfg.bot_id or not cfg.allowed_user_ids
            or cfg.outbound_chat_id not in cfg.allowed_chat_ids or owner_id != self.owner_id or not self.owner_id):
            raise DeliveryError()
        if not self.verified:
            identity = self._call("getMe", {})
            if str(identity.get("id")) != cfg.bot_id or identity.get("is_bot") is not True:
                raise DeliveryError()
            self.verified = True
        if not text or len(text.encode("utf-16-le")) // 2 > 4096:
            raise DeliveryError()
        result = self._call("sendMessage", {"chat_id": cfg.outbound_chat_id, "text": text,
                                          "link_preview_options": {"is_disabled": True}})
        if type(result.get("message_id")) is not int or result["message_id"] < 1:
            raise DeliveryUnknown()
        return f"telegram:{result['message_id']}"
