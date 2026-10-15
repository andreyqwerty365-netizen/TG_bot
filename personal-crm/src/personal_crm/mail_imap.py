"""IMAP SSL reader. EXAMINE + UID FETCH BODY.PEEK; never SELECT writable or CLOSE."""
import base64
from copy import deepcopy
from datetime import UTC, datetime
import imaplib
import re
import ssl
import time

from .mail import MailError, MailItem, MailPage, digest, parse_message


def quote_folder(value):
    if not value or len(value) > 300 or any(c in value for c in "\r\n\x00*%"):
        raise MailError("mail_configuration_invalid")
    # IMAP4rev1 modified UTF-7, including non-English Sent folder names.
    result, run = [], []
    def flush():
        if run:
            encoded = base64.b64encode("".join(run).encode("utf-16-be")).decode().rstrip("=").replace("/", ",")
            result.append("&" + encoded + "-"); run.clear()
    for char in value:
        if 32 <= ord(char) <= 126:
            flush(); result.append("&-" if char == "&" else char)
        else:
            run.append(char)
    flush()
    return '"' + "".join(result).replace("\\", "\\\\").replace('"', '\\"') + '"'


def ok(response):
    if response[0] != "OK":
        raise MailError("mail_protocol_error")
    return response[1]


def metadata(data, number):
    raw = b" ".join(x[0] if isinstance(x, tuple) else x for x in data if x)
    uid = re.search(rb"\bUID (\d+)", raw)
    if not uid:
        return None
    if uid.group(1).decode() != str(number):
        raise MailError("mail_protocol_error")
    size = re.search(rb"RFC822.SIZE (\d+)", raw)
    stamp = re.search(rb'INTERNALDATE "([^"]+)"', raw)
    if not size or not stamp:
        raise MailError("mail_protocol_error")
    # RFC months are English regardless of the process locale.
    date_pattern = re.fullmatch(r"(\d{1,2})-([A-Za-z]{3})-(\d{4}) (\d{2}:\d{2}:\d{2}) ([+-]\d{4})", stamp.group(1).decode().strip())
    months = {name: n for n, name in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}
    if not date_pattern or date_pattern[2] not in months:
        raise MailError("mail_protocol_error")
    try:
        arrived = datetime.strptime(f"{date_pattern[3]}-{months[date_pattern[2]]:02}-{int(date_pattern[1]):02} {date_pattern[4]} {date_pattern[5]}", "%Y-%m-%d %H:%M:%S %z").astimezone(UTC)
    except ValueError:
        raise MailError("mail_protocol_error") from None
    return int(size.group(1)), arrived, tuple(f.decode("ascii", errors="replace") for f in imaplib.ParseFlags(raw))


class IMAPProvider:
    name = "imap"

    def __init__(self, config, client_factory=None):
        if not config.enabled or not config.consent:
            raise MailError("mail_disabled")
        if config.sent_folder.casefold() in {"inbox", "spam", "junk", "trash", "drafts", "корзина", "спам", "черновики"}:
            raise MailError("mail_configuration_invalid")
        self.config = config
        self.folders = [("INBOX", "inbox"), (config.sent_folder, "sent")]
        for folder, _ in self.folders:
            quote_folder(folder)
        self.account_key = digest(config.host.casefold() + ":" + str(config.port) + "\n" + config.username)
        self.client_factory = client_factory or (lambda c: imaplib.IMAP4_SSL(c.host, c.port,
            ssl_context=ssl.create_default_context(), timeout=c.timeout))

    def _read(self, client, number, direction, pointer, size, arrived, flags):
        query = f"(UID BODY.PEEK[]<0.{self.config.max_bytes + 1}>)" if size <= self.config.max_bytes else "(UID BODY.PEEK[HEADER.FIELDS (MESSAGE-ID REFERENCES IN-REPLY-TO DATE SUBJECT FROM)]<0.16384>)"
        content = ok(client.uid("FETCH", str(number), query))
        literals = []
        response_metadata = b" ".join(part[0] if isinstance(part, tuple) else part for part in content if part)
        identities = re.findall(rb"\bUID (\d+)", response_metadata)
        if content and any(isinstance(part, tuple) for part in content) and (not identities or any(value.decode() != str(number) for value in identities)):
            raise MailError("mail_protocol_error")
        for part in content:
            if isinstance(part, tuple):
                literals.append(part[1])
        if not literals:
            return None
        raw = b"".join(literals)
        if len(raw) > self.config.max_bytes:
            raise MailError("mail_protocol_error")
        entry = parse_message(raw, direction, json_key(pointer), arrived, self.config.max_bytes)
        if size > self.config.max_bytes:
            entry.text, entry.unsupported = "[Письмо превышает лимит; тело и вложения не загружены]", True
        entry.pointer, entry.flags = pointer, flags
        return entry

    def _connect(self):
        client = self.client_factory(self.config)
        try:
            try:
                ok(client.login(self.config.username, self.config.password))
            except imaplib.IMAP4.abort:
                raise MailError("mail_unavailable") from None
            except (imaplib.IMAP4.error, MailError):
                raise MailError("mail_auth_error") from None
            listings = ok(client.list())
            for folder, _ in self.folders:
                encoded = quote_folder(folder).encode()
                line = next((line for line in listings if line and (line.endswith(encoded) or line.endswith(b" " + encoded[1:-1]))), None)
                if line is None or any(flag in line.split(b")", 1)[0].lower() for flag in (b"\\junk", b"\\trash", b"\\drafts", b"\\noselect")):
                    raise MailError("mail_configuration_invalid")
            return client
        except Exception:
            self._disconnect(client)
            raise

    @staticmethod
    def _disconnect(client):
        # CLOSE may expunge on some clients. LOGOUT is sufficient for a read-only session.
        try:
            client.logout()
        except (OSError, imaplib.IMAP4.error):
            pass

    def check_access(self):
        client = self._connect()
        try:
            for folder, _ in self.folders:
                ok(client.select(quote_folder(folder), readonly=True))
            return {"read_only": True, "folders": 2}
        finally:
            self._disconnect(client)

    def changes(self, cursor, since, limit, tracked):
        client = None
        started = time.monotonic()
        state = deepcopy(cursor or {"folders": {}})
        folders = state.setdefault("folders", {})
        items, checked = [], []
        more = reset = False
        fetched = 0
        # Locale-independent SINCE is an intentionally broad server filter; ingestion checks the exact instant.
        months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
        since_date = f"{since.day:02}-{months[since.month - 1]}-{since.year}"
        try:
            client = self._connect()
            start = int(state.get("next_folder", 0)) % len(self.folders)
            ordered_folders = self.folders[start:] + self.folders[:start]
            for folder, direction in ordered_folders:
                if fetched >= limit or time.monotonic() - started >= 45:
                    state["next_folder"] = self.folders.index((folder, direction))
                    more = True
                    break
                ok(client.select(quote_folder(folder), readonly=True))
                validity_data = client.response("UIDVALIDITY")[1]
                validity = (validity_data or [b""])[0]
                if not validity or not validity.isdigit():
                    raise MailError("mail_protocol_error")
                validity = validity.decode()
                previous = folders.get(folder, {})
                if previous and previous.get("validity") != validity:
                    previous = {}; reset = True
                last = int(previous.get("uid", 0))
                current = {"validity": validity, "uid": last}
                folders[folder] = current
                result = ok(client.uid("SEARCH", None, "UID", f"{last + 1}:*", "SINCE", since_date))
                raw_ids = result[0] or b""
                if len(raw_ids) > 1000000 or not re.fullmatch(rb"[0-9 ]*", raw_ids):
                    raise MailError("mail_protocol_error")
                # UID n:* also includes the largest UID when n exceeds it (RFC range semantics).
                numbers = sorted({int(n) for n in raw_ids.split() if int(n) > last})
                for number in numbers:
                    if fetched >= limit or time.monotonic() - started >= 45:
                        more = True; break
                    info = metadata(ok(client.uid("FETCH", str(number), "(UID FLAGS RFC822.SIZE INTERNALDATE)")), number)
                    fetched += 1
                    if info:
                        size, arrived, flags = info
                        if not any(f.lower() in ("\\deleted", "\\draft", "$junk", "\\junk") for f in flags) and arrived >= since:
                            pointer = {"folder": folder, "validity": validity, "uid": str(number)}
                            entry = self._read(client, number, direction, pointer, size, arrived, flags)
                            if entry is None:
                                # A concurrent deletion is retried without skipping this UID.
                                more = True; break
                            items.append(entry)
                    current["uid"] = number
                # Rotate through bounded tracked metadata; no repeated body download or interpretation.
                for record in tracked:
                    pointer = record.get("pointer") or {}
                    if pointer.get("folder") != folder:
                        continue
                    if time.monotonic() - started >= 45:
                        more = True; break
                    number = pointer.get("uid", "")
                    rebound = pointer.get("validity") != validity
                    if rebound:
                        checked.append(record["key"])
                        message_id = record.get("message_id", "")
                        if not re.fullmatch(r"<[^<>\s]{1,998}>", message_id):
                            # Without Message-ID, old UIDs cannot safely be rebound to other messages.
                            continue
                        quoted_id = '"' + message_id.replace("\\", "\\\\").replace('"', '\\"') + '"'
                        result = ok(client.uid("SEARCH", None, "HEADER", "Message-ID", quoted_id))
                        matches = (result[0] or b"").split()
                        if any(not n.isdigit() for n in matches):
                            raise MailError("mail_protocol_error")
                        number = str(max(int(n) for n in matches)) if matches else "0"
                        pointer = {"folder": folder, "validity": validity, "uid": number}
                    if not str(number).isdigit():
                        raise MailError("mail_protocol_error")
                    info = metadata(ok(client.uid("FETCH", number, "(UID FLAGS RFC822.SIZE INTERNALDATE)")), number) if number != "0" else None
                    checked.append(record["key"])
                    flags = info[2] if info else ()
                    removed = info is None or "\\Deleted" in flags
                    if rebound and info and not removed:
                        entry = self._read(client, number, direction, pointer, *info)
                        if entry:
                            if entry.message_id != record["message_id"]:
                                raise MailError("mail_protocol_error")
                            items.append(entry)
                        continue
                    # key is already hashed in the database; ingestion accepts it as a metadata identity.
                    entry = MailItem(record["key"], "", (), direction, since, since, "", "", None,
                                     flags=flags, removed=removed, pointer=pointer)
                    items.append(entry)
                state["next_folder"] = (self.folders.index((folder, direction)) + 1) % len(self.folders)
            return MailPage(items, state, more, reset, tuple(checked))
        except MailError:
            raise
        except (OSError, imaplib.IMAP4.error, ValueError, TypeError, IndexError):
            raise MailError("mail_unavailable") from None
        finally:
            if client:
                self._disconnect(client)


def json_key(pointer):
    return f"{pointer['folder']}:{pointer['validity']}:{pointer['uid']}"
