"""Poll explicitly enabled read-only mail; never discover or connect an account implicitly."""
import argparse
import time

from sqlalchemy.exc import SQLAlchemyError

from .config import Settings
from .db import sessions
from .mail import MailError, MailSync, build_provider
from .openai_adapter import ContextInterpreter, ResponsesAdapter
from .service import CRMError, CRMService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    # No network client, SDK or database is needed to determine disabled state.
    if not settings.mail.enabled or not settings.mail.consent:
        print("mail worker outcome=disabled", flush=True)
        return
    if not settings.owner_id or not settings.owner_token:
        print("mail worker outcome=owner_not_configured", flush=True)
        raise SystemExit(1)
    try:
        provider = build_provider(settings.mail)
    except MailError:
        print("mail worker outcome=configuration_invalid", flush=True)
        raise SystemExit(1) from None
    factory = sessions(settings.database_url)
    service = CRMService(factory, ContextInterpreter(ResponsesAdapter(factory, settings.ai)))
    worker = MailSync(service, provider, settings.mail.batch_size)
    while True:
        failed = False
        try:
            service.register(settings.owner_id, settings.timezone, initialize_only=True)
            result = worker.run(settings.owner_id)
            service.recover_sources(settings.owner_id)
            if args.once or result["status"] not in ("not_due", "disabled", "busy"):
                print(f"mail worker outcome={result['status']} saved={result['saved']}", flush=True)
            failed = result["status"] in ("auth_error", "error", "backoff")
        except (SQLAlchemyError, CRMError, MailError):
            failed = True
            print("mail worker outcome=unavailable", flush=True)
        if args.once:
            if failed:
                raise SystemExit(1)
            return
        time.sleep(5)


if __name__ == "__main__":
    main()
