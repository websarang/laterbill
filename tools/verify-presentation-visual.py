#!/usr/bin/env python3
"""Verify that every exported PNG contains the persistent brand regions."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets" / "presentation"
BADGE = (1590, 15, 1890, 135)
FOOTER = (85, 985, 610, 1065)


def color_counts(image: Image.Image, bounds: tuple[int, int, int, int]) -> tuple[int, int]:
    dark = 0
    red = 0
    for r, g, b in image.crop(bounds).get_flattened_data():
        dark += r < 70 and g < 85 and b < 90
        red += r > 150 and r > g * 1.25 and r > b * 1.25
    return dark, red


pngs = sorted(ASSETS.glob("slide-*.png"))
assert len(pngs) == 10, f"expected 10 PNGs, got {len(pngs)}"

for path in pngs:
    image = Image.open(path).convert("RGB")
    badge_dark, badge_red = color_counts(image, BADGE)
    footer_dark, footer_red = color_counts(image, FOOTER)
    assert badge_dark > 2_000 and badge_red > 2_000, (
        f"ACE badge missing or incomplete: {path.name} dark={badge_dark} red={badge_red}"
    )
    assert footer_dark > 1_000 and footer_red > 500, (
        f"Laterbill footer missing or incomplete: {path.name} dark={footer_dark} red={footer_red}"
    )

print("presentation_png_ace_badges=10/10")
print("presentation_png_brand_footers=10/10")
print("presentation_visual_regions=PASS")
