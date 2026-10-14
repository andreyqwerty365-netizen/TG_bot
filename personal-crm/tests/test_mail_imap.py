from datetime import UTC, datetime
from email.message import EmailMessage

import pytest

from personal_crm.mail import MailConfig, MailError, digest
from personal_crm.mail_imap import IMAPProvider


class Wire:
    def __init__(self):
        self.calls = []; self.folder = "INBOX"; self.validity = b"42"
        message = EmailMessage()
        message["Message-ID"] = "<wire@example.invalid>"
        message["Subject"] = "Synthetic report"
        message["Date"] = "Tue, 13 Oct 2026 08:00:00 +0000"
        message.set_content("Please prepare the synthetic report.")
        self.raw = message.as_bytes()
        self.ids = {"INBOX": [1, 2], "Sent": [4]}

    def login(self, user, password):
        self.calls.append(("login",)); return "OK", []

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\Sent) "/" "Sent"']

    def select(self, folder, readonly=False):
        assert readonly is True
        self.folder = folder.strip('"')
        self.calls.append(("EXAMINE", self.folder)); return "OK", [b"2"]

    def response(self, name):
        return name, [self.validity]

    def uid(self, command, *args):
        self.calls.append((command, *args))
        if command == "SEARCH":
            return "OK", [b" ".join(str(n).encode() for n in self.ids[self.folder])]
        assert command == "FETCH", "adapter must never write mail"
        number = args[0]
        if number == "999":
            return "OK", [None]
        header = f'{number} (UID {number} FLAGS () RFC822.SIZE {len(self.raw)} INTERNALDATE "13-Oct-2026 08:00:00 +0000"'.encode()
        if "BODY.PEEK" in args[1]:
            return "OK", [(header + b" BODY[] {99}", self.raw), b")"]
        return "OK", [header + b")"]

    def logout(self):
        self.calls.append(("LOGOUT",)); return "BYE", []


def provider(wire):
    return IMAPProvider(MailConfig(enabled=True, consent=True, host="imap.example.invalid", username="synthetic",
                                  password="synthetic-password", sent_folder="Sent"), client_factory=lambda config: wire)


def test_only_examine_uid_peek_and_logout_and_paginated_high_watermark():
    wire = Wire(); adapter = provider(wire)
    now = datetime(2026, 10, 13, 8, tzinfo=UTC)
    page = adapter.changes(None, now, 2, [])
    assert len(page.items) == 2 and page.has_more
    assert page.cursor["folders"]["INBOX"]["uid"] == 2
    assert "Sent" not in page.cursor["folders"] or page.cursor["folders"]["Sent"]["uid"] == 0
    next_page = adapter.changes(page.cursor, now, 2, [])
    assert len(next_page.items) == 1 and next_page.items[0].folder == "sent"
    assert wire.calls[-1] == ("LOGOUT",)
    assert all("BODY[" not in c[-1] for c in wire.calls if c[0] == "FETCH")
    assert any("BODY.PEEK[]" in c[-1] for c in wire.calls if c[0] == "FETCH")


def test_uidvalidity_reset_and_deleted_metadata_are_reported():
    wire = Wire(); wire.validity = b"77"
    adapter = provider(wire); now = datetime(2026, 10, 13, 8, tzinfo=UTC)
    page = adapter.changes({"folders": {"INBOX": {"validity": "42", "uid": 900}}}, now, 25, [])
    assert page.reset and page.items
    tracked = [{"key": digest("gone"), "pointer": {"folder": "INBOX", "validity": "77", "uid": "999"}}]
    delta = adapter.changes(page.cursor, now, 25, tracked)
    assert len(delta.items) == 1 and delta.items[0].removed and delta.items[0].text is None


def test_auth_failure_sanitizes_secret_and_logs_out():
    wire = Wire()
    def failed(*args):
        import imaplib
        raise imaplib.IMAP4.error("synthetic-password private server reply")
    wire.login = failed
    with pytest.raises(MailError, match="^mail_auth_error$"):
        provider(wire).changes(None, datetime.now(UTC), 25, [])
    assert wire.calls[-1] == ("LOGOUT",)


def test_oversized_body_is_not_fetched_and_drafts_are_excluded():
    wire = Wire(); original = wire.uid
    def large(command, *args):
        result = original(command, *args)
        if command == "FETCH" and "BODY.PEEK" not in args[1]:
            return "OK", [f'{args[0]} (UID {args[0]} FLAGS (\\Draft) RFC822.SIZE 99999999 INTERNALDATE "13-Oct-2026 08:00:00 +0000")'.encode()]
        return result
    wire.uid = large
    page = provider(wire).changes(None, datetime(2026, 10, 13, 8, tzinfo=UTC), 25, [])
    assert not page.items
    assert not any("BODY.PEEK" in c[-1] for c in wire.calls if c[0] == "FETCH")


def test_busy_inbox_does_not_starve_sent_folder():
    wire = Wire(); wire.ids["INBOX"] = list(range(1, 100))
    adapter = provider(wire); now = datetime(2026, 10, 13, 8, tzinfo=UTC)
    first = adapter.changes(None, now, 2, [])
    second = adapter.changes(first.cursor, now, 2, [])
    assert any(entry.folder == "sent" for entry in second.items)


def test_uidvalidity_reset_rebinds_tracked_old_message_by_message_id():
    wire = Wire(); wire.validity = b"77"; adapter = provider(wire)
    now = datetime(2026, 10, 13, 8, tzinfo=UTC)
    tracked = [{"key": digest("<wire@example.invalid>"), "message_id": "<wire@example.invalid>",
                "pointer": {"folder": "INBOX", "validity": "42", "uid": "999"}}]
    page = adapter.changes({"folders": {"INBOX": {"validity": "77", "uid": 50}, "Sent": {"validity": "77", "uid": 50}}}, now, 25, tracked)
    assert any(entry.pointer["validity"] == "77" for entry in page.items)
    assert any(c[0] == "SEARCH" and "HEADER" in c for c in wire.calls)


def test_server_may_return_uid_after_the_body_literal():
    wire = Wire(); original = wire.uid
    def uid_last(command, *args):
        if command == "FETCH" and "BODY.PEEK" in args[1]:
            return "OK", [(b"1 (BODY[] {99}", wire.raw), f" UID {args[0]})".encode()]
        return original(command, *args)
    wire.uid = uid_last
    page = provider(wire).changes(None, datetime(2026, 10, 13, 8, tzinfo=UTC), 25, [])
    assert len(page.items) == 3
