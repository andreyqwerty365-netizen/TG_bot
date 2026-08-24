from __future__ import annotations

from urllib.error import URLError

import pytest

from tools import send_telegram_alert


def test_alert_network_error_does_not_expose_token(monkeypatch):
    token = "123456789:" + "abcdefghijklmnopqrstuvwxyzABCDE"
    monkeypatch.setenv("BOT_TOKEN", token)
    monkeypatch.setenv("BOT_ALERT_CHAT_ID", "123456789")
    monkeypatch.setattr("sys.argv", ["send_telegram_alert.py", "test"])
    monkeypatch.setattr(
        send_telegram_alert,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(URLError(f"https://api.telegram.org/bot{token}/sendMessage")),
    )

    with pytest.raises(SystemExit) as exc_info:
        send_telegram_alert.main()

    assert str(exc_info.value) == "Telegram alert request failed."
    assert token not in str(exc_info.value)
