"""Patch composition: fonts, line layout, drawing. Used by both preview and apply, so the
preview is exactly what gets written.

A patch spec (dict):
  rect      [x0,y0,x1,y1]  box the user drew (cover area; alignment box for center/right)
  fill      [r,g,b] | None cover colour (None = don't cover)
  text      str            lines separated by \n
  font      str            "helv"/"hebo"/... (standard) or "sys:<n>" (installed font id from fonts())
  size      float pt
  color     [r,g,b]
  x         float | None   where the first letter's INK starts (left align); None = box left
  baseline  float | None   first line's baseline; None = centred in the box
  pitch     float | None   line spacing (baseline to baseline), default 1.2 * size
  hscale    float          horizontal scale (1 = normal)
  spacing   float pt       extra space between letters
  align     left|center|right
  fit       bool           shrink to stay inside the box
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

import pymupdf

STANDARD = [
    ("Sans", {"r": "helv", "b": "hebo", "i": "heit", "bi": "hebi"}),
    ("Serif", {"r": "tiro", "b": "tibo", "i": "tiit", "bi": "tibi"}),
    ("Mono", {"r": "cour", "b": "cobo", "i": "coit", "bi": "cobi"}),
]
_FONT_DIRS = ["/System/Library/Fonts/Supplemental", "/System/Library/Fonts", "/Library/Fonts",
              str(Path.home() / "Library/Fonts")]
_STYLE = re.compile(r"[\s_-]*(Bold Italic|BoldItalic|Bold Oblique|Bold|Italic|Oblique|Regular)$", re.I)


@lru_cache(maxsize=1)
def _installed() -> tuple[list, dict]:
    """[(family, {style: id})], {id: path} from .ttf/.otf files (style parsed from the file name)."""
    fams: dict[str, dict] = {}
    paths: dict[str, str] = {}
    seen = set()
    for d in _FONT_DIRS:
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.lower().endswith((".ttf", ".otf")) or f in seen:
                continue
            seen.add(f)
            stem = Path(f).stem
            m = _STYLE.search(stem)
            style = (m.group(1).lower() if m else "regular").replace(" ", "")
            fam = _STYLE.sub("", stem).strip() or stem
            key = {"regular": "r", "bold": "b", "italic": "i", "oblique": "i",
                   "bolditalic": "bi", "boldoblique": "bi"}.get(style, "r")
            fid = f"sys:{len(paths)}"
            paths[fid] = os.path.join(d, f)
            fams.setdefault(fam, {}).setdefault(key, fid)
    out = [(name, st) for name, st in sorted(fams.items(), key=lambda kv: kv[0].lower()) if "r" in st or "b" in st]
    return out, paths


def fonts() -> list[dict]:
    inst, _ = _installed()
    return ([{"name": n, "styles": s, "std": True} for n, s in STANDARD] +
            [{"name": n, "styles": s, "std": False} for n, s in inst])


@lru_cache(maxsize=64)
def get_font(fid: str) -> pymupdf.Font:
    if fid.startswith("sys:"):
        path = _installed()[1].get(fid)
        if not path:
            raise ValueError(f"unknown font {fid}")
        return pymupdf.Font(fontfile=path)
    return pymupdf.Font(fid)


@lru_cache(maxsize=4096)
def _lsb_em(fid: str, ch: str) -> float:
    """Left side bearing in em, measured from a render (MuPDF's glyph_bbox returns the font bbox
    for many installed fonts, which would shift text by ~0.6em)."""
    font = get_font(fid)
    doc = pymupdf.open(); pg = doc.new_page(width=300, height=200)
    tw = pymupdf.TextWriter(pg.rect); tw.append((100, 150), ch, font=font, fontsize=100); tw.write_text(pg)
    pix = pg.get_pixmap(alpha=False, colorspace=pymupdf.csGRAY)
    w = pix.width
    cols = [x for x in range(w) if any(pix.samples[y * w + x] < 128 for y in range(0, pix.height, 2))]
    return (cols[0] - 100) / 100 if cols else 0.0


def _advance(font, line, size, spacing):
    if not line:
        return 0.0
    return sum(font.glyph_advance(ord(c)) * size for c in line) + spacing * (len(line) - 1)


def layout(spec) -> dict:
    """Where every line goes. Returns {font, size, lines:[(ox, oy, text)], bbox}."""
    font = get_font(spec.get("font") or "helv")
    text = spec.get("text") or ""
    missing = sorted({c for c in text if not c.isspace() and not font.has_glyph(ord(c))})
    if missing:
        raise ValueError(f"{font.name} has no glyph for: {''.join(missing[:10])}")
    size = float(spec.get("size") or 11)
    hs = float(spec.get("hscale") or 1.0)
    sp = float(spec.get("spacing") or 0.0)
    align = spec.get("align") or "left"
    r = pymupdf.Rect(spec["rect"])
    lines = text.split("\n")
    x, baseline = spec.get("x"), spec.get("baseline")
    if baseline is None:
        baseline = r.y0 + (r.height - size) / 2 + font.ascender * size * 0.95
    if x is None:
        x = r.x0 + 1

    def widths(sz):
        return [_advance(font, ln, sz, sp) * hs for ln in lines]

    if spec.get("fit"):
        room = (r.x1 - x - 1) if align == "left" else (r.width - 2)
        widest = max(widths(size) or [0])
        if widest > room > 0:
            size *= room / widest
    pitch = float(spec.get("pitch") or size * 1.2)
    placed, x0s, x1s = [], [], []
    for k, (ln, w) in enumerate(zip(lines, widths(size))):
        first = ln.lstrip()[:1]
        lsb = _lsb_em(spec.get("font") or "helv", first) * size * hs if first else 0
        if align == "center":
            ox = (r.x0 + r.x1) / 2 - w / 2
        elif align == "right":
            ox = r.x1 - 1 - w
        else:
            ox = x - lsb  # x is where INK starts: back off the first letter's side bearing
        oy = baseline + k * pitch
        placed.append((ox, oy, ln))
        x0s.append(ox); x1s.append(ox + w)
    asc, desc = font.ascender * size, -font.descender * size
    bbox = pymupdf.Rect(min(x0s), baseline - asc, max(x1s), baseline + (len(lines) - 1) * pitch + desc)
    return {"font": font, "size": size, "hscale": hs, "spacing": sp, "lines": placed, "bbox": bbox}


def draw(page: pymupdf.Page, spec) -> pymupdf.Rect:
    """Cover + write. Returns the area touched (for preview clipping)."""
    r = pymupdf.Rect(spec["rect"])
    touched = pymupdf.Rect(r)
    if spec.get("fill") is not None:
        page.draw_rect(r, color=None, fill=spec["fill"], overlay=True, width=0)
    if not (spec.get("text") or "").strip():
        return touched
    L = layout(spec)
    font, size, hs, sp = L["font"], L["size"], L["hscale"], L["spacing"]
    color = spec.get("color") or [0, 0, 0]
    for ox, oy, ln in L["lines"]:
        if not ln:
            continue
        tw = pymupdf.TextWriter(page.rect)
        if sp:  # letter spacing: place glyphs one by one (in unscaled space; morph scales positions too)
            cx = ox
            for c in ln:
                tw.append((cx, oy), c, font=font, fontsize=size)
                cx += font.glyph_advance(ord(c)) * size + sp / hs
        else:
            tw.append((ox, oy), ln, font=font, fontsize=size)
        morph = (pymupdf.Point(ox, oy), pymupdf.Matrix(hs, 1)) if abs(hs - 1) > 1e-3 else None
        tw.write_text(page, color=color, morph=morph)
    return touched | L["bbox"]


def preview(doc: pymupdf.Document, pno: int, spec, zoom: float):
    """The new text alone, as a transparent PNG, drawn by the same code as apply. The UI lays it over
    the page above a flat cover box (the cover is a plain fill, so that composite == the applied result).
    Returns (clip, png) or (None, None) when there's no text."""
    if not (spec.get("text") or "").strip():
        return None, None
    src = doc[pno].rect
    tmp = pymupdf.open()
    pg = tmp.new_page(width=src.width, height=src.height)
    L = layout(spec)
    draw(pg, {**spec, "fill": None})
    area = (L["bbox"] + (-2, -2, 2, 2)) & pg.rect
    pix = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=area, alpha=True)
    return [area.x0, area.y0, area.x1, area.y1], pix.tobytes("png")
