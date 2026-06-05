#!/usr/bin/env python3
"""Verify that every brain marker box actually lands on its target.

Eyeballing marker placement on a downscaled full-poster overlay hides small
offsets — a box can sit 50 px above its URL text and still look "fine" at that
zoom. This tool checks each marker two ways:

1. **Per-marker zoom crop** — writes ``verify/<n>-<label>.png``: the marker box
   outlined on the brain art at 1:1-ish native resolution, padded so you can see
   whether the box is centered on the icon/text. Open these and look.
2. **Automated ink check** — flags boxes that are mostly over blank tissue
   (``LOW-INK``) or whose nearest ink cluster is offset from the box center
   (``OFFSET``). These are the failure modes that slip past a zoomed-out glance.

Run after editing ``brain_markers`` in poster-content.json::

    python3 verify_markers.py            # all markers
    python3 verify_markers.py origami    # only markers whose label matches

Exit code is non-zero if any marker fails an automated check, so it can gate a
build.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

# Must match build_poster.py's brain placement (poster space).
BRAIN_IMAGE_X = 1300
BRAIN_IMAGE_Y = 455
BRAIN_IMAGE_WIDTH = 2000

HERE = Path(__file__).parent
CONTENT_PATH = HERE / "poster-content.json"
EXAMPLE_CONTENT_PATH = HERE / "poster-content.example.json"
VERIFY_DIR = HERE / "verify"


def resolve_content_path() -> Path:
    """The real content file if present, else the committed example (.env-style)."""
    if CONTENT_PATH.exists():
        return CONTENT_PATH
    if EXAMPLE_CONTENT_PATH.exists():
        return EXAMPLE_CONTENT_PATH
    raise FileNotFoundError(
        f"No content file: expected {CONTENT_PATH.name} or {EXAMPLE_CONTENT_PATH.name}"
    )


INK_LUMA_THRESHOLD = 235  # pixel counts as "ink" (not blank tissue) below this
MIN_INK_FRACTION = 0.04  # icon box covering less ink than this is probably misplaced
MAX_BORDER_INK = 0.32  # icon box with more perimeter ink is likely on a brain stroke
SOLID_ICON_FRACTION = 0.6  # above this fill, high border ink is a solid badge, not a stroke
BLUE_TARGET_MIN_PIXELS = 150  # this much blue nearby => treat marker as a text/URL label
BLUE_MIN_BOX_FRACTION = 0.01  # a text box should contain at least this fraction blue
CENTROID_MARGIN = 0.15  # blue centroid may fall this far outside the box (frac of size)


def load_brain() -> Image.Image:
    """Open the configured brain image as RGB."""
    content = json.loads(resolve_content_path().read_text())
    source = HERE / content["brain_image"]
    if not source.exists():
        raise FileNotFoundError(f"brain_image not found: {source}")
    return Image.open(source).convert("RGB")


def poster_to_native(image: Image.Image) -> float:
    """Return the native-pixels-per-poster-unit scale for ``image``."""
    return image.size[0] / BRAIN_IMAGE_WIDTH  # inverse of BRAIN_IMAGE_WIDTH/native


def is_ink(pixel: Any) -> bool:
    """True if the pixel is drawn content rather than blank white tissue.

    ``pixel`` is an RGB tuple from a converted image; typed loosely because
    Pillow's pixel-access stubs return a broad union.
    """
    return min(pixel[0], pixel[1], pixel[2]) < INK_LUMA_THRESHOLD


def is_blue(pixel: Any) -> bool:
    """True for the royal-blue of the on-art URL/callout labels.

    Matches ``find_brain_links.py`` so the verifier and the detector agree on
    what counts as label text. Black brain outlines and the photo/colored icons
    don't satisfy this, so blue is a clean signal for 'this marker is a label'.
    """
    red, green, blue = pixel[0], pixel[1], pixel[2]
    return blue > 120 and blue - red > 45 and blue - green > 25 and red < 150


def native_box(marker: dict, to_native: float) -> tuple[int, int, int, int]:
    """Convert a poster-space marker to a native-pixel (x0, y0, x1, y1) box."""
    native_x = (marker["x"] - BRAIN_IMAGE_X) * to_native
    native_y = (marker["y"] - BRAIN_IMAGE_Y) * to_native
    width = marker["w"] * to_native
    height = marker["h"] * to_native
    return round(native_x), round(native_y), round(native_x + width), round(native_y + height)


def ink_fraction(image: Image.Image, box: tuple[int, int, int, int]) -> float:
    """Fraction of pixels inside ``box`` that are ink."""
    x0, y0, x1, y1 = box
    region = image.crop((x0, y0, x1, y1))
    pixels = region.load()
    if pixels is None or region.size[0] == 0 or region.size[1] == 0:
        return 0.0
    ink = total = 0
    for y in range(region.size[1]):
        for x in range(region.size[0]):
            total += 1
            if is_ink(pixels[x, y]):
                ink += 1
    return ink / total if total else 0.0


def border_ink_fraction(image: Image.Image, box: tuple[int, int, int, int]) -> float:
    """Fraction of the box's perimeter pixels that are ink.

    A well-placed icon box frames a glyph floating in a white pocket, so its
    border is mostly white. A box that has drifted onto a brain outline has that
    thick black stroke running through it, lighting up the border. This is the
    icon-side analogue of the blue check: it catches the failure where a box
    sits on high-ink brain strokes instead of the icon (which a raw ink-coverage
    number rates as a healthy 'lots of ink' and waves through).
    """
    x0, y0, x1, y1 = box
    region = image.crop((x0, y0, x1, y1))
    pixels = region.load()
    width, height = region.size
    if pixels is None or width < 2 or height < 2:
        return 0.0
    ink = total = 0
    for x in range(width):
        for y in (0, height - 1):
            total += 1
            ink += is_ink(pixels[x, y])
    for y in range(height):
        for x in (0, width - 1):
            total += 1
            ink += is_ink(pixels[x, y])
    return ink / total if total else 0.0


def blue_label_check(
    image: Image.Image, box: tuple[int, int, int, int]
) -> dict[str, Any] | None:
    """Check a marker that overlays blue label text.

    Returns ``None`` when there isn't enough blue near the box to call this a
    text/URL marker (so the caller treats it as an icon and relies on the review
    crop). Otherwise returns the blue coverage inside the box, the blue
    centroid, and whether that centroid lands inside the box (with a small
    margin). Because only the labels are blue, this is immune to the brain's
    black outlines — the noise that defeats a generic ink check.
    """
    x0, y0, x1, y1 = box
    box_w, box_h = max(1, x1 - x0), max(1, y1 - y0)
    # Pad modestly, not by a full box-width: a wide window sweeps in unrelated
    # blue icons (e.g. the recolored team glyph near the tarmar label) and drags
    # the centroid out. Half a box still catches a label that has slid off.
    pad_x, pad_y = round(box_w * 0.5), box_h
    sx0, sy0 = max(0, x0 - pad_x), max(0, y0 - pad_y)
    sx1 = min(image.size[0], x1 + pad_x)
    sy1 = min(image.size[1], y1 + pad_y)
    region = image.crop((sx0, sy0, sx1, sy1))
    pixels = region.load()
    if pixels is None:
        return None
    sum_x = sum_y = nearby = in_box = 0
    for y in range(region.size[1]):
        for x in range(region.size[0]):
            if not is_blue(pixels[x, y]):
                continue
            abs_x, abs_y = sx0 + x, sy0 + y
            nearby += 1
            sum_x += abs_x
            sum_y += abs_y
            if x0 <= abs_x <= x1 and y0 <= abs_y <= y1:
                in_box += 1
    if nearby < BLUE_TARGET_MIN_PIXELS:
        return None
    centroid_x = sum_x / nearby
    centroid_y = sum_y / nearby
    centroid_in_box = (
        x0 - CENTROID_MARGIN * box_w <= centroid_x <= x1 + CENTROID_MARGIN * box_w
        and y0 - CENTROID_MARGIN * box_h <= centroid_y <= y1 + CENTROID_MARGIN * box_h
    )
    return {
        "box_fraction": in_box / (box_w * box_h),
        "centroid": (centroid_x, centroid_y),
        "centroid_in_box": centroid_in_box,
        "captured": in_box / nearby,  # share of nearby blue that lands inside the box
    }


def crop_for_review(image: Image.Image, box: tuple[int, int, int, int], path: Path) -> None:
    """Write a padded, outlined crop of ``box`` for human review."""
    x0, y0, x1, y1 = box
    margin_x = max(60, (x1 - x0))
    margin_y = max(60, (y1 - y0))
    cx0, cy0 = max(0, x0 - margin_x), max(0, y0 - margin_y)
    cx1 = min(image.size[0], x1 + margin_x)
    cy1 = min(image.size[1], y1 + margin_y)
    crop = image.crop((cx0, cy0, cx1, cy1)).copy()
    # Upscale small crops so detail is legible.
    if crop.size[0] < 500:
        factor = 500 // max(1, crop.size[0]) + 1
        crop = crop.resize((crop.size[0] * factor, crop.size[1] * factor))
        scale = factor
    else:
        scale = 1
    draw = ImageDraw.Draw(crop)
    draw.rectangle(
        [(x0 - cx0) * scale, (y0 - cy0) * scale, (x1 - cx0) * scale, (y1 - cy0) * scale],
        outline=(255, 0, 0),
        width=4,
    )
    crop.save(path)


def main(name_filter: str | None) -> int:
    """Verify markers, write review crops, return process exit code."""
    content = json.loads(resolve_content_path().read_text())
    markers = content.get("brain_markers") or content.get("brain_hotspots", [])
    image = load_brain()
    to_native = poster_to_native(image)
    VERIFY_DIR.mkdir(exist_ok=True)
    for old in VERIFY_DIR.glob("*.png"):
        old.unlink()

    failures = 0
    warnings = 0
    print(f"Verifying {len(markers)} markers against {content['brain_image']}\n")
    for index, marker in enumerate(markers):
        label = marker.get("label", marker.get("_label", f"marker-{index}"))
        if name_filter and name_filter.lower() not in label.lower():
            continue
        box = native_box(marker, to_native)
        fraction = ink_fraction(image, box)
        # A marker labelled "URL: ..." overlays blue label text and gets the
        # strict blue check. Everything else is an icon: a blue dashed arrow may
        # wander through its box, so blue would mislead — use ink as an advisory
        # and rely on the review crop for the real confirmation.
        # Hard failures are things we can detect reliably (exit non-zero, gate a
        # build). Warnings need a human glance at the crop — the busy art makes a
        # perfect geometric gate impossible, so we flag and defer, never silently
        # pass. Either way every marker gets a crop.
        hard: list[str] = []
        warn: list[str] = []
        if label.lower().lstrip().startswith(("url", "text")):
            kind = "label"
            blue = blue_label_check(image, box)
            if blue is None:
                detail = "expected blue label text but found almost none nearby"
                hard.append("NO-BLUE(box is nowhere near a URL label)")
            else:
                detail = f"blue in box={blue['box_fraction']:.1%}, {blue['captured']:.0%} of nearby blue captured"
                if not blue["centroid_in_box"]:
                    hard.append("OFFSET(blue text centroid falls outside the box)")
                elif blue["box_fraction"] < BLUE_MIN_BOX_FRACTION:
                    hard.append(f"LOW-BLUE({blue['box_fraction']:.1%} — box barely covers the text)")
        else:
            kind = "icon "
            border = border_ink_fraction(image, box)
            detail = f"ink={fraction:.1%}, border ink={border:.1%}"
            if fraction < MIN_INK_FRACTION:
                hard.append(f"LOW-INK({fraction:.1%} — box may be over blank tissue)")
            # High border ink usually means the box drifted onto a brain stroke —
            # unless the whole box is inked, which is just a solid filled badge
            # (e.g. the README tile) framed correctly.
            if border > MAX_BORDER_INK and fraction < SOLID_ICON_FRACTION:
                warn.append(f"ON-OUTLINE(border ink {border:.0%} — verify the box frames the icon, not a brain stroke)")
        status = "FAIL" if hard else ("warn" if warn else "ok")
        if hard:
            failures += 1
        elif warn:
            warnings += 1
        slug = "".join(c if c.isalnum() else "-" for c in label)[:40].strip("-")
        crop_path = VERIFY_DIR / f"{index:02d}-{slug}.png"
        crop_for_review(image, box, crop_path)
        print(f"  [{status:4}] {kind} {label}")
        print(f"          {detail}  {' '.join(hard + warn)}")
        print(f"          review: {crop_path.relative_to(HERE)}")
    print(
        f"\n{failures} hard failure(s), {warnings} warning(s). "
        f"Always open the verify/ crops — green is not proof of placement."
    )
    return 1 if failures else 0


if __name__ == "__main__":
    argument = sys.argv[1] if len(sys.argv) > 1 else None
    raise SystemExit(main(argument))
