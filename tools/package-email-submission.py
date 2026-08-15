#!/usr/bin/env python3
"""Build the email handoff ZIP without changing the executable Skill ZIP."""

from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
SOURCE_INFO = ROOT / "submission" / "SUBMISSION.md"
SOURCE_SKILL = ROOT / "laterbill-skill.zip"
SOURCE_LICENSE = ROOT / "LICENSE"
SOURCE_IMAGES = ROOT / "docs" / "assets" / "evidence"
TARGET = ROOT / "laterbill-email-submission.zip"
FIXED_TIME = (2026, 8, 15, 0, 0, 0)


def add_bytes(archive: ZipFile, name: str, data: bytes) -> None:
    info = ZipInfo(name, FIXED_TIME)
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data, compress_type=ZIP_DEFLATED, compresslevel=9)


submission = SOURCE_INFO.read_text(encoding="utf-8")
required = [
    "스킬 이름: `하다 만 일 종결반 (Laterbill)`",
    "한 줄 설명:",
    "심사·갤러리 설명 본문",
    "https://websarang.github.io/laterbill/",
    "https://github.com/websarang/laterbill",
]
assert all(value in submission for value in required), "submission fields are incomplete"
assert len(submission) <= 20_000, "submission document exceeds 20,000 characters"

with ZipFile(SOURCE_SKILL) as skill_archive:
    names = skill_archive.namelist()
    assert "laterbill/SKILL.md" in names, "inner Skill ZIP is not executable"

with ZipFile(TARGET, "w") as archive:
    add_bytes(archive, "SUBMISSION.md", SOURCE_INFO.read_bytes())
    add_bytes(archive, "laterbill-skill.zip", SOURCE_SKILL.read_bytes())
    add_bytes(archive, "LICENSE", SOURCE_LICENSE.read_bytes())
    for image in sorted(SOURCE_IMAGES.glob("evidence-*.webp")):
        add_bytes(archive, f"evidence/{image.name}", image.read_bytes())

with ZipFile(TARGET) as archive:
    expected = ["SUBMISSION.md", "laterbill-skill.zip", "LICENSE"] + [
        f"evidence/evidence-{number}.webp" for number in range(1, 6)
    ]
    assert archive.namelist() == expected
    assert archive.testzip() is None
    assert all(archive.getinfo(name).file_size > 0 for name in expected)

digest = hashlib.sha256(TARGET.read_bytes()).hexdigest()
print(f"files={len(expected)} compressed={TARGET.stat().st_size}")
print(f"sha256={digest}")
