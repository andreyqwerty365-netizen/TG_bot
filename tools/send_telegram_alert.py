from __future__ import annotations

import os
import sys
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: send_telegram_alert.py <message>")
    token = os.getenv("BOT_TOKEN", "").strip()
    chat_id = os.getenv("BOT_ALERT_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise SystemExit("BOT_TOKEN and BOT_ALERT_CHAT_ID are required.")
    data = urlencode({"chat_id": chat_id, "text": sys.argv[1]}).encode("utf-8")
    request = Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data, method="POST")
    try:
        with urlopen(request, timeout=15) as response:
            if response.status != 200:
                raise SystemExit(f"Telegram alert failed with HTTP {response.status}.")
    except HTTPError as exc:
        raise SystemExit(f"Telegram alert failed with HTTP {exc.code}.") from None
    except (URLError, TimeoutError):
        raise SystemExit("Telegram alert request failed.") from None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
