#!/usr/bin/env python3
"""Create secondary pixel-diff evidence for the 16:9 reference adaptation."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "docs" / "assets" / "evidence" / "evidence-3.png"
GENERATED = ROOT / "docs" / "assets" / "presentation" / "slide-06.png"
ARTIFACTS = ROOT / ".omx" / "artifacts" / "visual-ralph" / "laterbill-presentation"

ARTIFACTS.mkdir(parents=True, exist_ok=True)
reference = Image.open(REFERENCE).convert("RGB").resize((1920, 1080))
generated = Image.open(GENERATED).convert("RGB")
difference = ImageChops.difference(reference, generated)
difference.save(ARTIFACTS / "pixel-diff-slide-06.png")

mean = sum(ImageStat.Stat(difference).mean) / 3
result = {
    "reference": str(REFERENCE.relative_to(ROOT)),
    "generated": str(GENERATED.relative_to(ROOT)),
    "normalized_dimensions": "1920x1080",
    "mean_absolute_rgb_difference": round(mean, 2),
    "interpretation": "Secondary debug evidence only; the approved 3:2 evidence board was intentionally re-composed as a 16:9 presentation slide.",
}
(ARTIFACTS / "pixel-diff-slide-06.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(result, ensure_ascii=False))
