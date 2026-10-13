"""Download locked public wheels with normal TLS verification, then checksum them."""
import hashlib
from pathlib import Path
import subprocess
import sys

target = Path(".runtime/wheels")
target.mkdir(parents=True, exist_ok=True)
subprocess.run([sys.executable, "-m", "pip", "download", "--no-cache-dir", "--only-binary=:all:",
                "--dest", str(target), "-r", "requirements.lock"], check=True)
checksums = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}"
             for p in sorted(target.glob("*.whl"))]
(target / "SHA256SUMS").write_text("\n".join(checksums) + "\n")
print(f"Prepared {len(checksums)} wheels; Docker installs offline and rechecks SHA256SUMS")
