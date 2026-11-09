"""PDF text-editing engine.

Edits only the text you touch. Everything else (images, stamps, vector art,
headers/footers, annotations, other text) is left byte-for-byte alone:

  1. Find the text span (rawdict gives per-glyph boxes + baseline origin).
  2. Remove just those glyphs with a redaction whose rect is a thin band
     inside the span, with images/line-art/other-text untouched.
  3. Write the new string at the same baseline origin, size and colour, in
     the original embedded font if it has the glyphs, else the closest
     system font, else a base-14 font.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pymupdf

# ---------------------------------------------------------------- fonts

_SUBSET = re.compile(r"^[A-Z]{6}\+")
_FONT_DIRS = ["/System/Library/Fonts", "/System/Library/Fonts/Supplemental",
              "/Library/Fonts", str(Path.home() / "Library/Fonts"),
              "/usr/share/fonts", "C:/Windows/Fonts"]


def _norm(name: str) -> str:
    # "ABCDEF+TimesNewRomanPS-BoldMT" -> "timesnewromanbold"; "Arial Bold.ttf" -> "arialbold"
    name = _SUBSET.sub("", name or "")
    name = re.sub(r"(PSMT|MT|PS)(?=$|[-,])", "", name)
    return re.sub(r"[^a-z0-9]", "", name.lower()).replace("regular", "")


_SYS_FONTS: dict[str, str] | None = None


def _system_fonts() -> dict[str, str]:
    global _SYS_FONTS
    if _SYS_FONTS is None:
        _SYS_FONTS = {}
        for d in _FONT_DIRS:
            if not os.path.isdir(d):
                continue
            for root, _, files in os.walk(d):
                for f in files:
                    if f.lower().endswith((".ttf", ".otf")):
                        _SYS_FONTS.setdefault(_norm(Path(f).stem), os.path.join(root, f))
    return _SYS_FONTS


def _base14(span) -> str:
    flags, name = span["flags"], span["font"].lower()
    bold = bool(flags & 16) or "bold" in name or "black" in name or "heavy" in name
    italic = bool(flags & 2) or "italic" in name or "oblique" in name
    mono = bool(flags & 8) or "courier" in name or "mono" in name
    serif = bool(flags & 4) or "times" in name or "serif" in name and "sans" not in name
    fam = "co" if mono else ("ti" if serif else "he")
    if fam == "ti":
        return {(0, 0): "tiro", (1, 0): "tibo", (0, 1): "tiit", (1, 1): "tibi"}[(bold, italic)]
    if fam == "co":
        return {(0, 0): "cour", (1, 0): "cobo", (0, 1): "coit", (1, 1): "cobi"}[(bold, italic)]
    return {(0, 0): "helv", (1, 0): "hebo", (0, 1): "heit", (1, 1): "hebi"}[(bold, italic)]


def _covers(font: pymupdf.Font, text: str) -> bool:
    return all(c.isspace() or font.has_glyph(ord(c)) for c in text)


def _width_ok(font: pymupdf.Font, span) -> bool:
    """Sanity check that the font's unicode->glyph map and metrics are real:
    the original string must come out at (nearly) the original width."""
    txt = span["text"]
    if not txt.strip():
        return True
    w = font.text_length(txt, fontsize=span["size"])
    ow = span["bbox"][2] - span["bbox"][0]
    return ow > 0 and abs(w - ow) / ow < 0.06


def pick_font(doc: pymupdf.Document, page: pymupdf.Page, span, new_text: str):
    """Return (Font, source) where source in {'embedded','system','base14'}."""
    target = _SUBSET.sub("", span["font"])
    # 1) the font actually embedded in the PDF
    for xref, ext, _typ, basefont, *_ in page.get_fonts(full=True):
        if _SUBSET.sub("", basefont) != target or ext == "n/a":
            continue
        try:
            _, _, _, buf = doc.extract_font(xref)
            if buf:
                f = pymupdf.Font(fontbuffer=buf)
                if _covers(f, new_text) and _covers(f, span["text"]) and _width_ok(f, span):
                    return f, "embedded"
        except Exception:
            pass
    # 2) same-named font installed on this machine
    path = _system_fonts().get(_norm(target))
    if path:
        try:
            f = pymupdf.Font(fontfile=path)
            if _covers(f, new_text):
                return f, "system"
        except Exception:
            pass
    # 3) base-14 by style
    f = pymupdf.Font(_base14(span))
    if _covers(f, new_text):
        # non-embedded standard fonts (Helvetica, Times, Courier, Arial*) render as exactly this
        std = re.sub(r"[^a-z]", "", target.lower()).split("bold")[0].split("italic")[0].split("oblique")[0]
        same = std in ("helvetica", "times", "timesroman", "courier", "arial", "arialmt", "timesnewroman")
        return f, "standard" if same else "base14"
    # 4) non-Latin text (Kannada, Devanagari, ...): any installed font that has every glyph
    for path in sorted(_system_fonts().values(), key=lambda p: ("Noto" not in p, "Unicode" not in p, p)):
        try:
            f = pymupdf.Font(fontfile=path)
            if _covers(f, new_text):
                return f, "system"
        except Exception:
            continue
    raise ValueError("no installed font has glyphs for: " + new_text)


# ---------------------------------------------------------------- spans

def get_spans(page: pymupdf.Page) -> list[dict]:
    out = []
    raw = page.get_text("rawdict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP)
    for b in raw["blocks"]:
        if b.get("type") != 0:
            continue
        for line in b["lines"]:
            dx, dy = line["dir"]
            horizontal = abs(dy) < 1e-3 and dx > 0
            for s in line["spans"]:
                chars = s["chars"]
                text = "".join(c["c"] for c in chars)
                if not text.strip():
                    continue
                out.append({
                    "id": len(out),
                    "text": text,
                    "font": s["font"],
                    "size": round(s["size"], 2),
                    "flags": s["flags"],
                    "color": s["color"],
                    "origin": list(s["origin"]),
                    "bbox": list(s["bbox"]),
                    "chars": [list(c["bbox"]) for c in chars],
                    "editable": horizontal,
                    "alpha": s.get("alpha", 255),
                })
    return out


def _rgb(c: int):
    return ((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255


def _kill_rect(span) -> pymupdf.Rect:
    """Thin band through the middle of the glyphs, inset at both ends, so the
    redaction catches exactly this span's glyphs and never a neighbour's."""
    chars = [c for c in span["chars"]]
    x0, x1 = chars[0][0], chars[-1][2]
    w0 = max(chars[0][2] - chars[0][0], 0.5)
    w1 = max(chars[-1][2] - chars[-1][0], 0.5)
    oy = span["origin"][1]
    sz = span["size"]
    return pymupdf.Rect(x0 + 0.3 * w0, oy - 0.55 * sz, x1 - 0.3 * w1, oy - 0.15 * sz)


def _other_text(spans, skip_id):
    return sorted(s["text"] for s in spans if s["id"] != skip_id)


def edit_span(doc: pymupdf.Document, pno: int, span_id: int, new_text: str, fit: bool = False) -> dict:
    page = doc[pno]
    spans = get_spans(page)
    span = next(s for s in spans if s["id"] == span_id)
    if not span["editable"]:
        raise ValueError("rotated/vertical text is not editable")

    font, source = pick_font(doc, page, span, new_text) if new_text.strip() else (None, "none")
    before = _other_text(spans, span_id)

    page.add_redact_annot(_kill_rect(span))
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)

    size = span["size"]
    if font is not None:
        orig_w = span["bbox"][2] - span["bbox"][0]
        new_w = font.text_length(new_text, fontsize=size)
        if fit and new_w > orig_w > 0:
            size *= orig_w / new_w
        tw = pymupdf.TextWriter(page.rect)
        tw.append(pymupdf.Point(span["origin"]), new_text, font=font, fontsize=size)
        tw.write_text(page, color=_rgb(span["color"]),
                      opacity=span["alpha"] / 255 if span["alpha"] < 255 else -1)

    # collateral check: did any other text on the page change?
    after_spans = get_spans(page)
    after_all = sorted(s["text"] for s in after_spans)
    missing = list(before)
    for t in after_all:
        if t in missing:
            missing.remove(t)
    if new_text.strip() and new_text in missing:
        missing.remove(new_text)
    return {"font_source": source, "font": span["font"], "size": round(size, 2),
            "collateral": [m for m in missing if m.strip()][:5]}


def patch(doc: pymupdf.Document, pno: int, rect, fill, text: str, size: float, color, fontname="helv",
          x=None, baseline=None, pitch=None, fit=False, hscale=1.0) -> None:
    """For scans / image text: paint a box (fill=None for transparent) and write text in it.
    With x/baseline (from scan.analyze: x = left edge of the ink) the text sits exactly where the old text was."""
    page = doc[pno]
    r = pymupdf.Rect(rect)
    if fill is not None:
        page.draw_rect(r, color=None, fill=fill, overlay=True, width=0)
    if not text.strip():
        return
    font = pymupdf.Font(fontname)
    lines = text.split("\n")
    if baseline is None:  # nothing detected: centre the first line in the box
        x, baseline = r.x0 + 1, r.y0 + (r.height - size) / 2 + font.ascender * size * 0.95
        fit = True
    widest = max(font.text_length(l, fontsize=size) for l in lines) * hscale
    room = r.x1 - x - 1
    if fit and widest > room > 0:
        size *= room / widest
    pitch = pitch or size * 1.2
    tw = pymupdf.TextWriter(page.rect)
    for k, line in enumerate(lines):
        # x is where INK starts (measured off the scan); shift back by the first letter's left bearing
        first = line.lstrip()[:1]
        lsb = font.glyph_bbox(ord(first)).x0 * size * hscale if first and font.has_glyph(ord(first)) else 0
        tw.append((x - lsb, baseline + k * pitch), line, font=font, fontsize=size)
    # horizontal scaling around the text's start point (narrow/wide typefaces on scans)
    morph = (pymupdf.Point(x, baseline), pymupdf.Matrix(hscale, 1)) if abs(hscale - 1) > 1e-3 else None
    tw.write_text(page, color=color, morph=morph)
