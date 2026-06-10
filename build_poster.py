#!/usr/bin/env python3
"""Build Spencer's brain-map README poster from poster-content.json.

Reads the editable content file plus a brain image and regenerates three
artifacts:

* ``spencer-brain-poster.svg``  — vector poster (references ``brain-web.png``)
* ``spencer-brain-poster.html`` — self-contained pan/zoom page for the web
* ``spencer-brain-poster.png``  — flat preview (only if Chrome is found)

Text auto-reflows, so editing ``poster-content.json`` is all you need: add,
remove, or reword bullets and re-run ``python3 build_poster.py``.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
import time
import traceback
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageFont

# Data (content, brain image, outputs) is resolved against the CURRENT directory,
# not the engine's own folder — so this engine can live in one repo and build a
# content folder in another (run it from the content dir). The engine ships no
# data of its own beyond the example demo that sits in its repo.
PROJECT = Path.cwd()
CONTENT_PATH = PROJECT / "poster-content.json"
EXAMPLE_CONTENT_PATH = PROJECT / "poster-content.example.json"
WEB_BRAIN = PROJECT / "brain-web.png"
SVG_OUT = PROJECT / "spencer-brain-poster.svg"
HTML_OUT = PROJECT / "spencer-brain-poster.html"
PNG_OUT = PROJECT / "spencer-brain-poster.png"
PDF_OUT = PROJECT / "spencer-brain-poster.pdf"
PRINT_DIR = PROJECT / "print"

# ── Canvas geometry (poster space) ──────────────────────────────────────────
CANVAS_WIDTH = 4600
COLUMN_WIDTH = 1000
LEFT_COLUMN_X = 70
RIGHT_COLUMN_X = 3530
# BRAIN_IMAGE_* is the *authoring frame* the brain markers were placed against.
# The brain is drawn larger and vertically centred at build time; markers are
# transformed by the same scale+offset (see build_svg / render_markers) so they
# stay glued to the art. Edit marker coordinates against this frame, not the
# displayed size.
BRAIN_IMAGE_X = 1300
BRAIN_IMAGE_Y = 455
BRAIN_IMAGE_WIDTH = 2000
# How wide the brain is actually drawn. Bounded by the gap between the side
# columns (RIGHT_COLUMN_X − (LEFT_COLUMN_X+COLUMN_WIDTH) = 2460) with a margin.
BRAIN_DISPLAY_WIDTH = 2300
BRAIN_NATIVE_WIDTH = 2752  # used only as a fallback aspect ratio
BRAIN_NATIVE_HEIGHT = 2064
COLUMN_TOP = 400
COLUMN_GAP = 30
CARD_PADDING = 46
ICON_BAR_GAP = 18  # extra inset so the header icon clears the colored accent bar
BULLET_INDENT = 40
BULLET_SIZE = 40
BULLET_LINE_HEIGHT = 68
BULLET_GAP = 10
QUOTE_SIZE = 44
QUOTE_LINE_HEIGHT = 62
BUTTON_HEIGHT = 104
BUTTON_GAP = 16

# Collapsible (disclosure) cards: a collapsed card shrinks to just its header
# pill; its full slot stays reserved so expanding never overlaps a neighbour.
COLLAPSED_HEIGHT = 120
# Disclosure triangle, drawn in local coords and positioned with translate() so
# the JS toggle only has to swap the points. Down = expanded, right = collapsed.
TRI_DOWN = "-18,-11 18,-11 0,15"
TRI_RIGHT = "-11,-18 -11,18 15,0"

# GitHub "Octocat" mark, drawn on a 16×16 grid (scaled where used).
OCTOCAT_PATH = (
    "M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 "
    "0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13"
    "-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66"
    ".07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15"
    "-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 "
    "1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 "
    "1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 "
    "1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"
)

# The poster font ships WITH the engine (not the content dir): the same files are
# used to MEASURE text here and are embedded into the page via @font-face below,
# so the browser renders with identical metrics on every device and card text
# always fits. PosterSans is Liberation Sans, subset + renamed (fonts/NOTICE.md).
ENGINE_DIR = Path(__file__).resolve().parent
FONT_DIR = ENGINE_DIR / "fonts"
EMBED_FAMILY = "PosterSans"
EMBEDDED_FONTS = (
    (400, "normal", "PosterSans-Regular.ttf"),
    (700, "normal", "PosterSans-Bold.ttf"),
    (400, "italic", "PosterSans-Italic.ttf"),
)

FONT_CANDIDATES = (
    # The embedded font first: measured here == rendered in the browser. The
    # system fonts are only a safety net if the bundled file ever goes missing.
    str(FONT_DIR / "PosterSans-Regular.ttf"),
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

_font_cache: dict[int, ImageFont.FreeTypeFont | None] = {}


def resolve_content_path() -> Path:
    """Pick the content file: the real one if present, else the example.

    ``poster-content.json`` is treated like a ``.env`` — it holds the real,
    personal content and is git-ignored. When it's absent (e.g. a fresh public
    clone), fall back to the committed ``poster-content.example.json`` so the
    project still builds a working demo out of the box.
    """
    if CONTENT_PATH.exists():
        return CONTENT_PATH
    if EXAMPLE_CONTENT_PATH.exists():
        print(f"• {CONTENT_PATH.name} not found — building the example demo.")
        return EXAMPLE_CONTENT_PATH
    raise FileNotFoundError(
        f"No content file: expected {CONTENT_PATH.name} or {EXAMPLE_CONTENT_PATH.name}"
    )


def get_font(size: int) -> ImageFont.FreeTypeFont | None:
    """Return a PIL font at ``size`` px for text measurement, or None."""
    if size not in _font_cache:
        chosen = None
        for candidate in FONT_CANDIDATES:
            if Path(candidate).exists():
                try:
                    chosen = ImageFont.truetype(candidate, size)
                    break
                except OSError:
                    continue
        _font_cache[size] = chosen
    return _font_cache[size]


def embedded_font_faces() -> str:
    """Return @font-face CSS embedding the poster font as base64 data URLs.

    The page renders with the exact files :func:`text_width` measures with, so
    wrapped lines are the same width in the browser as they were measured and
    card text cannot spill its box — independent of the viewer's installed fonts.
    """
    faces = []
    for weight, style, filename in EMBEDDED_FONTS:
        encoded = base64.b64encode((FONT_DIR / filename).read_bytes()).decode("ascii")
        faces.append(
            f"@font-face{{font-family:'{EMBED_FAMILY}';font-style:{style};"
            f"font-weight:{weight};font-display:swap;"
            f"src:url(data:font/ttf;base64,{encoded}) format('truetype');}}"
        )
    return "\n".join(faces)


def text_width(text: str, size: int) -> float:
    """Measure rendered width of ``text`` at ``size`` px."""
    font = get_font(size)
    if font is not None:
        return font.getlength(text)
    return len(text) * size * 0.52  # rough fallback


def escape(text: str) -> str:
    """Escape text for inclusion in XML content or attributes."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ── Inline-link aware tokenizing + wrapping ─────────────────────────────────
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def tokenize(text: str) -> list[tuple[str, str | None]]:
    """Split ``text`` into (word, href|None) tokens, honoring [label](url)."""
    tokens: list[tuple[str, str | None]] = []
    position = 0
    for match in LINK_RE.finditer(text):
        for word in text[position : match.start()].split(" "):
            if word:
                tokens.append((word, None))
        href = match.group(2)
        for word in match.group(1).split(" "):
            if word:
                tokens.append((word, href))
        position = match.end()
    for word in text[position:].split(" "):
        if word:
            tokens.append((word, None))
    return tokens


def wrap_tokens(
    tokens: list[tuple[str, str | None]], max_width: float, size: int
) -> list[list[tuple[str, str | None]]]:
    """Greedily wrap tokens into lines that fit ``max_width``."""
    lines: list[list[tuple[str, str | None]]] = []
    current: list[tuple[str, str | None]] = []
    for token in tokens:
        trial = current + [token]
        words = " ".join(word for word, _ in trial)
        if not current or text_width(words, size) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = [token]
    if current:
        lines.append(current)
    return lines


def render_line(
    line: list[tuple[str, str | None]],
    x: int,
    y: int,
    css_class: str,
    fill: str,
    leader: str = "",
) -> str:
    """Render one wrapped line as an SVG <text>, grouping link runs."""
    segments: list[list] = []
    for word, href in line:
        if segments and segments[-1][0] == href:
            segments[-1][1].append(word)
        else:
            segments.append([href, [word]])

    inner = f"<tspan>{escape(leader)}</tspan>" if leader else ""
    for index, (href, words) in enumerate(segments):
        spacer = "" if index == 0 and not leader else " "
        chunk = escape(spacer + " ".join(words))
        if href:
            inner += (
                f'<a href="{escape(href)}" target="_blank">'
                f'<tspan class="lnk">{chunk}</tspan></a>'
            )
        else:
            inner += f"<tspan>{chunk}</tspan>"
    return f'<text x="{x}" y="{y}" class="{css_class}" fill="{fill}">{inner}</text>'


# ── Icon glyphs (centered on cx, cy) ────────────────────────────────────────
def icon(name: str, cx: int, cy: int, color: str) -> str:
    """Return SVG markup for a named header icon."""
    disc = f'<circle cx="{cx}" cy="{cy}" r="30" fill="{color}"/>'
    white = "#FFFFFF"
    if name == "lightning":
        pts = f"{cx+6},{cy-22} {cx-18},{cy+6} {cx-2},{cy+6} {cx-10},{cy+26} {cx+14},{cy-4} {cx+2},{cy-4}"
        return disc + f'<polygon points="{pts}" fill="{white}"/>'
    if name == "squiggle":
        path = (
            f"M {cx-16},{cy} C {cx-16},{cy-14} {cx+2},{cy-14} {cx+2},{cy} "
            f"C {cx+2},{cy+14} {cx+16},{cy+14} {cx+16},{cy}"
        )
        return disc + f'<path d="{path}" fill="none" stroke="{white}" stroke-width="6" stroke-linecap="round"/>'
    if name == "twocircles":
        return (
            disc
            + f'<g fill="none" stroke="{white}" stroke-width="6">'
            f'<circle cx="{cx-8}" cy="{cy}" r="11"/><circle cx="{cx+8}" cy="{cy}" r="11"/></g>'
        )
    if name == "x":
        return (
            disc
            + f'<g stroke="{white}" stroke-width="6" stroke-linecap="round">'
            f'<line x1="{cx-12}" y1="{cy-12}" x2="{cx+12}" y2="{cy+12}"/>'
            f'<line x1="{cx+12}" y1="{cy-12}" x2="{cx-12}" y2="{cy+12}"/></g>'
        )
    if name == "bubble":
        return (
            disc
            + f'<rect x="{cx-16}" y="{cy-13}" width="32" height="21" rx="6" fill="{white}"/>'
            f'<polygon points="{cx-6},{cy+6} {cx-6},{cy+16} {cx+4},{cy+6}" fill="{white}"/>'
        )
    if name == "heart":
        path = (
            f"M {cx},{cy-10} c -10,-12 -30,-12 -30,6 c 0,16 30,32 30,32 "
            f"c 0,0 30,-16 30,-32 c 0,-18 -20,-18 -30,-6 z"
        )
        return f'<path d="{path}" fill="{color}"/>'
    if name == "person":
        return (
            disc
            + f'<circle cx="{cx}" cy="{cy-10}" r="9" fill="{white}"/>'
            f'<path d="M {cx-20},{cy+16} a 20 16 0 0 1 40 0 z" fill="{white}"/>'
        )
    if name == "globe":
        return (
            disc
            + f'<g fill="none" stroke="{white}" stroke-width="5">'
            f'<circle cx="{cx}" cy="{cy}" r="18"/>'
            f'<ellipse cx="{cx}" cy="{cy}" rx="8" ry="18"/>'
            f'<line x1="{cx-18}" y1="{cy}" x2="{cx+18}" y2="{cy}"/></g>'
        )
    return disc


# ── Card renderers ──────────────────────────────────────────────────────────
def disclosure_triangle(cx: int, cy: int, collapsed: bool) -> str:
    """A small disclosure triangle (▼ open / ► closed) the JS can flip."""
    points = TRI_RIGHT if collapsed else TRI_DOWN
    return f'<polygon class="ctri" points="{points}" transform="translate({cx},{cy})" fill="#1F2433"/>'


def card_divider(x: int, y: int, width: int) -> str:
    """The header rule under a card title (lives in the collapsible body)."""
    return (
        f'<line x1="{x+CARD_PADDING}" y1="{y+112}" x2="{x+width-CARD_PADDING}" y2="{y+112}" '
        f'stroke="#E2E5EE" stroke-width="3"/>'
    )


def card_header(card: dict, x: int, y: int, collapsed: bool = False) -> str:
    """Render a card's disclosure triangle, icon, and title (no divider)."""
    # Triangle at the far left, then the icon inset past the accent bar, then title.
    tri_cx, tri_cy = x + CARD_PADDING + ICON_BAR_GAP + 8, y + 60
    cx, cy = x + CARD_PADDING + ICON_BAR_GAP + 60, y + 62
    title_x = cx + 54
    return (
        disclosure_triangle(tri_cx, tri_cy, collapsed)
        + icon(card["icon"], cx, cy, card["color"])
        + f'<text x="{title_x}" y="{y+78}" class="cardh" fill="#1F2433">{escape(card["title"])}</text>'
    )


def collapsible(
    x: int,
    y: int,
    width: int,
    full_height: int,
    accent: str,
    header: str,
    body: str,
    accent_side: str = "left",
    bg: str = "#FFFFFF",
    collapsed: bool = False,
    column: bool = False,
) -> str:
    """Wrap a card's header + body so it can collapse to a header-only pill.

    Always rendered fully expanded so the static SVG/PNG/PDF exports show every
    card's content. ``collapsed`` only tags the card with ``data-start-collapsed``
    so the interactive page's JS can fold it on load; the slot reserves
    ``full_height`` regardless, so an expanding card never overlaps a neighbour.
    """
    bar_x = x if accent_side == "left" else x + width - 16
    start_collapsed = ' data-start-collapsed="1"' if collapsed else ""
    # transparent hit target over just the header row
    toggle = (
        f'<rect class="ctoggle" x="{x}" y="{y}" width="{width}" '
        f'height="{COLLAPSED_HEIGHT}" fill="#000" fill-opacity="0"/>'
    )
    # column cards reflow as a stack in the interactive page (data-y = baked top)
    classes = "card colcard" if column else "card"
    col_attr = f' data-y="{y}"' if column else ""
    # accent="" → no stripe (the brain card stands on its border + shadow alone)
    bar = (
        f'<rect class="cbar" x="{bar_x}" y="{y}" width="16" height="{full_height}" rx="8" fill="{accent}"/>'
        if accent else ""
    )
    return (
        f'<g class="{classes}" data-eh="{full_height}"{col_attr}{start_collapsed}>'
        f'<rect class="cbg" x="{x}" y="{y}" width="{width}" height="{full_height}" rx="26" '
        f'fill="{bg}" stroke="#E4E7EC" stroke-width="2" filter="url(#shadow)"/>'
        f'{bar}'
        f'<g class="cbody" display="inline">{body}</g>'
        f"{header}{toggle}</g>"
    )


def layout_card(
    card: dict,
    x: int,
    y: int,
    width: int,
    dark: bool = False,
    min_height: int = 0,
    bulleted: bool = True,
    column: bool = False,
) -> tuple[str, int]:
    """Render a card; return (svg, height).

    ``min_height`` pads the card's box (white space at the bottom) so a row of
    cards can be made the same height regardless of how much text each holds.
    ``bulleted=False`` renders each entry as an italic paragraph with no bullet
    or hanging indent and a little more space between — for quote/testimonial
    cards where dotted bullets would read wrong.
    """
    inner_width = width - 2 * CARD_PADDING
    text_fill = "#2A2F3D" if not dark else "#EDEEF4"
    text_class = "b" if bulleted else "note"
    leader = "•  " if bulleted else ""
    indent = BULLET_INDENT if bulleted else 0
    item_gap = BULLET_GAP if bulleted else 26

    wrapped = [wrap_tokens(tokenize(b), inner_width, BULLET_SIZE) for b in card["bullets"]]
    body = []
    cursor = y + 170
    for lines in wrapped:
        for line_index, line in enumerate(lines):
            if line_index == 0:
                body.append(render_line(line, x + CARD_PADDING, cursor, text_class, text_fill, leader=leader))
            else:
                body.append(
                    render_line(line, x + CARD_PADDING + indent, cursor, text_class, text_fill)
                )
            cursor += BULLET_LINE_HEIGHT
        cursor += item_gap

    if card.get("note"):
        cursor += 18
        note_lines = wrap_tokens(tokenize(card["note"]), inner_width, BULLET_SIZE)
        for line in note_lines:
            body.append(render_line(line, x + CARD_PADDING, cursor, "note", "#6A4FD0"))
            cursor += BULLET_LINE_HEIGHT

    height = max(cursor - y + 26, min_height)
    collapsed = bool(card.get("collapsed"))
    body_svg = card_divider(x, y, width) + "".join(body)
    svg = collapsible(
        x, y, width, height, card["color"],
        card_header(card, x, y), body_svg, collapsed=collapsed, column=column,
    )
    return svg, height


def layout_quotes(
    quotes: dict, x: int, y: int, width: int, min_height: int = 0, column: bool = False
) -> tuple[str, int]:
    """Render 'words that resonate' as a warm, literary parchment card.

    A deliberate contrast to the dark block it used to be: an ivory paper card
    that sits with the others (shadow, gradient divider echoing the top bar), a
    gold blockquote rule beside each quote, and warm terracotta attributions.
    ``min_height`` pads the box so the bottom row of cards lines up.
    """
    background = quotes.get("bg", "#FFFFFF")  # white, consistent with its neighbours
    rule_x = x + CARD_PADDING
    text_x = x + CARD_PADDING + 34  # clear the blockquote rule
    inner_width = width - 2 * CARD_PADDING - 34
    ink = "#403B33"
    attribution_color = "#A8632B"  # warm terracotta
    body = []
    rules = []
    cursor = y + 200
    for item in quotes["items"]:
        quote_top = cursor - 32
        text = "“" + item["text"] + "”"
        lines = wrap_tokens(tokenize(text), inner_width, QUOTE_SIZE)
        for line_index, line in enumerate(lines):
            is_last = line_index == len(lines) - 1
            attribution = ""
            if is_last and item.get("by"):
                attribution = (
                    f' <tspan class="qa" fill="{attribution_color}">'
                    f'— {escape(item["by"])}</tspan>'
                )
            words = " ".join(word for word, _ in line)
            body.append(
                f'<text x="{text_x}" y="{cursor}" class="q" fill="{ink}">'
                f"{escape(words)}{attribution}</text>"
            )
            cursor += QUOTE_LINE_HEIGHT
        rules.append(
            f'<rect x="{rule_x}" y="{quote_top}" width="5" '
            f'height="{cursor - QUOTE_LINE_HEIGHT + 10 - quote_top}" rx="2.5" fill="#D9A441"/>'
        )
        cursor += 24

    height = max(cursor - y + 24, min_height)
    collapsed = bool(quotes.get("collapsed"))
    header = (
        disclosure_triangle(x + CARD_PADDING + 12, y + 56, False)
        + f'<text x="{x+CARD_PADDING+44}" y="{y+106}" font-weight="800" font-size="120" '
        f'fill="#E0B86A">&#8220;</text>'
        f'<text x="{x+CARD_PADDING+170}" y="{y+82}" class="cardh" fill="#2A2620">'
        f'{escape(quotes["title"])}</text>'
    )
    divider = (
        f'<line x1="{x+CARD_PADDING}" y1="{y+118}" x2="{x+width-CARD_PADDING}" y2="{y+118}" '
        f'stroke="#D9A441" stroke-width="4"/>'
    )
    body_svg = divider + "".join(rules) + "".join(body)
    svg = collapsible(
        x, y, width, height, "#D9A441", header, body_svg,
        bg=background, collapsed=collapsed, column=column,
    )
    return svg, height


def layout_links(
    links: dict, x: int, y: int, width: int, min_height: int = 0, column: bool = False
) -> tuple[str, int]:
    """Render the 'find me online' card with clickable buttons.

    ``min_height`` pads the box so it can match the height of the other cards in
    its row; the extra is white space below the buttons.
    """
    buttons = []
    cursor = y + 150
    button_x = x + CARD_PADDING
    button_width = width - 2 * CARD_PADDING
    for button in links["buttons"]:
        buttons.append(
            f'<a href="{escape(button["href"])}" target="_blank">'
            f'<rect x="{button_x}" y="{cursor}" width="{button_width}" height="{BUTTON_HEIGHT}" '
            f'rx="16" fill="#EEF1FB" stroke="#2D6CDF" stroke-width="2"/>'
            f'<text x="{button_x+32}" y="{cursor+60}" class="btn" fill="#2D6CDF">{escape(button["label"])}</text></a>'
        )
        cursor += BUTTON_HEIGHT + BUTTON_GAP

    height = max(cursor - y + 18, min_height)
    collapsed = bool(links.get("collapsed"))
    header_card = {"icon": links["icon"], "color": links["color"], "title": links["title"]}
    body_svg = card_divider(x, y, width) + "".join(buttons)
    svg = collapsible(
        x, y, width, height, links["color"],
        card_header(header_card, x, y), body_svg,
        collapsed=collapsed, column=column,
    )
    return svg, height


def connector(brain_x: int, card_x: int, card_center_y: int) -> tuple[str, str]:
    """Return (path, node) connecting the brain to a card edge."""
    brain_y = max(700, min(1700, card_center_y))
    if card_x < brain_x:  # card sits to the LEFT of the brain
        path = f"M {brain_x},{brain_y} C {brain_x-110},{brain_y+10} {card_x+110},{card_center_y} {card_x},{card_center_y}"
    else:  # card sits to the RIGHT of the brain
        path = f"M {brain_x},{brain_y} C {brain_x+110},{brain_y+10} {card_x-110},{card_center_y} {card_x},{card_center_y}"
    node = f'<circle cx="{card_x}" cy="{card_center_y}" r="13"/>'
    return path, node


def render_markers(content: dict, brain_x: float, brain_y: float, scale: float) -> str:
    """Render the invisible hover/click boxes laid over the brain art.

    Each marker may carry a ``tooltip`` (shown on hover in the interactive HTML
    page) and/or an ``href`` (opened on click). A marker with neither does
    nothing, so at least one is expected. Falls back to the legacy
    ``brain_hotspots`` key, whose entries are link-only.

    Marker coordinates are authored against the ``BRAIN_IMAGE_*`` frame; they are
    mapped onto the actually-drawn art (``brain_x``/``brain_y`` origin, ``scale``
    factor) so they stay aligned no matter how the brain is sized or placed.
    """
    markers = content.get("brain_markers")
    if markers is None:
        markers = content.get("brain_hotspots", [])
    parts: list[str] = []
    for marker in markers:
        tooltip = (marker.get("tooltip") or "").strip()
        href = (marker.get("href") or "").strip()
        # Optional hotspots: an unpopulated box (no tooltip AND no link) renders
        # nothing at all. Scatter as many placeholder boxes as you like and fill
        # in only the ones you want — the rest simply don't appear.
        if not tooltip and not href:
            continue
        marker_x = brain_x + (marker["x"] - BRAIN_IMAGE_X) * scale
        marker_y = brain_y + (marker["y"] - BRAIN_IMAGE_Y) * scale
        tip_attr = f' data-tip="{escape(tooltip)}"' if tooltip else ""
        rect = (
            f'<rect class="hot" x="{marker_x:.1f}" y="{marker_y:.1f}" '
            f'width="{marker["w"] * scale:.1f}" height="{marker["h"] * scale:.1f}" '
            f'rx="16"{tip_attr}/>'
        )
        if href:
            parts.append(f'<a href="{escape(href)}" target="_blank">{rect}</a>')
        else:
            parts.append(rect)
    return "".join(parts)


def build_svg(content: dict, brain_height: int) -> str:
    """Assemble the full poster SVG string."""
    cards_svg: list[str] = []

    # ── Left sidebar: every card, stacked and collapsible (the page reflows the
    # stack as cards fold). Positioned at full heights so the static exports show
    # everything; the interactive JS folds + reflows on load. ──
    LEFT_X = 70
    SIDEBAR_W = 1240
    sidebar: list[tuple[str, dict]] = [
        ("card", card) for card in content["left_column"] + content["right_column"]
    ]
    if content.get("endorsements"):
        sidebar.append(("endorse", content["endorsements"]))
    sidebar.append(("quotes", content["quotes"]))
    sidebar.append(("links", content["links"]))

    y = COLUMN_TOP
    sidebar_collapsed_bottom = COLUMN_TOP
    for kind, card in sidebar:
        if kind == "endorse":
            svg, height = layout_card(card, LEFT_X, y, SIDEBAR_W, bulleted=False, column=True)
        elif kind == "quotes":
            svg, height = layout_quotes(card, LEFT_X, y, SIDEBAR_W, column=True)
        elif kind == "links":
            svg, height = layout_links(card, LEFT_X, y, SIDEBAR_W, column=True)
        else:
            svg, height = layout_card(card, LEFT_X, y, SIDEBAR_W, column=True)
        cards_svg.append(svg)
        initial = COLLAPSED_HEIGHT if card.get("collapsed") else height
        sidebar_collapsed_bottom += initial + COLUMN_GAP
        y += height + COLUMN_GAP
    sidebar_full_bottom = y

    # ── Right panel: the brain map as one big collapsible card ──
    panel_x = LEFT_X + SIDEBAR_W + 70
    panel_w = CANVAS_WIDTH - panel_x - 70
    panel_cx = panel_x + panel_w // 2
    brain_x = panel_x + CARD_PADDING
    brain_w = panel_w - 2 * CARD_PADDING
    brain_scale = brain_w / BRAIN_IMAGE_WIDTH
    brain_h = round(brain_height * brain_scale)
    brain_card_y = COLUMN_TOP
    brain_collapsed = bool(content.get("brain_collapsed"))
    img_y = brain_card_y + 140
    img_bottom = img_y + brain_h

    center_parts: list[str] = []
    caption_y = img_bottom + 76
    center_parts.append(
        f'<text x="{panel_cx}" y="{caption_y}" text-anchor="middle" class="b" '
        f'fill="#8A91A3" font-style="italic">{escape(content["brain_caption"])}</text>'
    )
    stack_bottom = caption_y
    brain_link = content.get("brain_link")
    thumb_name = brain_link.get("thumbnail") if brain_link else None
    if thumb_name and brain_link:
        thumb_b64 = base64.b64encode((PROJECT / thumb_name).read_bytes()).decode("ascii")
        mime = "jpeg" if thumb_name.lower().endswith((".jpg", ".jpeg")) else "png"
        with Image.open(PROJECT / thumb_name) as thumb_image:
            thumb_ratio = thumb_image.height / thumb_image.width
        thumb_w = min(1500, panel_w - 2 * CARD_PADDING - 200)
        thumb_h = round(thumb_w * thumb_ratio)
        thumb_x = panel_cx - thumb_w // 2
        thumb_y = caption_y + 44
        frame = 12
        href = escape(brain_link["href"])
        data_uri = f"data:image/{mime};base64,{thumb_b64}"
        center_parts.append(
            f'<a href="{href}" target="_blank">'
            f'<rect x="{thumb_x - frame}" y="{thumb_y - frame}" '
            f'width="{thumb_w + 2 * frame}" height="{thumb_h + 2 * frame}" rx="22" '
            f'fill="#FFFFFF" stroke="#E4E7EC" stroke-width="2" filter="url(#shadow)"/>'
            f'<image x="{thumb_x}" y="{thumb_y}" width="{thumb_w}" height="{thumb_h}" '
            f'href="{data_uri}" xlink:href="{data_uri}" preserveAspectRatio="xMidYMid meet"/></a>'
        )
        link_y = thumb_y + thumb_h + 72
        center_parts.append(
            f'<a href="{href}" target="_blank">'
            f'<text x="{panel_cx}" y="{link_y}" text-anchor="middle" class="lnk" '
            f'font-weight="700" font-size="40">{escape(brain_link["text"])}</text></a>'
        )
        stack_bottom = link_y + 16
    elif brain_link:
        link_y = img_bottom + 160
        center_parts.append(
            f'<a href="{escape(brain_link["href"])}" target="_blank">'
            f'<text x="{panel_cx}" y="{link_y}" text-anchor="middle" class="lnk" '
            f'font-weight="700" font-size="40">{escape(brain_link["text"])}</text></a>'
        )
        stack_bottom = link_y

    github = content.get("github_link")
    if github:
        label = github.get("label", "View on GitHub")
        font_size = 32
        icon_size = 36
        pad = 28
        gap = 18
        button_h = 68
        button_w = pad + icon_size + gap + int(text_width(label, font_size)) + pad
        button_x = panel_cx - button_w // 2
        button_y = stack_bottom + 34
        stack_bottom = button_y + button_h
        icon_x = button_x + pad
        icon_y = button_y + (button_h - icon_size) // 2
        gh_scale = icon_size / 16
        center_parts.append(
            f'<a href="{escape(github.get("href", ""))}" target="_blank">'
            f'<rect x="{button_x}" y="{button_y}" width="{button_w}" height="{button_h}" rx="16" fill="#2A2F3D"/>'
            f'<g transform="translate({icon_x},{icon_y}) scale({gh_scale:.5f})" fill="#FFFFFF"><path d="{OCTOCAT_PATH}"/></g>'
            f'<text x="{icon_x + icon_size + gap}" y="{button_y + button_h // 2 + 11}" '
            f'font-weight="700" font-size="{font_size}" fill="#FFFFFF">{escape(label)}</text></a>'
        )

    brain_full_h = stack_bottom - brain_card_y + 50
    hotspots = render_markers(content, brain_x, img_y, brain_scale)
    brain_title = content.get("brain_title", "My brain — poke around the icons")
    brain_header = (
        disclosure_triangle(panel_x + CARD_PADDING + 16, brain_card_y + 58, False)
        + f'<text x="{panel_x + CARD_PADDING + 60}" y="{brain_card_y + 78}" class="cardh" '
        f'fill="#1F2433">{escape(brain_title)}</text>'
    )
    brain_body = (
        card_divider(panel_x, brain_card_y, panel_w)
        + f'<image x="{brain_x}" y="{img_y}" width="{brain_w}" height="{brain_h}" '
        f'href="{WEB_BRAIN.name}" xlink:href="{WEB_BRAIN.name}" preserveAspectRatio="xMidYMid meet"/>'
        + hotspots
        + "".join(center_parts)
    )
    cards_svg.append(
        collapsible(
            panel_x, brain_card_y, panel_w, brain_full_h, "",
            brain_header, brain_body, collapsed=brain_collapsed,
        )
    )

    brain_initial_bottom = brain_card_y + (COLLAPSED_HEIGHT if brain_collapsed else brain_full_h)
    canvas_height = max(sidebar_full_bottom, brain_card_y + brain_full_h) + 50
    fit_height = max(sidebar_collapsed_bottom, brain_initial_bottom) + 50

    head = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg viewBox="0 0 {CANVAS_WIDTH} {canvas_height}" width="{CANVAS_WIDTH}" height="{canvas_height}" data-fit-h="{fit_height}" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
  <defs>
    <linearGradient id="bar" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#0F5E86"/><stop offset="0.5" stop-color="#6A4FD0"/><stop offset="1" stop-color="#F2547D"/>
    </linearGradient>
    <filter id="shadow" x="-8%" y="-8%" width="116%" height="124%">
      <feDropShadow dx="0" dy="10" stdDeviation="16" flood-color="#1F2433" flood-opacity="0.16"/>
    </filter>
    <style>
      /* Text uses the embedded PosterSans — the same font the build measured
         with — so card text fits identically in any browser. The @font-face that
         supplies it is defined at the document level (see build_html and the PNG
         & PDF wrappers); document-level is honoured for inline-SVG text
         everywhere, including iOS Safari, whereas an SVG-scoped @font-face is not.
         Falls back to Helvetica/Arial only if the embedded font fails to load. */
      text {{ font-family: '{EMBED_FAMILY}', Helvetica, Arial, sans-serif; }}
      .h1 {{ font-weight: 800; font-size: 132px; }}
      .subt {{ font-weight: 400; font-size: 36px; }}
      .tagt {{ font-weight: 600; font-size: 32px; font-style: italic; }}
      .cardh {{ font-weight: 800; font-size: 56px; }}
      .b {{ font-weight: 400; font-size: {BULLET_SIZE}px; }}
      .note {{ font-weight: 400; font-size: {BULLET_SIZE}px; font-style: italic; }}
      .q {{ font-weight: 400; font-size: {QUOTE_SIZE}px; font-style: italic; }}
      .qa {{ font-weight: 700; font-size: 37px; }}
      .btn {{ font-weight: 700; font-size: 44px; }}
      a tspan.lnk, .lnk {{ fill: #2D6CDF; text-decoration: underline; }}
      a {{ cursor: pointer; }}
      .hot {{ fill: #2D6CDF; fill-opacity: 0; stroke: #2D6CDF; stroke-width: 0; transition: fill-opacity .15s; }}
      a:hover .hot, .hot:hover {{ fill-opacity: 0.14; stroke-width: 4; }}
    </style>
  </defs>
  <rect x="0" y="0" width="{CANVAS_WIDTH}" height="{canvas_height}" fill="#FFFFFF"/>
  <text x="2300" y="206" text-anchor="middle" class="h1" fill="#1F2433">{escape(content["title"])}</text>
  <text x="2300" y="262" text-anchor="middle" class="subt" fill="#4A5163">{escape(content["subtitle"])}</text>
  <text x="2300" y="312" text-anchor="middle" class="tagt" fill="#6A4FD0">&#9472; {escape(content["tagline"])} &#9472;</text>
  {''.join(cards_svg)}
</svg>
"""
    return head


def embed_brain(svg_text: str) -> str:
    """Inline the brain PNG as a base64 data URI and drop the XML prolog.

    The result is a self-contained SVG fragment safe to embed directly in an
    HTML document (the external image reference is gone, so it renders even
    when a browser would otherwise block cross-resource loads).
    """
    data_uri = "data:image/png;base64," + base64.b64encode(WEB_BRAIN.read_bytes()).decode()
    inline = svg_text.replace(f'href="{WEB_BRAIN.name}"', f'href="{data_uri}"')
    inline = inline.replace(f'xlink:href="{data_uri}"', "")
    return re.sub(r"^<\?xml[^>]*\?>\s*", "", inline)


def inline_html(text: str) -> str:
    """Render text with [label](url) markdown links as escaped HTML."""
    parts: list[str] = []
    position = 0
    for match in LINK_RE.finditer(text):
        parts.append(escape(text[position : match.start()]))
        parts.append(
            f'<a href="{escape(match.group(2))}" target="_blank">{escape(match.group(1))}</a>'
        )
        position = match.end()
    parts.append(escape(text[position:]))
    return "".join(parts)


def _mobile_card(card: dict) -> str:
    """Render one content card as a mobile section."""
    glyph = f'<svg width="36" height="36" viewBox="0 0 60 60">{icon(card["icon"], 30, 30, card["color"])}</svg>'
    bullets = "".join(f"<li>{inline_html(bullet)}</li>" for bullet in card["bullets"])
    note = f'<p class="note">{inline_html(card["note"])}</p>' if card.get("note") else ""
    return (
        f'<section class="card" style="--accent:{escape(card["color"])}">'
        f'<h2>{glyph}<span>{escape(card["title"])}</span></h2>'
        f"<ul>{bullets}</ul>{note}</section>"
    )


def render_mobile(content: dict) -> str:
    """Render the no-image-map, stacked-card layout shown on phones."""
    bottom_left = content.get("endorsements") or content["about"]
    cards = "".join(
        _mobile_card(card)
        for card in content["left_column"] + content["right_column"] + [bottom_left]
    )
    quotes = content["quotes"]
    quote_items = "".join(
        f'<blockquote>“{inline_html(item["text"])}”'
        + (f'<span class="by">— {escape(item["by"])}</span>' if item.get("by") else "")
        + "</blockquote>"
        for item in quotes["items"]
    )
    quotes_html = f'<section class="card quotes"><h2><span>{escape(quotes["title"])}</span></h2>{quote_items}</section>'
    links = content["links"]
    buttons = "".join(
        f'<a class="btn" href="{escape(button["href"])}" target="_blank">{escape(button["label"])}</a>'
        for button in links["buttons"]
    )
    links_html = (
        f'<section class="card links" style="--accent:{escape(links["color"])}">'
        f'<h2><span>{escape(links["title"])}</span></h2>{buttons}</section>'
    )
    github = content.get("github_link")
    footer = ""
    if github:
        octocat = f'<svg width="22" height="22" viewBox="0 0 16 16" fill="#fff"><path d="{OCTOCAT_PATH}"/></svg>'
        footer = (
            f'<footer><a class="ghbtn" href="{escape(github.get("href", ""))}" target="_blank">'
            f'{octocat}{escape(github.get("label", "GitHub"))}</a></footer>'
        )
    brain_link = content.get("brain_link")
    brain_link_html = (
        f'<p style="text-align:center;font-weight:700;font-size:17px;margin:8px 16px 4px">'
        f'<a href="{escape(brain_link["href"])}" target="_blank">{escape(brain_link["text"])}</a></p>'
        if brain_link else ""
    )
    return (
        f'<div id="mobile"><h1>{escape(content["title"])}</h1>'
        f'<p class="sub">{escape(content["subtitle"])}</p>'
        f"{brain_link_html}{cards}{quotes_html}{links_html}{footer}</div>"
    )


def build_html(svg_text: str, content: dict) -> str:
    """Wrap the SVG (with brain base64-embedded) in a pan/zoom page.

    The same page also carries a stacked-card mobile layout (no image map); CSS
    shows the poster on wide screens and the cards on narrow ones.
    """
    inline = embed_brain(svg_text).replace("<svg ", '<svg id="poster" ', 1)
    return (
        _HTML_SHELL.replace("__FONTFACES__", embedded_font_faces())
        .replace("__COLLAPSED_HEIGHT__", str(COLLAPSED_HEIGHT))
        .replace("__COLUMN_TOP__", str(COLUMN_TOP))
        .replace("__COLUMN_GAP__", str(COLUMN_GAP))
        .replace("__TRI_DOWN__", TRI_DOWN)
        .replace("__TRI_RIGHT__", TRI_RIGHT)
        .replace("__SVG__", inline)
        .replace("__MOBILE__", render_mobile(content))
    )


_HTML_SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Spencer's README</title>
<style>
__FONTFACES__
  html,body{margin:0;height:100%;background:#FFFFFF;font-family:'Helvetica Neue',Arial,sans-serif;overflow:hidden}
  #stage{position:fixed;inset:0;cursor:grab;touch-action:none;overflow:hidden}
  #stage.grabbing{cursor:grabbing}
  #poster{position:absolute;top:0;left:0;transform-origin:0 0;will-change:transform;user-select:none}
  #poster a{cursor:pointer}
  #poster .ctoggle{cursor:pointer}
  #hud{position:fixed;right:14px;top:14px;display:flex;gap:6px;z-index:30}
  #hud button{font:600 13px/1 'Helvetica Neue',Arial;background:#fff;color:#1F2433;border:1px solid #d0d7de;border-radius:9px;padding:8px 11px;cursor:pointer;box-shadow:0 1px 2px rgba(31,36,51,.08);-webkit-tap-highlight-color:transparent}
  #hud button:hover{background:#f3f4f6}
  #hint{position:fixed;right:14px;top:58px;z-index:10;background:rgba(255,255,255,.95);color:#57606a;border:1px solid #d0d7de;font:500 12px/1.45 'Helvetica Neue',Arial;padding:8px 11px;border-radius:9px;max-width:230px}
  #tip{position:fixed;z-index:20;pointer-events:none;background:rgba(31,36,51,.96);color:#fff;font:500 15px/1.35 'Helvetica Neue',Arial;padding:8px 11px;border-radius:8px;max-width:280px;box-shadow:0 6px 18px rgba(0,0,0,.28);opacity:0;transition:opacity .12s}
  #tip.show{opacity:1}
  #mobile{display:none;max-width:680px;margin:0 auto;padding:26px 18px 56px;color:#2A2F3D;text-align:left}
  #mobile h1{font-size:2rem;font-weight:800;text-align:center;color:#1F2433;margin:6px 0 4px}
  #mobile .sub{text-align:center;color:#4A5163;font-size:1rem;margin:0 0 24px;line-height:1.5}
  #mobile .card{background:#fff;border-radius:16px;box-shadow:0 4px 14px rgba(31,36,51,.10);padding:18px 18px 14px;margin:0 0 16px;border-left:8px solid var(--accent,#888)}
  #mobile .card h2{display:flex;align-items:center;gap:10px;font-size:1.2rem;font-weight:800;color:#1F2433;margin:0 0 10px}
  #mobile .card ul{margin:0;padding-left:20px}
  #mobile .card li{margin:0 0 8px;line-height:1.45;font-size:1rem}
  #mobile .card .note{font-style:italic;color:#6A4FD0;margin:10px 0 0;font-size:.95rem}
  #mobile a{color:#2D6CDF}
  #mobile .quotes{background:#fff;border-left-color:#D9A441}
  #mobile .quotes h2{color:#1F2433}
  #mobile .quotes blockquote{color:#403B33}
  #mobile blockquote{margin:0 0 14px;font-style:italic;line-height:1.5}
  #mobile blockquote .by{font-style:normal;font-weight:700;color:#A8632B;display:block;margin-top:3px;font-size:.9rem}
  #mobile .links a.btn{display:block;background:#EEF1FB;border:1px solid #2D6CDF;color:#2D6CDF;border-radius:12px;padding:14px 16px;margin:0 0 10px;text-decoration:none;font-weight:700;font-size:1rem;overflow-wrap:anywhere}
  #mobile .ghbtn{display:inline-flex;align-items:center;gap:9px;background:#2A2F3D;color:#fff;border-radius:14px;padding:13px 20px;text-decoration:none;font-weight:700}
  #mobile footer{text-align:center;margin-top:22px}
  /* Text fallback is for phones only: either viewport dimension <=540px means a
     phone (in some orientation). Tablets (iPad mini portrait is 768 wide) have
     both dimensions well above this, so they get the interactive poster. The
     height clause is gated to touch (pointer:coarse) so short *desktop* windows
     keep the interactive view exactly as before. */
  @media (max-width:540px), (max-height:540px) and (pointer:coarse){
    html,body{overflow:auto;height:auto}
    #stage,#hud,#hint,#tip{display:none}
    #mobile{display:block}
  }
</style>
</head>
<body>
<div id="stage">
__SVG__
</div>
<div id="hud">
  <button type="button" id="zin">＋ Zoom in</button>
  <button type="button" id="zout">－ Zoom out</button>
  <button type="button" id="fit">⤢ Fit</button>
</div>
<div id="hint">Drag or scroll to pan &middot; pinch or the +/&minus; keys to zoom &middot; click a card&rsquo;s header to expand or collapse it &middot; hover the brain icons for notes.</div>
<div id="tip"></div>
__MOBILE__
<script>
(function(){
  var stage=document.getElementById('stage');
  var svg=document.getElementById('poster');
  var vb=svg.getAttribute('viewBox').split(/\\s+/).map(Number);
  var W=vb[2], H=vb[3];
  // Fit to the (tighter) collapsed height so folded cards leave no dead space;
  // the SVG itself stays full height, so an expanded card is never clipped.
  var Hfit=+svg.getAttribute('data-fit-h')||H;
  svg.style.width=W+'px'; svg.style.height=H+'px';
  var scale=1, tx=0, ty=0;
  function apply(){ svg.style.transform='translate('+tx+'px,'+ty+'px) scale('+scale+')'; }
  function fit(){
    var pad=40;
    var s=Math.min((stage.clientWidth-pad)/W,(stage.clientHeight-pad)/Hfit);
    scale=s; tx=(stage.clientWidth-W*s)/2; ty=(stage.clientHeight-Hfit*s)/2; apply();
  }
  function zoomAt(cx,cy,factor){
    var ns=Math.max(0.05,Math.min(8,scale*factor));
    tx=cx-(cx-tx)*(ns/scale); ty=cy-(cy-ty)*(ns/scale); scale=ns; apply();
  }
  var down=false,moved=false,sx=0,sy=0,otx=0,oty=0,target=null,toggleTarget=null;
  // ── Collapsible cards: toggle a card between its full slot and a header pill.
  var CH=__COLLAPSED_HEIGHT__, TRI_DOWN='__TRI_DOWN__', TRI_RIGHT='__TRI_RIGHT__';
  var COLTOP=__COLUMN_TOP__, COLGAP=__COLUMN_GAP__;
  // The left sidebar (.colcard) reflows as a tight stack: each card is shifted by
  // (running y − its baked y) so folding one slides the rest up.
  function reflow(){
    var cols=svg.querySelectorAll('.colcard'), y=COLTOP;
    for(var i=0;i<cols.length;i++){
      var c=cols[i];
      c.setAttribute('transform','translate(0,'+(y-(+c.getAttribute('data-y')))+')');
      y+=(c.classList.contains('collapsed')?CH:+c.getAttribute('data-eh'))+COLGAP;
    }
  }
  function toggleCard(card){
    if(!card)return;
    var collapsed=card.classList.toggle('collapsed');
    var h=collapsed?CH:card.getAttribute('data-eh');
    var rects=card.querySelectorAll('.cbg,.cbar');
    for(var i=0;i<rects.length;i++) rects[i].setAttribute('height',h);
    var body=card.querySelector('.cbody'); if(body) body.setAttribute('display',collapsed?'none':'inline');
    var tri=card.querySelector('.ctri'); if(tri) tri.setAttribute('points',collapsed?TRI_RIGHT:TRI_DOWN);
    reflow();
  }
  // Active pointers, keyed by id. A mouse is always a single pointer, so it never
  // enters the two-finger pinch path below — the desktop drag/click behaviour is
  // unchanged. A second touch starts a pinch; a single touch pans exactly like a
  // mouse drag does.
  var pointers={}, pinch=null;
  function ptList(){ return Object.keys(pointers).map(function(k){return pointers[k];}); }
  function ptDist(a,b){ return Math.hypot(a.x-b.x, a.y-b.y); }
  stage.addEventListener('pointerdown',function(e){
    pointers[e.pointerId]={x:e.clientX,y:e.clientY};
    stage.setPointerCapture(e.pointerId);
    var pts=ptList();
    if(pts.length>=2){                 // second finger down → begin pinch-zoom
      down=false; moved=true; target=null; hideTip();   // cancel any pan/tap in progress
      pinch={d:ptDist(pts[0],pts[1]), r:stage.getBoundingClientRect()};
      stage.classList.remove('grabbing');
      return;
    }
    down=true;moved=false;sx=e.clientX;sy=e.clientY;otx=tx;oty=ty;
    target=e.target.closest('a');
    toggleTarget=e.target.closest('.ctoggle');
    hideTip();
    stage.classList.add('grabbing');
  });
  stage.addEventListener('pointermove',function(e){
    if(pointers[e.pointerId]){ pointers[e.pointerId].x=e.clientX; pointers[e.pointerId].y=e.clientY; }
    if(pinch){                         // two fingers → zoom about their midpoint
      var pts=ptList();
      if(pts.length>=2){
        var nd=ptDist(pts[0],pts[1]);
        if(nd>0 && pinch.d>0){
          var mx=(pts[0].x+pts[1].x)/2, my=(pts[0].y+pts[1].y)/2;
          zoomAt(mx-pinch.r.left, my-pinch.r.top, nd/pinch.d);
        }
        pinch.d=nd;
      }
      return;
    }
    if(!down)return; var dx=e.clientX-sx, dy=e.clientY-sy;
    if(Math.abs(dx)+Math.abs(dy)>4)moved=true;
    tx=otx+dx; ty=oty+dy; apply();
  });
  function endPointer(e){
    delete pointers[e.pointerId];
    if(pinch){                         // lifting a finger ends (or hands off) the pinch
      if(ptList().length<2){
        pinch=null;
        var rest=ptList();
        if(rest.length===1){           // one finger remains → resume panning, no jump, no tap
          down=true; moved=true; sx=rest[0].x; sy=rest[0].y; otx=tx; oty=ty;
        }
      }
      stage.classList.remove('grabbing');
      return;
    }
    down=false; stage.classList.remove('grabbing');
    if(toggleTarget && !moved){ toggleCard(toggleTarget.closest('.card')); toggleTarget=null; target=null; return; }
    toggleTarget=null;
    if(target && !moved){ var href=target.getAttribute('href')||target.getAttribute('xlink:href'); if(href){ window.open(href,'_blank'); } target=null; return; }
    target=null;
    if(e.pointerType!=='mouse' && !moved){   // touch tap on empty art toggles marker tooltips
      var el=e.target.closest('[data-tip]');
      if(el){ tip.textContent=el.getAttribute('data-tip'); tip.classList.add('show'); moveTip(e.clientX,e.clientY); }
      else hideTip();
    }
  }
  stage.addEventListener('pointerup',endPointer);
  stage.addEventListener('pointercancel',endPointer);
  stage.addEventListener('wheel',function(e){
    e.preventDefault();
    var r=stage.getBoundingClientRect();
    if(e.ctrlKey){            // trackpad pinch (and ctrl+wheel on a mouse) → zoom at cursor
      zoomAt(e.clientX-r.left,e.clientY-r.top, e.deltaY<0?1.12:1/1.12);
    }else{                    // two-finger scroll / wheel → pan, like every other canvas app
      tx-=e.deltaX; ty-=e.deltaY; apply();
    }
  },{passive:false});
  // ── Keyboard controls (zoom, fit, nudge) ────────────────────────────────
  window.addEventListener('keydown',function(e){
    if(e.metaKey||e.ctrlKey||e.altKey)return;          // leave browser shortcuts alone
    if(getComputedStyle(stage).display==='none')return; // text fallback is showing
    var step=90, k=e.key;
    if(k==='+'||k==='='){ zoomAt(stage.clientWidth/2,stage.clientHeight/2,1.2); }
    else if(k==='-'||k==='_'){ zoomAt(stage.clientWidth/2,stage.clientHeight/2,1/1.2); }
    else if(k==='0'||k==='f'||k==='F'){ fit(); }
    else if(k==='ArrowLeft'){ tx+=step; apply(); }
    else if(k==='ArrowRight'){ tx-=step; apply(); }
    else if(k==='ArrowUp'){ ty+=step; apply(); }
    else if(k==='ArrowDown'){ ty-=step; apply(); }
    else return;
    e.preventDefault();
  });
  // ── Icon tooltips (pure hover) ──────────────────────────────────────────
  var tip=document.getElementById('tip');
  function moveTip(x,y){
    var pad=14, tw=tip.offsetWidth, th=tip.offsetHeight;
    var nx=x+pad, ny=y+pad;
    if(nx+tw>window.innerWidth) nx=x-pad-tw;
    if(ny+th>window.innerHeight) ny=y-pad-th;
    tip.style.left=Math.max(4,nx)+'px'; tip.style.top=Math.max(4,ny)+'px';
  }
  function hideTip(){ tip.classList.remove('show'); }
  stage.addEventListener('pointerover',function(e){
    if(down || e.pointerType!=='mouse')return;   // touch tooltips are handled on tap, above
    var el=e.target.closest('[data-tip]');
    if(el){ tip.textContent=el.getAttribute('data-tip'); tip.classList.add('show'); moveTip(e.clientX,e.clientY); }
  });
  stage.addEventListener('pointerout',function(e){
    if(e.pointerType!=='mouse')return;
    if(e.target.closest('[data-tip]')) hideTip();
  });
  stage.addEventListener('pointermove',function(e){
    if(e.pointerType!=='mouse')return;           // pinned touch tip stays put until the next tap
    if(down){ hideTip(); return; }
    if(tip.classList.contains('show')) moveTip(e.clientX,e.clientY);
  });
  document.getElementById('zin').onclick=function(){zoomAt(stage.clientWidth/2,stage.clientHeight/2,1.25);};
  document.getElementById('zout').onclick=function(){zoomAt(stage.clientWidth/2,stage.clientHeight/2,1/1.25);};
  document.getElementById('fit').onclick=fit;
  window.addEventListener('resize',fit);
  window.addEventListener('orientationchange',fit);   // re-center when an iPad rotates
  // Fold the cards that should start collapsed (interactive page only; the static
  // SVG/PNG/PDF stay fully expanded).
  var startCollapsed=svg.querySelectorAll('.card[data-start-collapsed]');
  for(var ci=0;ci<startCollapsed.length;ci++) toggleCard(startCollapsed[ci]);
  reflow();
  fit();
})();
</script>
</body>
</html>
"""


def prepare_brain(source_name: str) -> int:
    """Convert the brain image to a web PNG; return its scaled poster height."""
    source = PROJECT / source_name
    if not source.exists():
        raise FileNotFoundError(f"brain_image not found: {source}")
    with Image.open(source) as image:
        rgb = image.convert("RGBA")
        rgb.save(WEB_BRAIN)
        native_width, native_height = rgb.size
    return round(BRAIN_IMAGE_WIDTH * native_height / native_width)


def find_chrome() -> str | None:
    """Locate a headless-capable Chrome/Chromium binary, or None."""
    mac_chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if Path(mac_chrome).exists():
        return mac_chrome
    return shutil.which("google-chrome") or shutil.which("chromium")


def poster_dimensions(svg_text: str) -> tuple[str, str] | None:
    """Return (width, height) from the SVG viewBox, or None if absent."""
    match = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg_text)
    if match is None:
        return None
    return match.group(1), match.group(2)


def render_png(svg_text: str) -> None:
    """Render a flat PNG preview with headless Chrome, if available."""
    chrome = find_chrome()
    if chrome is None:
        print("• Chrome not found — skipping PNG preview.")
        return
    dimensions = poster_dimensions(svg_text)
    if dimensions is None:
        print("• Could not read viewBox — skipping PNG preview.")
        return
    width, height = dimensions
    preview = PROJECT / "_preview.html"
    preview.write_text(
        "<!doctype html><meta charset=utf-8>"
        "<style>" + embedded_font_faces()
        + "html,body{margin:0;background:#EEEEF3}</style>" + embed_brain(svg_text)
    )
    subprocess.run(
        [
            chrome, "--headless", "--disable-gpu", "--hide-scrollbars",
            "--force-device-scale-factor=1", f"--window-size={width},{height}",
            f"--screenshot={PNG_OUT}", preview.as_uri(),
        ],
        check=False,
        capture_output=True,
    )
    preview.unlink(missing_ok=True)
    if PNG_OUT.exists():
        print(f"• Wrote {PNG_OUT.name}")


def render_pdf(svg_text: str) -> None:
    """Render a high-resolution, print-ready PDF with headless Chrome.

    Text stays vector (crisp at any print size); the brain art is embedded as
    a raster. The PDF page is sized to the poster's exact pixel dimensions
    (1px = 1/96 inch), so 4600px wide prints at roughly 48 inches.
    """
    chrome = find_chrome()
    if chrome is None:
        print("• Chrome not found — skipping PDF.")
        return
    dimensions = poster_dimensions(svg_text)
    if dimensions is None:
        print("• Could not read viewBox — skipping PDF.")
        return
    width, height = dimensions
    page = PROJECT / "_print.html"
    page.write_text(
        "<!doctype html><meta charset=utf-8><style>"
        + embedded_font_faces()
        + f"@page{{size:{width}px {height}px;margin:0}}"
        "html,body{margin:0;padding:0;background:#EEEEF3}svg{display:block}"
        "</style>" + embed_brain(svg_text)
    )
    subprocess.run(
        [
            chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
            f"--print-to-pdf={PDF_OUT}", page.as_uri(),
        ],
        check=False,
        capture_output=True,
    )
    page.unlink(missing_ok=True)
    if PDF_OUT.exists():
        print(f"• Wrote {PDF_OUT.name}")


def archive_pdf() -> None:
    """Snapshot the current PDF into print/ with a timestamped filename."""
    if not PDF_OUT.exists():
        return
    PRINT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = PRINT_DIR / f"spencer-brain-poster-{stamp}.pdf"
    shutil.copy2(PDF_OUT, destination)
    print(f"• Archived {destination.relative_to(PROJECT)}")


def build_once(make_pdf: bool = True, archive: bool = True) -> dict:
    """Generate every artifact from the content file; return the content."""
    content = json.loads(resolve_content_path().read_text())
    brain_height = prepare_brain(content["brain_image"])
    svg_text = build_svg(content, brain_height)
    SVG_OUT.write_text(svg_text)
    print(f"• Wrote {SVG_OUT.name} and {WEB_BRAIN.name}")
    HTML_OUT.write_text(build_html(svg_text, content))
    print(f"• Wrote {HTML_OUT.name}")
    render_png(svg_text)
    if make_pdf:
        render_pdf(svg_text)
        if archive:
            archive_pdf()
    return content


def watched_paths(content: dict) -> list[Path]:
    """Files whose changes should trigger a rebuild."""
    return [resolve_content_path(), Path(__file__), PROJECT / content["brain_image"]]


def watch(make_pdf: bool = True) -> None:
    """Rebuild whenever the content file, brain image, or this script changes."""
    print("Watching for changes — edit poster-content.json, save, see it rebuild.")
    print("Press Ctrl-C to stop.\n")
    # Don't archive on every save during a watch — snapshots are for deliberate builds.
    content = build_once(make_pdf, archive=False)
    stamps = {path: path.stat().st_mtime for path in watched_paths(content) if path.exists()}
    while True:
        time.sleep(0.5)
        changed = [
            path for path, was in stamps.items()
            if path.exists() and path.stat().st_mtime != was
        ]
        if not changed:
            continue
        print(f"\n↻ changed: {', '.join(p.name for p in changed)} — rebuilding")
        try:
            content = build_once(make_pdf, archive=False)
        except Exception:  # keep watching after a bad edit; surface the error
            traceback.print_exc()
        # refresh stamps (brain_image target may have changed in the content)
        stamps = {path: path.stat().st_mtime for path in watched_paths(content) if path.exists()}


def main() -> None:
    """Parse arguments and build once, or watch and rebuild on change."""
    parser = argparse.ArgumentParser(description="Build the brain-map README poster.")
    parser.add_argument("--watch", action="store_true", help="rebuild on every save")
    parser.add_argument("--no-pdf", action="store_true", help="skip the print PDF")
    parser.add_argument(
        "--no-archive", action="store_true", help="don't snapshot a timestamped PDF into print/"
    )
    args = parser.parse_args()
    try:
        if args.watch:
            watch(make_pdf=not args.no_pdf)
        else:
            build_once(make_pdf=not args.no_pdf, archive=not args.no_archive)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
