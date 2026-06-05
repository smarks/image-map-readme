# image-map-readme

Build a large, pannable, **interactive "About Me" poster** from a single text file
plus one image. Icons drawn on your artwork show a tooltip on hover; on-art labels
become clickable links; side cards of bulleted text auto-reflow and lay themselves
out. The whole thing exports to a self-contained HTML page you can share, plus SVG,
PNG, and a print-ready PDF.

This repo is a **template**. Clone it, run `just build`, and you get a working demo
built from the bundled sample. Then drop in your own image and text to make it yours.

![the demo poster is generated from sample-brain.png + poster-content.example.json]

## The idea

The artwork is a single raster image, so the icons and labels on it can't carry their
own behavior. Instead, the interactivity is a layer of **invisible boxes** positioned
over the image in a fixed "poster-space" coordinate system. Each box — a *marker* — can
show a tooltip on hover and/or open a link on click. The build bakes the image in
(base64) and wraps it in a little pan/zoom/hover page. That's the whole trick: hotspots
over an image, plus an auto-reflowing card layout around it.

Nothing here is brain-specific — the sample happens to be a brain, but the technique
works over any image (a map, a diagram, a photo).

## Content is a `.env`-style file

Your real content lives in **`poster-content.json`**, which is **git-ignored** — treat
it like a `.env` secret. The committed **`poster-content.example.json`** is the template
(`.env.example`). The build uses your real file if it's present and silently falls back
to the example otherwise, so a fresh clone always builds *something*:

```
poster-content.json          (yours, git-ignored)  → your real art + text
poster-content.example.json  (committed template)   → the bundled demo
```

## Quick start

```bash
just build      # all artifacts (svg, html, png, pdf) + a timestamped print snapshot
just preview    # build, then open the interactive HTML
just verify     # check every marker box lands on its target (writes crops to verify/)
just sample     # regenerate the demo image + example content (make_sample.py)
```

No `just`? Call the scripts directly: `python3 build_poster.py`,
`python3 verify_markers.py`, `python3 make_sample.py`.

## Make it your own

1. **Copy the template:** `cp poster-content.example.json poster-content.json`.
2. **Add your image** and point `brain_image` at it (PNG or TIFF; TIFF is auto-converted).
3. **Write your text** — `title`, the `left_column` / `right_column` cards, `about`,
   `quotes`, `links`. Bullets support inline markdown links: `[label](url)`. Cards pick
   an `icon` (lightning, squiggle, twocircles, x, bubble, heart, person, globe) and a
   `color`. Text auto-reflows — you never touch layout coordinates.
4. **Place your markers** (below), then `just build`.

Your `poster-content.json` and image stay local and never get committed.

## Markers: the interactive layer

`brain_markers` is a list of invisible boxes over the image, in poster-space
coordinates. Each may carry a `tooltip` (hover) and/or an `href` (click):

```json
{ "label": "note to self", "tooltip": "Shown on hover.",
  "href": "https://example.com", "x": 1700, "y": 1030, "w": 90, "h": 110 }
```

`label` is just a note; it never renders. A marker can be tooltip-only, link-only, or
both. (A legacy `brain_hotspots` key is still read as a fallback.)

### Where do the coordinates come from?

They're relative to your specific image, so the image and its markers are a *matched
pair*. Two helpers:

- **`make_sample.py`** shows the pattern end to end: it draws the demo image and writes
  the matching markers in one pass, so they're correct by construction. Read it as the
  worked example, or adapt it to emit a starting marker set for your own art.
- **`find_brain_links.py`** (`just hotspots <image>`) scans an image for blue on-art URL
  labels and prints ready-to-paste boxes.

### Verify placement — `just verify`

Marker boxes are coordinates, so it's easy to place one a few dozen pixels off, and on
a busy image a small slip is invisible when you eyeball the whole poster. `verify_markers.py`
writes a **zoomed review crop per marker** (the box outlined on the art) to `verify/`,
and runs automated checks: a blue-text-centroid test for URL labels, and ink /
border-ink advisories for icons. It exits non-zero on hard failures so it can gate a
build — but **green is not proof** (the checks can't tell *which* icon a box is on).
Open the crops and look.

## How the build works

`build_poster.py` (pure Python + Pillow):

- Measures real text with Pillow to wrap bullets and size the cards and canvas — so
  editing text never requires moving anything.
- Emits an SVG, then a **self-contained HTML** page with the image base64-embedded and
  inline pan/zoom/grab + hover-tooltip JS. This HTML is the shareable artifact.
- Rasterizes the PNG and a print-ready, vector-text PDF via **headless Chrome**.

## Requirements

- Python 3.11+ with Pillow
- [`just`](https://github.com/casey/just) (optional — `brew install just`)
- Google Chrome (for PNG/PDF rasterization; SVG/HTML build without it)

## License

MIT. The bundled `sample-brain.png` is a generic placeholder — replace it with your own.
