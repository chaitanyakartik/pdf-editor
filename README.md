# Redline: edit the text in a PDF, nothing else

Local tool. Click any text in a PDF, retype it, and download. Headers, footers, stamps, logos,
backgrounds and every other line on the page stay where they were.

```sh
./run.sh            # -> http://localhost:43063  (port from ops/tools/port.py personal pdf-editor)
./run.sh file.pdf   # opens with that file loaded
```

## Modes
- **Edit text**: click a text run → type → Enter. Same baseline, size and colour. Font order: the PDF's own
  embedded font (if it has every glyph you typed and its metrics check out) → same-named installed font →
  look-alike standard font (toast warns) → any installed font covering the script (Kannada, Devanagari…).
  **Fit width** shrinks new text that's longer than the original.
- **Patch**: for scans or text baked into an image. Drag a box. It's filled with the most common colour on its
  border (the paper) and you type over it. Untick *Cover* to just add text.
- ⌘Z / ⌘⇧Z undo/redo (50 steps). `E` / `P` switch modes.

## How it works (engine.py)
Removes only the touched glyphs with a PyMuPDF redaction whose rect is a thin band inside the span
(`images=NONE, graphics=NONE`), so images and vector art are untouched, then writes the new string at the same
origin with `TextWriter`. After each edit it re-extracts the page and reports any *other* text that changed.

## Tests
- `tests/pixel_diff.py <pdfs…>`: edits 6 spans per PDF and counts changed pixels outside the edited boxes.
  2026-11-09 over 21 real PDFs: 0 collateral text, 0 stray pixels on 20/21. The one exception: MuPDF rewrites the
  content stream on redaction (absolute `Tm` → relative `TD`, e.g. `99.99996`), shifting one unrelated line by ~0.1pt.
  That's sub-pixel and not visible.
- `tests/ui_e2e.py <outdir>`: drives the UI in headless Chromium (edit, patch, undo) with the server running on `tests/fixture.pdf`.
- `tests/make_fixture.py`: builds the fixture (header bar, highlight box, image, stamp, mixed bold/regular, rotated text).

## Limits
- Rotated/vertical text: not click-editable (use Patch).
- Scanned pages have no text layer, so Patch is the only option there.
- One text run = one style. A run that mixes bold and regular is split by the PDF into separate runs; edit each.
