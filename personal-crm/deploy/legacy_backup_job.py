"""Hold SQLite read-only connections while an entirely read-only source job runs.

SQLite may create WAL/SHM metadata when an idle WAL database has no sidecars.
Only the small host wrapper can do that; the network-enabled container receives
a read-only bind mount. Neither connection can execute writes to database pages.
"""
import argparse
import json
import sqlite3
import subprocess
from contextlib import ExitStack, closing
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("/srv/legacy-reminder-bot/data"))
    parser.add_argument("--env-file", type=Path, default=Path("/etc/legacy-reminder-bot/config/backup-deploy.env"))
    parser.add_argument("--compose-file", type=Path, default=Path(__file__).parent / "compose.legacy-backup.yaml")
    args = parser.parse_args()
    try:
        with ExitStack() as stack:
            for name in ("notes.db", "workouts.sqlite3"):
                path = args.source / name
                if path.is_symlink() or not path.is_file():
                    raise OSError()
                db = stack.enter_context(closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)))
                db.execute("PRAGMA query_only=ON")
                db.execute("SELECT count(*) FROM sqlite_master").fetchone()
            result = subprocess.run(["/usr/bin/docker", "compose", "--env-file", str(args.env_file),
                                     "-f", str(args.compose_file), "run", "--rm", "-T", "--interactive=false", "backup"],
                                    stdin=subprocess.DEVNULL, timeout=540, check=False)
            return result.returncode
    except (OSError, sqlite3.Error, subprocess.TimeoutExpired):
        print(json.dumps({"status": "failed", "code": "readonly_snapshot_job_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
