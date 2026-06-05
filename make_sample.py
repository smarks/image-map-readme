#!/usr/bin/env python3
"""Generate the demo pair: ``sample-brain.png`` + ``poster-content.example.json``.

The brain art and its marker boxes are a matched pair — every marker coordinate
is relative to one specific image, so you can't template the image alone. This
script draws a generic placeholder "brain" with a few labeled icons and one
on-art URL label, then writes the example content file with markers at the exact
coordinates it just drew. Because one script owns both, the demo's boxes are
correct *by construction* — no measuring, no drift.

It's also living documentation of the whole technique: this is how a poster-space
box maps onto the art. Run it whenever you change the sample::

    python3 make_sample.py
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
SAMPLE_IMAGE = HERE / "sample-brain.png"
EXAMPLE_CONTENT = HERE / "poster-content.example.json"

# Must match build_poster.py's brain placement (poster space).
BRAIN_IMAGE_X = 1300
BRAIN_IMAGE_Y = 455
BRAIN_IMAGE_WIDTH = 2000

NATIVE_WIDTH, NATIVE_HEIGHT = 1600, 1200
SCALE = BRAIN_IMAGE_WIDTH / NATIVE_WIDTH  # native pixels -> poster units

INK = "#1F2433"
ROYAL_BLUE = "#2D6CDF"  # the URL-label color build/verify look for

FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
)


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Return a truetype font at ``size`` px, or PIL's default."""
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def box_to_poster(native_x: float, native_y: float, native_w: float, native_h: float) -> dict[str, int]:
    """Convert a native-pixel box to a poster-space x/y/w/h dict."""
    return {
        "x": round(BRAIN_IMAGE_X + native_x * SCALE),
        "y": round(BRAIN_IMAGE_Y + native_y * SCALE),
        "w": round(native_w * SCALE),
        "h": round(native_h * SCALE),
    }


def draw_sample() -> list[dict]:
    """Draw the placeholder brain and return markers matching what was drawn."""
    image = Image.new("RGB", (NATIVE_WIDTH, NATIVE_HEIGHT), "white")
    draw = ImageDraw.Draw(image)

    # A simple brain-ish silhouette: two overlapping hemispheres + a center fold.
    draw.ellipse([170, 210, 950, 1010], outline=INK, width=16)
    draw.ellipse([650, 210, 1430, 1010], outline=INK, width=16)
    draw.line([(800, 250), (800, 970)], fill=INK, width=10)
    draw.arc([520, 360, 880, 720], start=200, end=20, fill=INK, width=8)
    draw.arc([720, 520, 1080, 880], start=160, end=340, fill=INK, width=8)

    markers: list[dict] = []
    pad = 14  # breathing room so the hover box clears the glyph

    # 1) Blue circle — tooltip only.
    cx, cy, radius = 540, 560, 78
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=ROYAL_BLUE)
    markers.append(
        {
            "label": "Icon: blue circle (demo)",
            "tooltip": "Hover an icon to show its tooltip. This one is tooltip-only.",
            **box_to_poster(cx - radius - pad, cy - radius - pad, 2 * (radius + pad), 2 * (radius + pad)),
        }
    )

    # 2) Orange square — tooltip AND a click-through link.
    sx, sy, half = 840, 540, 74
    draw.rounded_rectangle([sx - half, sy - half, sx + half, sy + half], radius=18, fill="#F2A007")
    markers.append(
        {
            "label": "Icon: orange square (demo)",
            "href": "https://example.com",
            "tooltip": "A marker can do both: hover shows this text, click opens the link.",
            **box_to_poster(sx - half - pad, sy - half - pad, 2 * (half + pad), 2 * (half + pad)),
        }
    )

    # 3) Green triangle — tooltip only.
    tx, ty, size = 1120, 580, 88
    draw.polygon([(tx, ty - size), (tx - size, ty + size), (tx + size, ty + size)], fill="#27A66B")
    markers.append(
        {
            "label": "Icon: green triangle (demo)",
            "tooltip": "Replace these placeholders with your own icons and notes.",
            **box_to_poster(tx - size - pad, ty - size + 4, 2 * (size + pad), 2 * size),
        }
    )

    # 4) On-art URL label in royal blue — becomes a clickable link.
    label = "example.com"
    url_font = load_font(58)
    label_x, label_y = 470, 840
    draw.text((label_x, label_y), label, fill=ROYAL_BLUE, font=url_font)
    left, top, right, bottom = draw.textbbox((label_x, label_y), label, font=url_font)
    markers.append(
        {
            "label": "URL: example.com (on-art label)",
            "href": "https://example.com",
            "tooltip": "Text labels printed on the art can be clickable links too.",
            **box_to_poster(left - pad, top - pad, (right - left) + 2 * pad, (bottom - top) + 2 * pad),
        }
    )

    image.save(SAMPLE_IMAGE)
    return markers


def example_content(markers: list[dict]) -> dict:
    """Assemble a complete, generic example content file around the markers."""
    return {
        "_README": [
            "EXAMPLE / TEMPLATE — this renders the demo poster when no real",
            "poster-content.json is present (the .env-style fallback).",
            "Copy this to poster-content.json, point brain_image at your own art,",
            "place your own brain_markers, and rewrite the text. Your real file is",
            "git-ignored and never committed; this example is the public template.",
        ],
        "brain_image": "sample-brain.png",
        "title": "Your README",
        "subtitle": "A quick guide to who you are and how you like to work.",
        "tagline": "grab and drag to explore · the links are live",
        "brain_caption": "Your art goes here — hover the icons, click the links.",
        "left_column": [
            {
                "key": "energizes",
                "title": "What energizes me",
                "icon": "lightning",
                "color": "#F2A007",
                "bullets": [
                    "Something that gets you out of bed",
                    "A kind of problem you love",
                    "A way of working that suits you — [a link works too](https://example.com)",
                ],
            },
            {
                "key": "struggle",
                "title": "I struggle with",
                "icon": "squiggle",
                "color": "#6A4FD0",
                "bullets": ["Be honest here", "It builds trust"],
            },
            {
                "key": "work",
                "title": "Work with me",
                "icon": "twocircles",
                "color": "#27A66B",
                "bullets": ["How to get the best from you", "What you need from others"],
                "note": "A short italic note can sit under a card.",
            },
        ],
        "right_column": [
            {
                "key": "grumpy",
                "title": "What makes me grumpy",
                "icon": "x",
                "color": "#E0474B",
                "bullets": ["The small things that drain you", "Name them kindly"],
                "note": "\"A motto or aside lives here.\"",
            },
            {
                "key": "feedback",
                "title": "How I like feedback",
                "icon": "bubble",
                "color": "#2D6CDF",
                "bullets": ["Direct and specific", "Tied to a real example"],
            },
            {
                "key": "likes",
                "title": "A few things I like",
                "icon": "heart",
                "color": "#F2547D",
                "bullets": ["Hobbies", "Books, games, the outdoors — whatever's you"],
            },
        ],
        "about": {
            "key": "about",
            "title": "About me",
            "icon": "person",
            "color": "#0F5E86",
            "bullets": ["Where you live", "The shape of your career", "Anything else worth knowing"],
            "note": "This is a work in progress.",
        },
        "quotes": {
            "title": "Words that resonate",
            "bg": "#2E2A5A",
            "items": [
                {"text": "A line that means something to you.", "by": "Someone"},
                {"text": "Another, shorter.", "by": ""},
            ],
        },
        "links": {
            "title": "Find me online",
            "icon": "globe",
            "color": "#6A4FD0",
            "buttons": [
                {"label": "Your site — example.com", "href": "https://example.com"},
                {"label": "Another profile", "href": "https://example.com"},
            ],
        },
        "_brain_markers_README": [
            "These boxes were generated by make_sample.py to match sample-brain.png.",
            "Each may carry a 'tooltip' (hover) and/or 'href' (click). Coordinates are",
            "in poster space. Run 'just verify' to review box placement against the art.",
        ],
        "brain_markers": markers,
    }


def main() -> None:
    """Generate the sample image and its matching example content file."""
    markers = draw_sample()
    EXAMPLE_CONTENT.write_text(
        json.dumps(example_content(markers), indent=2, ensure_ascii=False) + "\n"
    )
    print(f"• Wrote {SAMPLE_IMAGE.name} ({NATIVE_WIDTH}x{NATIVE_HEIGHT})")
    print(f"• Wrote {EXAMPLE_CONTENT.name} with {len(markers)} markers matching it")


if __name__ == "__main__":
    main()
