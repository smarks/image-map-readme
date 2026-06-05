# image-map-readme — task runner.
# Install `just` with: brew install just   (then run `just` to list recipes)

# Show available recipes
default:
    @just --list

# Build all artifacts (svg, html, png, pdf) from poster-content.json
build:
    python3 build_poster.py

# Build everything except the print PDF (faster)
quick:
    python3 build_poster.py --no-pdf

# Rebuild automatically whenever you save the content file or brain art
watch:
    python3 build_poster.py --watch

# Build, then open the interactive page in your browser
preview: build
    open spencer-brain-poster.html

# Open the print-ready PDF
pdf: build
    open spencer-brain-poster.pdf

# Build without snapshotting a timestamped copy into print/
draft:
    python3 build_poster.py --no-archive

# Re-detect clickable hotspots after editing the art (prints boxes to paste)
hotspots image="sample-brain.png":
    python3 find_brain_links.py "{{image}}"

# Regenerate the demo image + example content (sample-brain.png + the example file)
sample:
    python3 make_sample.py

# Verify every marker box lands on its target (writes review crops to verify/)
verify filter="":
    python3 verify_markers.py "{{filter}}"

# Open the print/ archive of timestamped PDF snapshots
prints:
    open print

# Remove generated artifacts (sources and the print/ archive are left untouched)
clean:
    rm -f spencer-brain-poster.svg spencer-brain-poster.html \
          spencer-brain-poster.png spencer-brain-poster.pdf brain-web.png

# Delete the timestamped PDF snapshots in print/ (irreversible)
clean-prints:
    rm -rf print
