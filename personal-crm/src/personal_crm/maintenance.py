"""Explicit offline operations. No production restore or implicit integration startup."""
import argparse
import base64
import json
import os
import time
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from .db import sessions
from .legacy_import import ImportError, import_legacy, inspect_legacy
from .recovery import (BackupConfig, RecoveryError, _write, backup_cycle, create_backup, erase_owner,
                       export_owner, initialize_ledger, inspect_backup, release_hold, restore_backup, seal)


def main():
    parser = argparse.ArgumentParser(description="CRM backup, isolated restore and legacy rehearsal")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("keygen", help="Generate a new key; keep it outside Git and backups")
    commands.add_parser("init-ledger", help="Create a NEW external erasure ledger; refuses overwrite")
    commands.add_parser("backup", help="One encrypted backup to an existing directory")
    loop = commands.add_parser("backup-loop", help="Opt-in daily backups; no channels or AI")
    loop.add_argument("--once", action="store_true")
    for name in ("inspect", "restore"):
        command = commands.add_parser(name)
        command.add_argument("archive", type=Path)
    commands.add_parser("release-hold", help="After offline review; leaves delivery, mail and AI paused")
    export = commands.add_parser("export", help="Owner-only encrypted export")
    export.add_argument("destination", type=Path)
    erase = commands.add_parser("erase-owner", help="Offline erasure, all services must be stopped")
    erase.add_argument("--confirm-owner", required=True)
    for name in ("legacy-preview", "legacy-import"):
        command = commands.add_parser(name)
        command.add_argument("copy", type=Path)
        command.add_argument("--chat", type=int, required=True)
        command.add_argument("--timezone", required=True)
        if name == "legacy-import":
            command.add_argument("--namespace", required=True)
            command.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    config = BackupConfig.from_env()
    owner = os.getenv("CRM_OWNER_ID", "")
    factory = None
    try:
        if args.command == "keygen":
            print(base64.urlsafe_b64encode(os.urandom(32)).decode())
            return
        if args.command == "init-ledger":
            initialize_ledger(config.ledger, config.key)
            result = {"status": "ledger_initialized"}
        elif args.command == "backup":
            result = create_backup(config.database_url, config.directory, config.key, config.pg_bin, config.ledger)
        elif args.command == "inspect":
            result = inspect_backup(args.archive, config.key)
        elif args.command == "restore":
            target = os.getenv("CRM_RESTORE_DATABASE_URL", "")
            if not target:
                raise RecoveryError("restore_target_required")
            result = restore_backup(args.archive, config.key, target, config.pg_bin, config.ledger)
        elif args.command == "backup-loop":
            while True:
                try:
                    result = backup_cycle(config)
                except (RecoveryError, OSError, SQLAlchemyError) as error:
                    if args.once:
                        raise
                    print(json.dumps({"status": "error", "code": str(error) if isinstance(error, RecoveryError) else "backup_unavailable"}), flush=True)
                else:
                    if args.once or result["status"] == "disabled":
                        break
                    if result["status"] == "backed_up":
                        print(json.dumps(result), flush=True)
                time.sleep(60)
        elif args.command == "legacy-preview":
            result = inspect_legacy(args.copy, args.chat, args.timezone)
        else:
            if not owner:
                raise RecoveryError("owner_required")
            if args.command == "release-hold":
                target = os.getenv("CRM_RESTORE_DATABASE_URL", "")
                if not target:
                    raise RecoveryError("restore_target_required")
                release_hold(target, owner, config.ledger, config.key)
                result = {"status": "hold_released_integrations_still_paused"}
            elif args.command == "erase-owner":
                if args.confirm_owner != owner:
                    raise RecoveryError("owner_confirmation_mismatch")
                erase_owner(config.database_url, owner, config.ledger, config.key)
                result = {"status": "owner_erased"}
            else:
                factory = sessions(config.database_url)
                if args.command == "legacy-import":
                    result = import_legacy(factory, args.copy, owner, args.chat, args.timezone, args.namespace, args.expected_sha256)
                else:
                    data = json.dumps(export_owner(factory, owner), ensure_ascii=False).encode("utf-8")
                    _write(args.destination, seal(data, config.key, "export"))
                    result = {"status": "exported_encrypted"}
        print(json.dumps(result, ensure_ascii=False), flush=True)
    except (RecoveryError, ImportError, SQLAlchemyError, OSError, ValueError) as error:
        code = str(error) if isinstance(error, (RecoveryError, ImportError)) else "maintenance_unavailable"
        print(json.dumps({"status": "error", "code": code}), flush=True)
        raise SystemExit(1) from None
    finally:
        if factory:
            factory.kw["bind"].dispose()


if __name__ == "__main__":
    main()
