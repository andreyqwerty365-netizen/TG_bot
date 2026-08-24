from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


def main() -> int:
    base_temp = Path(tempfile.gettempdir()) / f"telegram-assistant-pytest-{uuid.uuid4().hex}"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        f"--basetemp={base_temp}",
        *sys.argv[1:],
    ]
    try:
        return subprocess.run(command, check=False).returncode
    finally:
        shutil.rmtree(base_temp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
