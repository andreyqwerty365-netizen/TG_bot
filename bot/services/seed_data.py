from __future__ import annotations

import base64
import gzip
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Mapping


def restore_seed_databases(payloads: Mapping[Path, str], marker: Path) -> list[Path]:
    """Restore initial SQLite files exactly once and mark the data volume."""
    if marker.exists():
        return []

    pending = [(Path(target), encoded.strip()) for target, encoded in payloads.items() if encoded.strip()]
    if not pending:
        return []

    prepared: list[tuple[Path, Path]] = []
    try:
        for target, encoded in pending:
            target.parent.mkdir(parents=True, exist_ok=True)
            raw = base64.b64decode(encoded, validate=True)
            if raw.startswith(b"\x1f\x8b"):
                raw = gzip.decompress(raw)
            with tempfile.NamedTemporaryFile(prefix=f".{target.name}.", suffix=".seed", dir=target.parent, delete=False) as handle:
                handle.write(raw)
                temp_path = Path(handle.name)
            connection = sqlite3.connect(temp_path)
            try:
                status = connection.execute("PRAGMA quick_check").fetchone()
            finally:
                connection.close()
            if status != ("ok",):
                raise ValueError(f"Seed database {target.name} failed SQLite quick_check")
            prepared.append((target, temp_path))

        for target, temp_path in prepared:
            os.replace(temp_path, target)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("restored\n", encoding="utf-8")
        return [target for target, _ in prepared]
    finally:
        for _, temp_path in prepared:
            temp_path.unlink(missing_ok=True)
