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
- **Patch**: for scans or text baked into an image. Drag a box over the words. `scan.py` then:
  reads the existing words (Tesseract) and **prefills them** so you just edit; picks the font by rendering those
  words in 8 standard fonts and keeping the best pixel overlap; sets the size from the line's ink width; detects
  baseline, left edge, text colour and paper colour, so the new text lands exactly on the old one. If no
  standard font fits (a narrow typeface), it picks Sans or Sans Bold by stroke thickness, matches glyph height,
  and squeezes the width (PDF horizontal scaling). Untick *Cover* to just add text.
- **Reference box** (Patch mode: *Set reference*, `R`, or Shift-drag): drag over existing text first. Every patch after
  that copies its **left edge** (ink-to-ink, corrected for the first letter's side bearing), font, size, colour and line
  spacing. If the target box is empty and the reference has 2+ lines, the new line snaps onto the reference's line grid.
  The reference stays (green REF box + dashed left-edge guide) until you clear it. `tests/ui_ref.py` covers both cases.
  Checked on a scanned certificate (`tests/scan_check.py`, `tests/ui_patch_scan.py`): title, date, 4-line address and
  a bullet line re-patch near-identically (Sans, 58–64% overlap); a narrow-typeface footer gets the right width and
  height, but the letter shapes differ.
- ⌘Z / ⌘⇧Z undo/redo (50 steps). `E` / `P` switch modes.

## Patch panel (formatting + live preview)
Dragging a Patch box opens a panel on the right: text, font family (Sans/Serif/Mono + every .ttf/.otf installed
on the Mac), Bold/Italic, size, colour, width %, letter spacing, line spacing, align, exact Left/Baseline (pt), cover
colour, shrink-to-fit. Every change re-renders a **preview** over the page: a flat cover box plus the new text as a
transparent PNG drawn by the same `compose.draw` code as Apply (checked pixel-identical). Drag the previewed text or use
arrow keys (0.25pt, Shift = 2pt) to position it; it snaps to the reference's left edge and line grid. ⌘↵ applies.

**Multi-line boxes re-type only what you change.** OCR keeps each line's text, ink box, left edge and baseline
(bullets OCR misreads as "e" are left as pixels; "|" mid-line is read as "I"). The panel diffs your edit against
that: a changed line is covered by its own box (to half the gap to its neighbours) and re-typed at its own position;
unchanged lines stay original pixels, so indents, bullets and paragraph gaps survive. `tests/ui_bigbox.py`: box over
the whole letter body, edit one line → 0 changed pixels outside that line.

**Wrapping.** Text wraps at a fixed right margin (*Wrap at*, shown as a dashed WRAP line). Default: the right
margin of the paragraph(s) in the box, else the reference paragraph's, else the box edge. In a multi-line box an
edited line that gets too long pushes its overflow words into the next line of the same paragraph, which re-wraps,
until it settles; lines the reflow doesn't reach stay pixels. Paragraphs = blank-line gap, indent, or short line.
**Justify** (≡) is auto-detected when 2+ lines run flush to the margin; a paragraph's last line stays left.
`compose.plan()` decides covers + lines for both preview and apply. `tests/ui_wrap.py`: lengthen one justified line →
4 lines re-typed, 0 changed pixels outside that paragraph. Lines the box edge slices through are left as pixels.

**Dark Reader**: the page carries `<meta name="darkreader-lock">` and covers are canvas pixels; Dark Reader
recoloured the CSS-white cover box black (2026-11-09).

**Sessions** persist to `~/Library/Application Support/Redline/session.pkl` (doc + 20 undo steps) on every change;
`python app.py` with no file restores it. Test servers: `REDLINE_NO_SESSION=1 PORT=43070 python app.py <pdf>`.

## Move (`M`)
Box some text → it's lifted (ink as a transparent PNG, its old spot shown cleared) → drag it or use arrow keys,
snapping to the reference → Enter. On scans (an image under the box) the scanned pixels move, so it looks identical;
on real-text PDFs the text spans themselves move (same font, still selectable).

## How it works (engine.py)
Removes only the touched glyphs with a PyMuPDF redaction whose rect is a thin band inside the span
(`images=NONE, graphics=NONE`), so images and vector art are untouched, then writes the new string at the same
origin with `TextWriter`. After each edit it re-extracts the page and reports any *other* text that changed.

## Tests
- `tests/pixel_diff.py <pdfs…>`: edits 6 spans per PDF and counts changed pixels outside the edited boxes.
  2026-11-09 over 21 real PDFs: 0 collateral text, 0 stray pixels on 20/21. The one exception: MuPDF rewrites the
  content stream on redaction (absolute `Tm` → relative `TD`, e.g. `99.99996`), shifting one unrelated line by ~0.1pt.
  That's sub-pixel and not visible.
- `tests/ui_inspector.py <outdir> [url]`: reference + patch panel (formatting, preview, drag-snap) + Move, on a throwaway
  server (`PORT=43070 python app.py <scan>`), never on the live one.
- `tests/ui_e2e.py <outdir>`: drives the UI in headless Chromium (edit, patch, undo) with the server running on `tests/fixture.pdf`.
- `tests/make_fixture.py`: builds the fixture (header bar, highlight box, image, stamp, mixed bold/regular, rotated text).

## Limits
- Rotated/vertical text: not click-editable (use Patch).
- Scanned pages have no text layer, so Patch is the only option there. Patch fonts are the standard 14
  (Sans/Serif/Mono families), so a distinctive scanned typeface gets the right size and position, but the letter shapes won't match.
- Patch needs `tesseract` on PATH to prefill words (`brew install tesseract`); without it, size, font weight and colours are still detected.
- One text run = one style. A run that mixes bold and regular is split by the PDF into separate runs; edit each.
