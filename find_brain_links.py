#!/usr/bin/env python3
"""Locate the blue URL labels printed on the brain art.

When you edit the brain image and move its on-art URL callouts, run this to
get fresh ``brain_hotspots`` boxes (in poster space) to paste into
``poster-content.json``::

    python3 find_brain_links.py [brain_image.png]

It detects clusters of blue text pixels and prints a ready-to-edit box for
each. You still label each box with the right href by hand — only you know
which callout is which.
"""

from __future__ import annotations

import collections
import sys
from pathlib import Path

from PIL import Image

# Must match build_poster.py's brain placement.
BRAIN_IMAGE_X = 1300
BRAIN_IMAGE_Y = 455
BRAIN_IMAGE_WIDTH = 2000


def is_blue(red: int, green: int, blue: int) -> bool:
    """True for the royal-blue used by the brain's URL labels."""
    return blue > 120 and blue - red > 45 and blue - green > 25 and red < 150


def main(path: Path) -> None:
    """Detect blue label clusters and print poster-space boxes."""
    image = Image.open(path).convert("RGB")
    width, height = image.size
    pixels = image.load()
    if pixels is None:
        raise RuntimeError(f"could not read pixels from {path}")
    scale = BRAIN_IMAGE_WIDTH / width
    grid = 40

    cells: dict[tuple[int, int], int] = collections.defaultdict(int)
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            pixel = pixels[x, y]
            if isinstance(pixel, tuple) and is_blue(pixel[0], pixel[1], pixel[2]):
                cells[(x // grid, y // grid)] += 1

    populated = {cell for cell, count in cells.items() if count >= 3}
    seen: set[tuple[int, int]] = set()
    print(f"# {path.name}  ({width}x{height})  — paste into brain_hotspots, fix _label/href:")
    for cell in list(populated):
        if cell in seen:
            continue
        stack = [cell]
        component = []
        while stack:
            node = stack.pop()
            if node in seen or node not in populated:
                continue
            seen.add(node)
            component.append(node)
            cx, cy = node
            stack += [(cx + dx, cy + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
        xs = [c[0] for c in component]
        ys = [c[1] for c in component]
        nx0, ny0 = min(xs) * grid, min(ys) * grid
        nx1, ny1 = (max(xs) + 1) * grid, (max(ys) + 1) * grid
        if (nx1 - nx0) * (ny1 - ny0) < 8000:
            continue
        box = {
            "_label": "FIXME — which callout?",
            "href": "https://FIXME",
            "x": round(BRAIN_IMAGE_X + nx0 * scale),
            "y": round(BRAIN_IMAGE_Y + ny0 * scale),
            "w": round((nx1 - nx0) * scale),
            "h": round((ny1 - ny0) * scale),
        }
        print(
            f'    {{ "_label": "{box["_label"]}", "href": "{box["href"]}", '
            f'"x": {box["x"]}, "y": {box["y"]}, "w": {box["w"]}, "h": {box["h"]} }},'
        )


if __name__ == "__main__":
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("Untitled_Artwork.png")
    main(source)
