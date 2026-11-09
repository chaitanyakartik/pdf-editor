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


class _Style:
    def __init__(self, spec):
        self.fid = spec.get("font") or "helv"
        self.font = get_font(self.fid)
        self.size = float(spec.get("size") or 11)
        self.hs = float(spec.get("hscale") or 1.0)
        self.sp = float(spec.get("spacing") or 0.0)

    def width(self, s: str) -> float:
        return _advance(self.font, s, self.size, self.sp) * self.hs

    def lsb(self, s: str) -> float:
        first = s.lstrip()[:1]
        return _lsb_em(self.fid, first) * self.size * self.hs if first else 0.0


def _wrap(st: _Style, text: str, width: float | None) -> list[str]:
    """Greedy word wrap to `width` pt (None = no wrap). A word longer than the width gets its own line."""
    if width is None or width <= 0:
        return [text]
    words, out, cur = text.split(), [], ""
    for w in words:
        t = f"{cur} {w}" if cur else w
        if cur and st.width(t) > width:
            out.append(cur); cur = w
        else:
            cur = t
    out.append(cur)
    return out


def _paragraphs(L: list, pitch: float) -> list[int]:
    """Paragraph id per original line: a new paragraph starts after a blank-line gap, when a line is
    indented relative to the body, or after a short line."""
    xs = sorted(l["x"] for l in L)
    body = min(xs, key=lambda x: -sum(abs(x - y) < 2 for y in xs))  # most common left edge
    right = max(l["box"][2] for l in L)
    pid, out = 0, [0]
    for i in range(1, len(L)):
        gap = L[i]["baseline"] - L[i - 1]["baseline"]
        short_prev = L[i - 1]["box"][2] < right - 0.15 * (right - body)
        if gap > 1.45 * pitch or L[i]["x"] > body + 5 or short_prev:
            pid += 1
        out.append(pid)
    return out


def plan(spec) -> dict:
    """What gets covered and what gets written; preview and apply both use this.
    Returns {style, covers:[rect], lines:[{x, y, text, just}], retyped, warn}.
      x = where the line's INK starts, y = baseline, just = right edge to justify to (or None)."""
    st = _Style(spec)
    text = spec.get("text") or ""
    missing = sorted({c for c in text if not c.isspace() and not st.font.has_glyph(ord(c))})
    if missing:
        raise ValueError(f"{st.font.name} has no glyph for: {''.join(missing[:10])}")
    r = pymupdf.Rect(spec["rect"])
    fill = spec.get("fill")
    wrap = spec.get("wrap")
    justify = (spec.get("align") == "justify")
    orig = spec.get("orig") or []
    out = {"style": st, "covers": [], "lines": [], "retyped": 0, "warn": None}

    if len(orig) < 2:
        # ---- one box: cover it, write the text from (x, baseline), wrapping at the wrap edge
        if fill is not None:
            out["covers"].append([r.x0, r.y0, r.x1, r.y1])
        x, y = spec.get("x"), spec.get("baseline")
        if y is None:
            y = r.y0 + (r.height - st.size) / 2 + st.font.ascender * st.size * 0.95
        if x is None:
            x = r.x0 + 1
        if spec.get("fit") and not wrap:
            widest = max([st.width(l) for l in text.split("\n")] or [0])
            room = r.x1 - x - 1
            if widest > room > 0:
                st.size *= room / widest
        pitch = float(spec.get("pitch") or st.size * 1.2)
        k = 0
        for para in text.split("\n"):
            rows = _wrap(st, para, (wrap - x) if wrap else None)
            for j, row in enumerate(rows):
                w = st.width(row)
                align = spec.get("align") or "left"
                ix = (r.x0 + r.x1) / 2 - w / 2 if align == "center" else (r.x1 - 1 - w if align == "right" else x)
                out["lines"].append({"x": ix, "y": y + k * pitch, "text": row,
                                     "just": wrap if justify and j < len(rows) - 1 else None})
                k += 1
        out["retyped"] = 1 if text.strip() else 0
        return out

    # ---- several OCR'd lines: re-type only what changed, reflowing within the paragraph
    L = orig
    new = text.split("\n")
    old = [l["text"].strip() for l in L]
    base = spec.get("base") or [min(l["x"] for l in L), L[0]["baseline"]]
    offx = (spec.get("x") if spec.get("x") is not None else base[0]) - base[0]
    offy = (spec.get("baseline") if spec.get("baseline") is not None else base[1]) - base[1]
    diffs = [L[i + 1]["baseline"] - L[i]["baseline"] for i in range(len(L) - 1)]
    pitch = float(spec.get("pitch") or (sorted(diffs)[len(diffs) // 2] if diffs else st.size * 1.2))
    right = wrap if wrap else max(l["box"][2] for l in L)
    para = _paragraphs(L, pitch)

    def cover(i):
        b = L[i]["box"]
        up = (b[1] - L[i - 1]["box"][3]) / 2 if i > 0 else 2
        dn = (L[i + 1]["box"][1] - b[3]) / 2 if i < len(L) - 1 else 2
        return [b[0] - 1, b[1] - max(0.3, min(6, up)), b[2] + 1, b[3] + max(0.3, min(6, dn))]

    def put(i_or_y, txt, x, last_in_para):
        y = L[i_or_y]["baseline"] if isinstance(i_or_y, int) else i_or_y
        out["lines"].append({"x": x + offx, "y": y + offy, "text": txt,
                             "just": right + offx if justify and not last_in_para else None})

    if len(new) != len(old):
        # lines added/removed: re-flow everything from the first difference
        f = 0
        while f < min(len(new), len(old)) and new[f].strip() == old[f]:
            f += 1
        for i in range(f, len(L)):
            if fill is not None:
                out["covers"].append(cover(i))
        a = L[min(f, len(L) - 1)]
        y = a["baseline"] if f < len(L) else a["baseline"] + pitch
        for t in new[f:]:
            rows = _wrap(st, t, right - a["x"])
            for j, row in enumerate(rows):
                out["lines"].append({"x": a["x"] + offx, "y": y + offy, "text": row,
                                     "just": right + offx if justify and j < len(rows) - 1 else None})
                y += pitch
        out["retyped"] = max(len(L) - f, len(new) - f)
        return out

    changed = [i for i in range(len(L)) if new[i].strip() != old[i]]
    done, extra_rows = set(), 0
    for c in changed:
        if c in done:
            continue
        p = para[c]
        last = max(i for i in range(len(L)) if para[i] == p)
        k, pending = c, new[c].split()
        while True:
            x = L[k]["x"] if k <= last else L[last]["x"]
            row = _wrap(st, " ".join(pending), right - x)
            line, left = row[0], " ".join(row[1:]).split()
            nxt = k + 1
            if k <= last:
                done.add(k)
                if fill is not None:
                    out["covers"].append(cover(k))
                # justify unless it's the paragraph's last line and nothing spills past it
                put(k, line, x, last_in_para=(k == last and not left))
            else:   # overflow past the paragraph's last line: into the gap below it
                y = L[last]["baseline"] + (k - last) * pitch
                put(y, line, x, last_in_para=not left)
                extra_rows += 1
            if not left:
                if nxt <= last and nxt in changed:
                    k, pending = nxt, new[nxt].split(); continue
                break
            # overflow pushes into the next line of the same paragraph (re-typed too)
            k, pending = nxt, left + (new[nxt].split() if nxt <= last else [])
    out["retyped"] = len(done) + extra_rows
    if extra_rows:
        nxt_base = None
        for i, l in enumerate(L):
            if any(i > j for j in done) and para[i] not in {para[j] for j in done}:
                nxt_base = l["baseline"]; break
        if nxt_base is not None:
            lowest = max(ln["y"] for ln in out["lines"])
            if lowest > nxt_base - pitch * 0.6:
                out["warn"] = f"{extra_rows} line(s) don't fit the paragraph and overlap the text below; shorten it or tick Shrink."
    return out


def _emit(page, st: _Style, ln, color):
    """Write one planned line. Justified lines place each word; letter spacing places each glyph."""
    x0 = ln["x"] - st.lsb(ln["text"])
    words = ln["text"].split(" ")
    gap_extra = 0.0
    if ln.get("just") and len(words) > 1:
        slack = (ln["just"] - ln["x"]) - st.width(ln["text"])
        if 0 < slack < 0.3 * (ln["just"] - ln["x"]):          # never stretch a near-empty line
            gap_extra = slack / (len(words) - 1)
    tw = pymupdf.TextWriter(page.rect)
    # positions are laid out in UNSCALED space; the morph applies horizontal scaling about x0
    cx = x0
    space = st.font.glyph_advance(32) * st.size + st.sp / st.hs
    for wi, w in enumerate(words):
        if st.sp:
            for ch in w:
                tw.append((cx, ln["y"]), ch, font=st.font, fontsize=st.size)
                cx += st.font.glyph_advance(ord(ch)) * st.size + st.sp / st.hs
        else:
            if w:
                tw.append((cx, ln["y"]), w, font=st.font, fontsize=st.size)
            cx += sum(st.font.glyph_advance(ord(ch)) * st.size for ch in w)
        cx += space + gap_extra / st.hs
    morph = (pymupdf.Point(x0, ln["y"]), pymupdf.Matrix(st.hs, 1)) if abs(st.hs - 1) > 1e-3 else None
    tw.write_text(page, color=color, morph=morph)


def _text_bbox(P) -> pymupdf.Rect | None:
    st = P["style"]
    asc, desc = st.font.ascender * st.size, -st.font.descender * st.size
    box = None
    for ln in P["lines"]:
        x1 = ln["just"] if ln.get("just") else ln["x"] + st.width(ln["text"])
        b = pymupdf.Rect(ln["x"] - 2, ln["y"] - asc, x1 + 2, ln["y"] + desc)
        box = b if box is None else box | b
    return box


def draw(page: pymupdf.Page, spec) -> dict:
    P = plan(spec)
    for c in P["covers"]:
        page.draw_rect(c, color=None, fill=spec["fill"], overlay=True, width=0)
    color = spec.get("color") or [0, 0, 0]
    for ln in P["lines"]:
        if ln["text"].strip():
            _emit(page, P["style"], ln, color)
    return P


def preview(doc: pymupdf.Document, pno: int, spec, zoom: float) -> dict:
    """Text alone as a transparent PNG (drawn by the same plan as apply) + the cover boxes; the UI
    shows covers as flat colour under the PNG, which composites to exactly the applied result."""
    P = plan(spec)
    res = {"covers": P["covers"], "retyped": P["retyped"], "warn": P["warn"], "clip": None, "png": None,
           "lines": len(P["lines"])}
    box = _text_bbox(P)
    if box is None:
        return res
    src = doc[pno].rect
    tmp = pymupdf.open()
    pg = tmp.new_page(width=src.width, height=src.height)
    color = spec.get("color") or [0, 0, 0]
    for ln in P["lines"]:
        if ln["text"].strip():
            _emit(pg, P["style"], ln, color)
    area = (box + (-2, -2, 2, 2)) & pg.rect
    pix = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=area, alpha=True)
    res.update(clip=[area.x0, area.y0, area.x1, area.y1], png=pix.tobytes("png"))
    return res
