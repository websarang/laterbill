#!/usr/bin/env python3
"""Convert deterministic evidence screenshots to compact WebP files."""

from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "assets" / "evidence"

for png in sorted(EVIDENCE.glob("evidence-*.png")):
    target = png.with_suffix(".webp")
    with Image.open(png) as image:
        image.save(target, "WEBP", quality=88, method=6)
    print(f"{target.name}: {target.stat().st_size:,} bytes")
