from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".pytest_tmp", ".tmp", "backups", "build", "data", "dist", "logs"}
SKIP_SUFFIXES = {".db", ".pyc", ".pyo", ".sqlite"}


def should_skip(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in SKIP_DIRS for part in relative.parts):
        return True
    if path.suffix.lower() in SKIP_SUFFIXES:
        return True
    return path.name.startswith(".env") and path.name not in {".env.example", ".env.vps.example"}


def main() -> int:
    failures: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or should_skip(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if TOKEN_RE.search(text):
            failures.append(str(path.relative_to(ROOT)))

    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    if ".env" not in dockerignore:
        failures.append(".dockerignore does not exclude .env")
    if ".env" not in gitignore:
        failures.append(".gitignore does not exclude .env")

    if failures:
        print("Secret check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Secret check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
