"""Build a single self-contained HTML reference of the brain-map input screens.

Embeds each source PNG as base64 so the page is one shareable, annotatable file,
documents what the code does at each step and which files are responsible, and
ends with a diagram of the full publish workflow.

Run: python3 build_input_reference.py  (or: just inputref)
"""

import base64
import html
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_PATH = PROJECT_ROOT / "brain-input-screens.html"

# Each screen: number, title, source image, plain description, and an
# "under the hood" block (what the code does + which files do what).
SCREENS = [
    {
        "number": 1,
        "title": "Empty brain stencil",
        "source": "assets/1-empty-stencil.png",
        "desc": (
            "The bare hand-drawn brain outline — gyri and sulci only, no content. "
            "This is the base canvas every other layer sits on top of, and it "
            "defines the coordinate space (\"poster space\") that all the marker "
            "boxes are measured in. You just hand it over as a "
            "<code>brainimage.png</code> — nothing happens to it yet."
        ),
    },
    {
        "number": 2,
        "title": "Stencil with the icons",
        "source": "assets/2-with-icons.png",
        "desc": (
            "The stencil with the hand-placed icons baked into the raster — this is "
            "the current poster master the engine actually consumes. Because the "
            "icons are pixels in the image, they can't carry their own links or "
            "tooltips; that behavior comes from the invisible marker layer (step 3)."
        ),
        "code": (
            "<code>poster-content.json</code> names this file via "
            "<code>\"brain_image\": \"brain.png\"</code>. The engine "
            "<code>build_poster.py</code> measures its aspect ratio with Pillow, "
            "scales it, base64-embeds it into the generated SVG/HTML, and reflows "
            "the README cards and connector curves around it. Swapping the art is "
            "just pointing <code>brain_image</code> at a new file and rebuilding."
        ),
        "files": [
            ("private repo / poster-content.json", "Single source of truth; <code>brain_image</code> picks the art."),
            ("image-map-readme / build_poster.py", "Reads the art + content, emits svg / html / png / pdf."),
        ],
    },
    {
        "number": 3,
        "title": "Stencil with the purple blockouts (staging input)",
        "source": "assets/3-staging-blockouts.png",
        "desc": (
            "While placing the icons, use an image editor that has a layering "
            "feature. I use Procreate. For each icon, I create a layer that is a "
            "clipping mask of the icon, which typically is a square. I fill that in "
            "with color that the code will recognize as a bounding box for a click "
            "location. Flattened to a single image and handed to the program "
            "(<code>find_brain_links.py</code>), it is a staging map that says "
            "“make these spots interactive” — the clickable / hover regions "
            "are marked visually, by painting, instead of by typing pixel "
            "coordinates. The program reads the boxes and figures out where each "
            "marker goes."
        ),
        "code": (
            "<code>find_brain_links.py</code> turns the painted boxes into "
            "coordinates. It walks the image pixel by pixel and classifies each as "
            "the marker colour (the committed <code>is_blue()</code> test keys on "
            "the royal-blue callouts), buckets the hits into a 40-pixel grid, and "
            "keeps only the dense cells. It then flood-fills neighbouring cells into "
            "connected components — one component per painted box — takes "
            "each component’s bounding rectangle, and converts it from native "
            "pixels into poster space using the brain’s placement constants "
            "(<code>BRAIN_IMAGE_X / Y / WIDTH</code> plus a scale factor). The result "
            "is printed as ready-to-paste boxes; you then add each one’s "
            "tooltip / href by hand, since only you know which icon a box belongs to. "
            "From there <code>build_poster.py</code> renders the boxes as the "
            "invisible hover / click zones layered over the flat art."
        ),
        "files": [
            ("private repo / staging image", "Hand-painted: one purple box per icon, each on its own layer, over the icon."),
            ("image-map-readme / find_brain_links.py", "Detects the painted boxes, prints poster-space coordinates."),
            ("private repo / poster-content.json", "Where the detected boxes land, under <code>brain_markers</code> (you add tooltip/href)."),
            ("image-map-readme / build_poster.py", "Renders each box as an invisible hover/click zone over the art."),
        ],
    },
    {
        "number": 4,
        "title": "Stencil with the ID numbers",
        "source": "assets/4-id-numbers.png",
        "desc": (
            "The same marker boxes, outlined and numbered 1–N. It's the index "
            "map: each number ties a box on the art back to its entry in the "
            "marker list, so you can place and audit boxes without eyeballing a "
            "busy zoomed-out overlay."
        ),
        "code": (
            "<code>verify_markers.py</code> walks the <code>brain_markers</code> "
            "list in order (the numbers are the list indices), converts each "
            "poster-space box to native pixels, and writes a padded, red-outlined "
            "review crop per marker into <code>verify/</code>. It also runs "
            "automated checks (blue-label centroid for URL markers, ink coverage "
            "for icons) that can gate a build — but the per-number crop is the "
            "authoritative check you actually look at."
        ),
        "files": [
            ("image-map-readme / verify_markers.py", "Enumerates + checks markers, writes numbered review crops."),
            ("private repo / verify/", "Per-marker crops, named by index (git-ignored output)."),
        ],
    },
]


def encode_image(image_path: Path) -> str:
    """Return a base64 data URI for the given PNG."""
    encoded_bytes = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded_bytes}"


def render_files_table(files: list[tuple[str, str]]) -> str:
    """Render the file -> role table for a step's 'under the hood' panel."""
    rows = "\n".join(
        f"                    <tr><td><code>{html.escape(name)}</code></td>"
        f"<td>{role}</td></tr>"
        for name, role in files
    )
    return (
        '                <table class="files">\n'
        "                    <thead><tr><th>File</th><th>Role</th></tr></thead>\n"
        f"                    <tbody>\n{rows}\n                    </tbody>\n"
        "                </table>"
    )


def render_screen(screen: dict) -> str:
    """Render one numbered screen: image + 'under the hood' panel."""
    image_path = PROJECT_ROOT / screen["source"]
    if not image_path.exists():
        raise FileNotFoundError(f"Missing source image: {image_path}")
    data_uri = encode_image(image_path)
    under_hood = ""
    if screen.get("code"):
        under_hood = f"""
            <div class="under-hood">
                <h3>Under the hood</h3>
                <p>{screen["code"]}</p>
{render_files_table(screen["files"])}
            </div>"""
    return f"""        <section class="screen">
            <div class="screen-head">
                <span class="step-number">{screen["number"]}</span>
                <span class="screen-title">{html.escape(screen["title"])}</span>
                <span class="screen-source">{html.escape(screen["source"])}</span>
            </div>
            <p class="screen-desc">{screen["desc"]}</p>
            <div class="image-frame">
                <img src="{data_uri}" alt="{html.escape(screen["title"])}">
            </div>{under_hood}
        </section>"""


def render_workflow() -> str:
    """Render step 5: the publish-workflow diagram."""
    stages = [
        (
            "Start in the private repo",
            "The private repo holds the personal data: your README text, the brain "
            "art, and the passphrase gate. Committing a file here is the only manual "
            "step — everything after it is automatic.",
        ),
        (
            "Check out the engine + the private repo",
            "The workflow checks out the engine repo <code>image-map-readme</code> "
            "(the shared build engine) alongside the private repo (your content and "
            "art). The engine is improved upstream and flows in here.",
        ),
        (
            "Build the artifacts",
            "<code>image-map-readme / build_poster.py</code> reads "
            "<code>private repo / poster-content.json</code> + "
            "<code>private repo / brainimage.png</code> and emits "
            "<code>spencer-brain-poster.svg / .html / .png / .pdf</code>. "
            "The HTML is the self-contained, shareable file.",
        ),
        (
            "Gate + publish",
            "<code>private repo / deploy/make_gate.py</code> AES-256-GCM encrypts "
            "the HTML behind the <code>ME_PASSPHRASE</code> riddle and commits it as "
            "<code>me/index.html</code> into the landing repo "
            "<code>roots.origamisoftware.com</code>.",
        ),
        (
            "Go live",
            "A push to the landing repo <code>roots.origamisoftware.com</code> runs "
            "its own workflow: validate links, SSH into the server (datahorde), and "
            "<code>git pull</code> into the directory that is both the git checkout "
            "and the nginx web root — then a smoke-check. nginx serves the one "
            "static gated file at <strong>roots.origamisoftware.com/me</strong>; the "
            "visitor's answer decrypts the poster in-browser, so the page only ever "
            "ships ciphertext. (The live web <em>apps</em> — Tarmar, Meeting "
            "Assistant, etc. — use a blue/green swap; this static page does not.)",
        ),
    ]
    blocks = []
    for index, (heading, body) in enumerate(stages):
        blocks.append(
            f"""                <li class="flow-step">
                    <div class="flow-num">{index + 1}</div>
                    <div class="flow-body"><strong>{heading}</strong><br>{body}</div>
                </li>"""
        )
    flow_html = "\n".join(blocks)
    return f"""        <section class="screen workflow">
            <div class="screen-head">
                <span class="step-number">5</span>
                <span class="screen-title">The publish workflow</span>
                <span class="screen-source">private repo → image-map-readme → roots.origamisoftware.com</span>
            </div>
            <p class="screen-desc">How a content edit becomes the live, password-gated
            poster at <code>roots.origamisoftware.com/me</code>.</p>
            <div class="workflow-note">
                <strong>This all runs as GitHub Workflows — you commit a file to the
                private repo and wait.</strong> There are no manual build or deploy
                steps: one workflow builds and gates the poster and publishes it into
                the landing repo, then the landing repo's own workflow ships it to the
                server with a plain <code>git pull</code> into the web root. The change
                shows up live in about a minute.
            </div>
            <ol class="flow">
{flow_html}
            </ol>
        </section>"""


def build_html() -> str:
    """Assemble the full self-contained HTML document."""
    screens_html = "\n".join(render_screen(screen) for screen in SCREENS)
    workflow_html = render_workflow()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Brain-Map Poster — Input Screens &amp; Workflow</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        body {{
            font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
            color: #1f1f1f;
            background: #f4f4f5;
            line-height: 1.5;
            padding: 2.5rem 1.5rem 4rem;
        }}

        header {{ max-width: 1400px; margin: 0 auto 2.5rem; }}
        header h1 {{ font-size: 1.6rem; font-weight: 600; letter-spacing: -0.01em; }}
        header p {{ color: #555; margin-top: 0.4rem; font-size: 0.95rem; }}

        .screen {{
            max-width: 1400px;
            margin: 0 auto 3rem;
            background: #fff;
            border: 1px solid #e2e2e4;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }}

        .screen-head {{
            display: flex;
            align-items: baseline;
            gap: 0.75rem;
            padding: 1rem 1.5rem 0.4rem;
        }}

        .step-number {{
            flex: none;
            width: 1.9rem;
            height: 1.9rem;
            border-radius: 50%;
            background: #1f1f1f;
            color: #fff;
            font-weight: 600;
            font-size: 0.95rem;
            display: inline-flex;
            align-items: center;
            justify-content: center;
        }}

        .screen-title {{ font-size: 1.2rem; font-weight: 600; }}
        .screen-source {{
            margin-left: auto;
            font-family: ui-monospace, "SF Mono", Menlo, monospace;
            font-size: 0.8rem;
            color: #888;
        }}

        .screen-desc {{ padding: 0 1.5rem 1rem; color: #555; font-size: 0.92rem; max-width: 78ch; }}
        .screen-desc code, .under-hood code, .flow-body code {{
            font-family: ui-monospace, "SF Mono", Menlo, monospace;
            font-size: 0.85em;
            background: #f0f0f2;
            padding: 0.05em 0.35em;
            border-radius: 3px;
        }}

        .image-frame {{ background: #fafafa; border-top: 1px solid #eee; padding: 1.25rem; text-align: center; }}
        .image-frame img {{
            display: block;
            width: 100%;
            height: auto;
            max-width: 1280px;
            margin: 0 auto;
            background: #fff;
            border: 1px solid #ededed;
        }}

        .under-hood {{ padding: 1.25rem 1.5rem 1.5rem; border-top: 1px solid #eee; background: #fcfcfd; }}
        .under-hood h3 {{
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #999;
            margin-bottom: 0.5rem;
        }}
        .under-hood p {{ font-size: 0.92rem; color: #444; max-width: 78ch; margin-bottom: 0.9rem; }}

        table.files {{ border-collapse: collapse; width: 100%; max-width: 760px; font-size: 0.88rem; }}
        table.files th {{
            text-align: left;
            font-weight: 600;
            color: #777;
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            padding: 0.3rem 0.75rem 0.3rem 0;
            border-bottom: 1px solid #e6e6e8;
        }}
        table.files td {{ padding: 0.4rem 0.75rem 0.4rem 0; border-bottom: 1px solid #f0f0f2; vertical-align: top; color: #444; }}
        table.files td:first-child {{ white-space: nowrap; width: 1%; }}

        /* Step 5 — publish workflow flow */
        .workflow-note {{
            margin: 0 1.5rem 0.5rem;
            padding: 0.85rem 1.1rem;
            background: #f1eefc;
            border: 1px solid #ddd4f5;
            border-left: 3px solid #6A4FD0;
            border-radius: 5px;
            font-size: 0.9rem;
            color: #3c3357;
            max-width: 80ch;
        }}
        .workflow .flow {{ list-style: none; padding: 1.25rem 1.5rem 1.75rem; }}
        .flow-step {{ display: flex; gap: 1rem; align-items: flex-start; position: relative; padding-bottom: 1.5rem; }}
        .flow-step:last-child {{ padding-bottom: 0; }}
        /* connector line between numbered nodes */
        .flow-step:not(:last-child)::before {{
            content: "";
            position: absolute;
            left: 1.1rem;
            top: 2.4rem;
            bottom: 0;
            width: 2px;
            background: #dcdce0;
        }}
        .flow-num {{
            flex: none;
            width: 2.2rem;
            height: 2.2rem;
            border-radius: 50%;
            background: #6A4FD0;
            color: #fff;
            font-weight: 700;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            z-index: 1;
        }}
        .flow-body {{ font-size: 0.92rem; color: #444; padding-top: 0.2rem; max-width: 80ch; }}
        .flow-body strong {{ color: #1f1f1f; }}

        @media print {{
            body {{ background: #fff; padding: 0; }}
            .screen {{ box-shadow: none; border-color: #ccc; page-break-inside: avoid; margin-bottom: 1.5rem; }}
        }}
    </style>
</head>
<body>
    <header>
        <h1>Brain-Map Poster — Input Screens &amp; Publish Workflow</h1>
        <p>The four source layers used to build the poster (full resolution, 2752&times;2064, for annotation),
        each with what the code does and which files are responsible — then the end-to-end publish flow.</p>
    </header>
{screens_html}
{workflow_html}
</body>
</html>
"""


def main() -> None:
    OUTPUT_PATH.write_text(build_html(), encoding="utf-8")
    size_mb = OUTPUT_PATH.stat().st_size / (1024 * 1024)
    print(f"Wrote {OUTPUT_PATH} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
