"""Recover committed sources independently of Telegram re-delivery or reminder sends."""
import argparse
import time

from sqlalchemy.exc import SQLAlchemyError

from .config import Settings
from .db import sessions
from .openai_adapter import ContextInterpreter, ResponsesAdapter
from .service import CRMError, CRMService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    if not settings.owner_id or not settings.owner_token:
        print("source worker outcome=owner_not_configured", flush=True)
        raise SystemExit(1)
    factory = sessions(settings.database_url)
    service = CRMService(factory, ContextInterpreter(ResponsesAdapter(factory, settings.ai)))
    last_prune = -300
    while True:
        failed = False
        try:
            service.register(settings.owner_id, settings.timezone, initialize_only=True)
            result = service.recover_sources(settings.owner_id)
            if time.monotonic() - last_prune >= 300:
                from .mail import MailSync
                MailSync(service, None).prune(settings.owner_id)
                last_prune = time.monotonic()
            if args.once or result["processed"]:
                print(f"source worker processed={result['processed']}", flush=True)
        except (SQLAlchemyError, CRMError):
            failed = True
            print("source worker outcome=unavailable", flush=True)
        if args.once:
            if failed:
                raise SystemExit(1)
            return
        time.sleep(5)


if __name__ == "__main__":
    main()
