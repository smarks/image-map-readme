# PosterSans — embedded poster font

`PosterSans-{Regular,Bold,Italic}.ttf` are **derived from Liberation Sans 2.1.5**
(© 2012 Red Hat, Inc.; digitized data © 2010 Google Corporation), licensed under
the SIL Open Font License 1.1 (see `LICENSE`).

Modifications made for this project:
- **Subset** to Latin + common punctuation (Basic Latin, Latin-1, dashes, curly
  quotes, bullet, ellipsis, primes, €, ™, Œœ) to keep the embedded size tiny.
- **Renamed** the font family from "Liberation Sans" to "PosterSans". The OFL
  reserves the name "Liberation" for the original, so a modified build must not
  carry it.

Why embedded: `build_poster.py` measures text with this exact file to wrap and
size the cards, and the page renders with this exact file via `@font-face`. Same
bytes for measurement and rendering means card text fits on every device, with no
dependence on whatever fonts the viewer happens to have installed.
