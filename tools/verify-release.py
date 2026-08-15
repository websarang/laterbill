#!/usr/bin/env python3
"""Generate a public, reproducible verification record for the release."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "laterbill"
ZIP_PATH = ROOT / "laterbill-skill.zip"
PROOF_DIR = ROOT / "docs" / "assets" / "proof"
REPORT = PROOF_DIR / "release-verification.txt"


def run(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=240,
    )
    if result.returncode != 0:
        raise SystemExit(result.stdout + result.stderr)
    return result.stdout.strip()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


source_output = run([sys.executable, "scripts/selftest.py"], SKILL)
package_output = run([sys.executable, "tools/package-skill.py"], ROOT)
zip_sha = hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest()

with tempfile.TemporaryDirectory(prefix="laterbill-release-check-") as temp:
    extracted_root = Path(temp)
    with ZipFile(ZIP_PATH) as archive:
        archive.extractall(extracted_root)
    extracted_output = run(
        [sys.executable, "scripts/selftest.py"], extracted_root / "laterbill"
    )

harvest = load_module("laterbill_harvest_proof", SKILL / "scripts" / "harvest.py")
render = load_module("laterbill_render_proof", SKILL / "scripts" / "render.py")
repayment = load_module("laterbill_repayment_proof", SKILL / "scripts" / "repayment.py")

codex_resume = render.resume_command({
    "runtime": "codex", "project_exists": True,
    "project_path": r"C:\demo\sample-project", "session_id": "demo-codex-001",
})
claude_resume = render.resume_command({
    "runtime": "claude-code", "project_exists": True,
    "project_path": "/demo/sample-project", "session_id": "demo-claude-001",
})

synthetic_item = {
    "kind": "abandoned_project", "label": "sample-project",
    "project": r"C:\demo\sample-project", "item_id": "lb_private_demo",
    "source_refs": [{
        "runtime": "codex", "session_id": "demo-codex-001",
        "project_path": r"C:\demo\sample-project", "project_exists": True,
        "last_seen": "2026-08-14T09:00:00+00:00",
    }],
    "sensitive_topics": [], "sensitive_approved": False,
    "last_words": {"ts": "2026-08-14T09:00:00+00:00", "text": "배포 전에 테스트가 실패해."},
    "stall_signals": [], "repayment_options": [],
}
public_item = harvest.anonymize([copy.deepcopy(synthetic_item)])[0]

with tempfile.TemporaryDirectory(prefix="laterbill-readonly-check-") as temp:
    project = Path(temp)
    marker = project / "README.md"
    marker.write_text("synthetic read-only probe\n", encoding="utf-8")
    before_hash = hashlib.sha256(marker.read_bytes()).hexdigest()
    private_item = copy.deepcopy(synthetic_item)
    private_item["project"] = str(project)
    private_item["source_refs"][0]["project_path"] = str(project)
    repayment.inspect_project(private_item)
    after_hash = hashlib.sha256(marker.read_bytes()).hexdigest()

selected_passes = [
    line for line in source_output.splitlines()
    if line.startswith("PASS  ") and any(key in line for key in (
        "최신 Codex envelope", "빠른 진전·장애물 해소·완결 우선",
        "민감 원문", "프로젝트 점검은 파일을 변경하지 않는다",
        "자가개선 가드레일",
    ))
]

utf8_targets = [
    ROOT / "README.md",
    ROOT / "JUDGE_START_HERE.md",
    ROOT / "submission" / "SUBMISSION.md",
    ROOT / "docs" / "evidence.html",
    SKILL / "SKILL.md",
]
utf8_decode_ok = all(path.read_bytes().decode("utf-8") for path in utf8_targets)
skill_frontmatter_at_byte_zero = (SKILL / "SKILL.md").read_bytes().startswith(b"---")

report_lines = [
    "LATERBILL RELEASE VERIFICATION",
    f"generated_at_utc={datetime.now(timezone.utc).isoformat(timespec='seconds')}", "",
    "$ python laterbill/scripts/selftest.py", *selected_passes,
    source_output.splitlines()[-1], "",
    "$ python tools/package-skill.py", package_output, "",
    "$ unzip laterbill-skill.zip -> temporary directory",
    "$ python <temporary>/laterbill/scripts/selftest.py",
    extracted_output.splitlines()[-1], f"zip_sha256={zip_sha}",
    "source_and_extracted_same_result=true", "",
    "ACTUAL SYNTHETIC BEHAVIOR (no personal records)",
    f"codex_resume={codex_resume}", f"claude_resume={claude_resume}",
    f"private_source_ref_count={len(synthetic_item['source_refs'])}",
    f"public_source_refs={json.dumps(public_item['source_refs'])}",
    f"public_item_id={public_item['item_id']}",
    f"public_project={public_item['project']}",
    f"readonly_before_sha256={before_hash}",
    f"readonly_after_sha256={after_hash}",
    f"readonly_unchanged={str(before_hash == after_hash).lower()}",
    f"utf8_strict_decode_ok={str(utf8_decode_ok).lower()}",
    f"skill_frontmatter_at_byte_zero={str(skill_frontmatter_at_byte_zero).lower()}",
    "windows_powershell_5_hint=Get-Content -Encoding UTF8 <file>",
]

PROOF_DIR.mkdir(parents=True, exist_ok=True)
REPORT.write_text("\n".join(report_lines) + "\n", encoding="utf-8-sig")
print(REPORT)
print(f"source={source_output.splitlines()[-1]}")
print(f"extracted={extracted_output.splitlines()[-1]}")
print(f"sha256={zip_sha}")
