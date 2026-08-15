#!/usr/bin/env python3
"""Verify the local presentation contract without third-party dependencies."""

from __future__ import annotations

import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "docs" / "presentation" / "index.html"
CSS = ROOT / "docs" / "presentation" / "presentation.css"
JS = ROOT / "docs" / "presentation" / "presentation.js"
ASSETS = ROOT / "docs" / "assets" / "presentation"


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n"), f"not PNG: {path.name}"
    return struct.unpack(">II", data[16:24])


html = HTML.read_text(encoding="utf-8")
css = CSS.read_text(encoding="utf-8")
js = JS.read_text(encoding="utf-8")
slides = re.findall(r'data-slide="(\d+)"', html)
assert slides == [str(i) for i in range(1, 11)], slides
assert "1920px" in css and "1080px" in css
assert all(key in js for key in ("ArrowRight", "ArrowLeft", "Home", "End", "PageDown"))
assert all(key in html for key in ("data-page-input", "data-nav-form", "ace-coach.png", "하다 만 일 종결반"))
assert all(key in js for key in ("pageInput.value", "navForm.addEventListener('submit'", "pageInput.addEventListener('change'"))
assert all(key in js for key in ("navSafeSpace", "deckLeft", "captureMode"))
assert '<span class="ace-name">에이스 / 최학곤</span>' in html
assert "class=\"ace-full\"" in html
assert "Coach</small>" not in html and ">ACE</b>" not in html
assert all(key in html for key in ("HOW TO USE · ACTUAL RUN", "ACTUAL RUN · ITEM 02", "SYNTHETIC FIXTURE", "actual-demo.html"))
assert "SYNTHETIC FIXTURE" in html
assert all(key in html for key in ("/laterbill", "텍스트 청구서 표시", "HTML 청구서 열기", "2번 → C안 → 승인"))
assert all(key in html for key in ("/laterbill 수동", "청구서 발행", "탕감</b> 실행 0"))
assert "914턴 → 미납 6건" in html
assert "35/35 × 2" in html and "<dd>70</dd>" in html

private_patterns = [r"C:\\Users\\", r"/Users/", r"\.codex[/\\]sessions", r"session_meta"]
for pattern in private_patterns:
    assert not re.search(pattern, html, re.I), f"private pattern in HTML: {pattern}"

pngs = sorted(ASSETS.glob("slide-*.png"))
assert len(pngs) == 10, f"expected 10 PNGs, got {len(pngs)}"
assert all(png_size(path) == (1920, 1080) for path in pngs)
assert sum(path.stat().st_size for path in pngs) <= 12_000_000
assert (ASSETS / "ace-coach.png").is_file()

print("presentation_slides=10")
print("presentation_pngs=10")
print("presentation_dimensions=1920x1080")
print("presentation_private_patterns=0")
print("presentation_direct_navigation=PASS")
print("presentation_brand_badge=PASS")
print("presentation_verification=PASS")
