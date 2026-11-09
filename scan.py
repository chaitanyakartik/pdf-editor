"""Read the text under a Patch box on a scanned/image page.

analyze(page, rect) -> {text, size, font, color, fill, lines:[{x, baseline}], pitch, ...}

1. Render the box at 4x, find the paper colour (most common colour on the border)
   and the ink (pixels far from it).
2. Split ink into text lines by empty rows; per line, baseline = bottom of the
   dense x-height band, left = first ink column.
3. OCR the box with Tesseract (TSV) for the existing words.
4. Font + size by rendering: draw the OCR'd first line in each candidate base-14
   font, scale it to the scanned line's ink width, and score pixel overlap (IoU)
   against the scan. Best overlap wins; its scale gives the point size.
   No OCR text -> size from the x-height and bold from stroke thickness.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile

import numpy as np
import pymupdf

Z = 4.0  # render zoom: 288 dpi
CANDIDATES = {"helv": "Sans", "hebo": "Sans Bold", "heit": "Sans Italic",
              "tiro": "Serif", "tibo": "Serif Bold", "tiit": "Serif Italic",
              "cour": "Mono", "cobo": "Mono Bold"}
TESSERACT = shutil.which("tesseract")


def _render(page, clip, zoom=Z) -> np.ndarray:
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False, colorspace=pymupdf.csRGB)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).astype(np.int16)


def _bg(img: np.ndarray) -> np.ndarray:
    border = np.concatenate([img[0], img[-1], img[:, 0], img[:, -1]])
    q = (border // 8)
    keys, inv, counts = np.unique(q, axis=0, return_inverse=True, return_counts=True)
    top = np.argmax(counts)
    return np.median(border[inv.ravel() == top], axis=0)


def _ink(img, bg) -> np.ndarray:
    return np.abs(img - bg).sum(axis=2) > 120


def _lines(mask: np.ndarray):
    """Row ranges of text lines (gaps of >=2 empty rows split lines)."""
    rows = mask.sum(axis=1)
    on = rows > max(1, 0.002 * mask.shape[1])  # ignore lone specks
    out, start, gap = [], None, 0
    for y, v in enumerate(on):
        if v:
            if start is None:
                start = y
            gap = 0
            end = y
        elif start is not None:
            gap += 1
            if gap >= 2:
                out.append((start, end)); start = None
    if start is not None:
        out.append((start, end))
    return [(a, b) for a, b in out if b - a >= 4]


def _line_metrics(mask, y0, y1):
    sub = mask[y0:y1 + 1]
    rows = sub.sum(axis=1).astype(float)
    dense = np.where(rows >= 0.45 * rows.max())[0]
    cols = np.where(sub.any(axis=0))[0]
    return {"top": y0, "bottom": y1, "xtop": y0 + int(dense[0]), "baseline": y0 + int(dense[-1]) + 1,
            "x0": int(cols[0]), "x1": int(cols[-1]) + 1}


def _stroke_ratio(mask, m):
    """Median horizontal ink run inside the x-height band / x-height."""
    band = mask[m["xtop"]:m["baseline"], m["x0"]:m["x1"]]
    runs = []
    for row in band:
        d = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
        s, e = np.where(d == 1)[0], np.where(d == -1)[0]
        runs.extend((e - s).tolist())
    xh = max(m["baseline"] - m["xtop"], 1)
    return float(np.median(runs)) / xh if runs else 0.0


def _ocr(img: np.ndarray, bg, single_line: bool) -> list[list[str]]:
    """Words per line via Tesseract TSV."""
    if not TESSERACT:
        return []
    rgb = img.astype(np.uint8)
    if bg.mean() < 110:  # light text on dark paper: invert so tesseract sees dark-on-light
        rgb = 255 - rgb
    pad = np.full((rgb.shape[0] + 40, rgb.shape[1] + 40, 3), 255, np.uint8)  # white margin helps tesseract
    pad[20:-20, 20:-20] = rgb
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        pymupdf.Pixmap(pymupdf.csRGB, pad.shape[1], pad.shape[0], pad.tobytes(), 0).save(f.name)
        r = subprocess.run([TESSERACT, f.name, "-", "--psm", "7" if single_line else "6", "tsv"],
                           capture_output=True, text=True, timeout=20)
    lines: dict = {}
    for row in r.stdout.splitlines()[1:]:
        c = row.split("\t")
        if len(c) == 12 and c[11].strip() and float(c[10]) > 20:
            lines.setdefault((c[2], c[3], c[4]), []).append(c[11])
    return list(lines.values())


def _ink_crop(mask):
    ys, xs = np.where(mask)
    return mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1] if len(ys) else None


def _resize(m, shape):
    h, w = shape
    yi = (np.arange(h) * m.shape[0] / h).astype(int)
    xi = (np.arange(w) * m.shape[1] / w).astype(int)
    return m[yi][:, xi]


def _match_font(target_line_mask, text, est_size):
    """Render `text` in each candidate at the scan's resolution; pick the best pixel overlap (IoU)
    after normalising both ink boxes. Returns the point size implied by ink width and by ink height."""
    tgt = _ink_crop(target_line_mask)
    if tgt is None or not text.strip():
        return None
    th, tw = tgt.shape
    zc = Z * est_size / 100  # candidate zoom so its pixels ~ match the scan's
    best, cands = None, {}
    for fname in CANDIDATES:
        font = pymupdf.Font(fname)
        doc = pymupdf.open(); pg = doc.new_page(width=font.text_length(text, 100) + 60, height=200)
        w = pymupdf.TextWriter(pg.rect); w.append((30, 140), text, font=font, fontsize=100); w.write_text(pg)
        cand = _ink_crop(_ink(_render(pg, None, zc), np.array([255, 255, 255])))
        if cand is None:
            continue
        ch, cw = cand.shape
        size_h = 100 * (th / Z) / (ch / zc)
        size_w = 100 * (tw / Z) / (cw / zc)
        a = _resize(cand, tgt.shape)
        iou = float((a & tgt).sum() / max((a | tgt).sum(), 1))
        cands[fname] = {"iou": round(iou, 3), "size_w": size_w, "size_h": size_h}
        if best is None or iou > best["iou"]:
            best = {"font": fname, "size_w": size_w, "size_h": size_h, "iou": iou}
    best["cands"] = cands
    return best


def analyze(page: pymupdf.Page, rect) -> dict:
    r = pymupdf.Rect(rect)
    m = 2  # pt margin so the border samples paper, not the text being covered
    outer = (r + (-m, -m, m, m)) & page.rect
    img = _render(page, outer)
    bg = _bg(img)
    # analyse only inside the user's box
    ox, oy = int(round((r.x0 - outer.x0) * Z)), int(round((r.y0 - outer.y0) * Z))
    inner = img[oy:oy + int(r.height * Z), ox:ox + int(r.width * Z)]
    mask = _ink(inner, bg)
    out = {"fill": (bg / 255).round(3).tolist(), "text": "", "font": "helv", "size": None,
           "color": [0, 0, 0], "lines": [], "pitch": None, "ocr": bool(TESSERACT)}
    if mask.sum() < 20:
        return out  # empty box

    # text colour: the darkest-quarter of ink by distance from paper (skips anti-aliased edges)
    dist = np.abs(inner - bg).sum(axis=2)
    core = inner[mask & (dist >= np.percentile(dist[mask], 75))]
    out["color"] = (np.median(core, axis=0) / 255).round(3).tolist()

    lines = [_line_metrics(mask, a, b) for a, b in _lines(mask)]
    if not lines:
        return out
    out["lines"] = [{"x": r.x0 + l["x0"] / Z, "baseline": r.y0 + l["baseline"] / Z} for l in lines]
    if len(lines) > 1:
        out["pitch"] = float(np.median(np.diff([l["baseline"] for l in lines]))) / Z

    words = _ocr(inner, bg, single_line=len(lines) == 1)
    # drop bullet/border fragments OCR picks up at a box edge ("| End Date", "• Start")
    out["text"] = "\n".join(" ".join(w).lstrip("|•·¦ ").rstrip("| ") for w in words)

    first = lines[0]
    xh = first["baseline"] - first["xtop"]
    # only the band letters can occupy (ascenders..descenders) so stray marks/logos above don't count
    top = max(first["top"], first["baseline"] - int(1.6 * xh))
    bot = min(first["bottom"], first["baseline"] + int(0.7 * xh))
    band = np.zeros_like(mask[top:bot + 1]); band[:] = mask[top:bot + 1]
    match = _match_font(band, " ".join(words[0]), xh / Z / 0.52) if words else None
    out["hscale"] = 1.0
    if match and match["iou"] >= 0.4:
        # a standard font fits: size from ink WIDTH (blur barely affects a long line's width)
        out.update(font=match["font"], size=round(match["size_w"], 1), match=round(match["iou"], 2), cands=match["cands"])
    elif match:
        # no standard font fits (e.g. a narrow typeface): Sans/Sans Bold by stroke weight,
        # match glyph height, squeeze/stretch the width to the scanned line
        f = "hebo" if _stroke_ratio(mask, first) > 0.21 else "helv"
        c = match["cands"][f]
        out.update(font=f, match=round(match["iou"], 2), size=round(c["size_h"], 1), cands=match["cands"],
                   hscale=round(float(np.clip(c["size_w"] / c["size_h"], 0.75, 1.25)), 3))
    else:  # no usable OCR: x-height ~ 0.52 em; thick stems -> bold
        out["size"] = round(xh / Z / 0.52, 1)
        out["cands"] = match and match["cands"]
        out["font"] = "hebo" if _stroke_ratio(mask, first) > 0.21 else "helv"
    out["font_label"] = CANDIDATES[out["font"]]
    return out


# ---------------------------------------------------------------- move

def _ink_rgba(page, rect):
    """Render rect, return (bg, mask, rgba uint8, Rect of the ink in pt) — ink keeps its own
    colour, paper becomes transparent (soft alpha keeps anti-aliased edges)."""
    r = pymupdf.Rect(rect)
    m = 2
    outer = (r + (-m, -m, m, m)) & page.rect
    img = _render(page, outer)
    bg = _bg(img)
    ox, oy = int(round((r.x0 - outer.x0) * Z)), int(round((r.y0 - outer.y0) * Z))
    inner = img[oy:oy + int(r.height * Z), ox:ox + int(r.width * Z)]
    dist = np.abs(inner - bg).sum(axis=2)
    mask = dist > 120
    if mask.sum() < 10:
        return bg, mask, None, None
    ys, xs = np.where(dist > 45)
    y0, y1, x0, x1 = max(ys.min() - 1, 0), ys.max() + 2, max(xs.min() - 1, 0), xs.max() + 2
    crop, d = inner[y0:y1, x0:x1], dist[y0:y1, x0:x1]
    alpha = np.clip((d - 30) / 90.0, 0, 1)
    rgba = np.dstack([crop, (alpha * 255)]).astype(np.uint8)
    ink = pymupdf.Rect(r.x0 + x0 / Z, r.y0 + y0 / Z, r.x0 + x1 / Z, r.y0 + y1 / Z)
    return bg, mask, rgba, ink


def _png(rgba: np.ndarray) -> bytes:
    h, w = rgba.shape[:2]
    return pymupdf.Pixmap(pymupdf.csRGB, w, h, np.ascontiguousarray(rgba).tobytes(), 1).tobytes("png")


def lift(page: pymupdf.Page, rect) -> dict | None:
    """What Move picks up: the ink (transparent PNG), its box, the paper colour, first baseline."""
    bg, mask, rgba, ink = _ink_rgba(page, rect)
    if rgba is None:
        return None
    lines = [_line_metrics(mask, a, b) for a, b in _lines(mask)]
    r = pymupdf.Rect(rect)
    return {"png": _png(rgba), "ink": [ink.x0, ink.y0, ink.x1, ink.y1], "fill": (bg / 255).round(3).tolist(),
            "baseline": r.y0 + lines[0]["baseline"] / Z if lines else None,
            "left": r.x0 + lines[0]["x0"] / Z if lines else ink.x0}


def move_pixels(page: pymupdf.Page, rect, dx: float, dy: float, fill) -> None:
    """Scans: paint the paper colour over the old ink, paste the ink (transparent PNG) at the new spot."""
    bg, _, rgba, ink = _ink_rgba(page, rect)
    if rgba is None:
        raise ValueError("nothing to move in that box")
    png = _png(rgba)
    page.draw_rect(ink + (-0.5, -0.5, 0.5, 0.5), color=None, fill=fill if fill is not None else (bg / 255).tolist(),
                   overlay=True, width=0)
    page.insert_image(ink + (dx, dy, dx, dy), stream=png, keep_proportion=False, overlay=True)
