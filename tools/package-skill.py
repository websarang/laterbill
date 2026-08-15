#!/usr/bin/env python3
"""Create and verify the submission ZIP from an explicit Skill allowlist."""

from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "laterbill"
TARGET = ROOT / "laterbill-skill.zip"
ALLOWED_TOP_LEVEL = {"SKILL.md", "agents", "scripts", "references", "fixtures"}
EXCLUDED_PARTS = {"__pycache__", ".omx", ".omc"}


def included_files() -> list[Path]:
    files: list[Path] = []
    for path in SKILL.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(SKILL)
        if relative.parts[0] not in ALLOWED_TOP_LEVEL:
            continue
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        files.append(path)
    return sorted(files)


files = included_files()
with ZipFile(TARGET, "w", ZIP_DEFLATED, compresslevel=9) as archive:
    for path in files:
        archive.write(path, (Path("laterbill") / path.relative_to(SKILL)).as_posix())

with ZipFile(TARGET) as archive:
    infos = archive.infolist()
    unpacked = sum(info.file_size for info in infos)
    names = [info.filename for info in infos]

assert TARGET.stat().st_size <= 3_000_000, "compressed ZIP exceeds 3,000,000 bytes"
assert unpacked <= 30_000_000, "unpacked ZIP exceeds 30,000,000 bytes"
assert len(infos) <= 500, "ZIP exceeds 500 files"
assert all("__pycache__" not in name and not name.endswith(".pyc") for name in names)
assert "laterbill/SKILL.md" in names
assert "laterbill/agents/openai.yaml" in names
assert "laterbill/scripts/repayment.py" in names
assert not any(name.startswith("laterbill/samples/") for name in names)

digest = hashlib.sha256(TARGET.read_bytes()).hexdigest()
print(f"files={len(infos)} compressed={TARGET.stat().st_size} unpacked={unpacked}")
print(f"sha256={digest}")
