"""PDF text editor: local server. Run: .venv/bin/python app.py  ->  http://localhost:43063"""
from __future__ import annotations

import io
import os
import sys
import pickle
import threading
from pathlib import Path

import pymupdf
from flask import Flask, abort, jsonify, request, send_file, send_from_directory

import base64

import compose
import engine
import scan

PORT = int(os.environ.get("PORT", 43063))
HERE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=None)

# single-user state: the working doc + an undo stack of snapshots
S: dict = {"doc": None, "name": "", "undo": [], "redo": [], "ver": 0}


# Threaded server (a single-threaded one hangs whenever Chrome holds an idle preconnect socket),
# with every /api call serialised: PyMuPDF documents are not thread-safe.
_LOCK = threading.Lock()


@app.before_request
def _lock():
    if request.path.startswith("/api/"):
        _LOCK.acquire()
        request.environ["pdfedit.locked"] = True


@app.teardown_request
def _unlock(_exc):
    if request.environ.pop("pdfedit.locked", False):
        _LOCK.release()


def _doc() -> pymupdf.Document:
    if S["doc"] is None:
        abort(400, "no PDF open")
    return S["doc"]


def _snapshot():
    S["undo"].append(S["doc"].tobytes())
    S["undo"] = S["undo"][-50:]
    S["redo"].clear()


def _meta():
    d = S["doc"]
    return {"name": S["name"], "ver": S["ver"], "can_undo": bool(S["undo"]), "can_redo": bool(S["redo"]),
            "pages": [{"w": p.rect.width, "h": p.rect.height} for p in d]}


# Session on disk: every change (with up to 20 undo steps) survives a server restart.
SESSION = Path(os.environ.get("REDLINE_SESSION", Path.home() / "Library/Application Support/Redline/session.pkl"))


def _persist():
    if S["doc"] is None or os.environ.get("REDLINE_NO_SESSION"):
        return
    SESSION.parent.mkdir(parents=True, exist_ok=True)
    tmp = SESSION.with_suffix(".tmp")
    with open(tmp, "wb") as fh:
        pickle.dump({"doc": S["doc"].tobytes(), "name": S["name"], "undo": S["undo"][-20:], "redo": S["redo"][-20:]}, fh)
    os.replace(tmp, SESSION)


def _restore() -> bool:
    try:
        with open(SESSION, "rb") as fh:
            d = pickle.load(fh)
        S.update(doc=pymupdf.open(stream=d["doc"], filetype="pdf"), name=d["name"], undo=d["undo"], redo=d["redo"])
        return True
    except (OSError, pickle.PickleError, EOFError, KeyError):
        return False


def _bump():
    S["ver"] += 1
    _persist()


@app.get("/")
def index():
    return send_from_directory(os.path.join(HERE, "static"), "index.html")


@app.post("/api/open")
def open_pdf():
    f = request.files.get("file")
    if not f:
        abort(400, "no file")
    data = f.read()
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:
        abort(400, f"not a readable PDF: {e}")
    if doc.needs_pass and not doc.authenticate(request.form.get("password", "")):
        abort(401, "password protected")
    S.update(doc=doc, name=f.filename or "document.pdf", undo=[], redo=[])
    _bump()
    return jsonify(_meta())


@app.get("/api/meta")
def meta():
    return jsonify(_meta() if S["doc"] is not None else None)


@app.get("/api/page/<int:pno>.png")
def render(pno: int):
    d = _doc()
    zoom = min(float(request.args.get("zoom", 2)), 4)
    pix = d[pno].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    return send_file(io.BytesIO(pix.tobytes("png")), mimetype="image/png", max_age=0)


@app.get("/api/page/<int:pno>/spans")
def spans(pno: int):
    out = engine.get_spans(_doc()[pno])
    for s in out:
        s.pop("chars", None)
    return jsonify(out)


@app.post("/api/edit")
def edit():
    j = request.get_json()
    d = _doc()
    _snapshot()
    try:
        res = engine.edit_span(d, j["page"], j["id"], j["text"], fit=j.get("fit", False))
    except Exception as e:
        d2 = pymupdf.open(stream=S["undo"].pop(), filetype="pdf")
        S["doc"] = d2
        return jsonify({"error": str(e)}), 400
    _bump()
    return jsonify({**res, **_meta()})


@app.post("/api/analyze")
def analyze():
    """What's under a Patch box: existing text (OCR), font, size, colours, baseline."""
    j = request.get_json()
    return jsonify(scan.analyze(_doc()[j["page"]], j["rect"]))


def _spec(j) -> dict:
    keys = ("rect", "fill", "text", "font", "size", "color", "x", "baseline", "pitch", "hscale", "spacing", "align", "fit", "wrap", "orig", "base")
    return {k: j.get(k) for k in keys}


@app.get("/api/fonts")
def fonts():
    return jsonify(compose.fonts())


@app.post("/api/preview")
def preview():
    """Exactly what /api/patch would do: cover boxes + the new text as a transparent PNG."""
    j = request.get_json()
    try:
        res = compose.preview(_doc(), j["page"], _spec(j), min(float(j.get("zoom", 3)), 6))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if res["png"]:
        res["png"] = "data:image/png;base64," + base64.b64encode(res["png"]).decode()
    return jsonify(res)


@app.post("/api/patch")
def patch():
    j = request.get_json()
    _snapshot()
    try:
        P = compose.draw(_doc()[j["page"]], _spec(j))
        if not P["retyped"] and not P["covers"]:
            raise ValueError("nothing changed")
    except ValueError as e:
        S["doc"] = pymupdf.open(stream=S["undo"].pop(), filetype="pdf")
        return jsonify({"error": str(e)}), 400
    _bump()
    return jsonify(_meta())


@app.post("/api/lift")
def lift():
    """Move tool: the ink in a box as a transparent PNG + where it is."""
    j = request.get_json()
    page = _doc()[j["page"]]
    out = scan.lift(page, j["rect"])
    if out is None:
        return jsonify({"error": "nothing in that box"}), 400
    out["png"] = "data:image/png;base64," + base64.b64encode(out["png"]).decode()
    out["kind"] = "pixels" if engine.region_is_image(page, j["rect"]) or not engine.get_spans(page) else "text"
    return jsonify(out)


@app.post("/api/move")
def move():
    j = request.get_json()
    d, pno, dx, dy = _doc(), j["page"], float(j["dx"]), float(j["dy"])
    page = d[pno]
    _snapshot()
    try:
        if not engine.region_is_image(page, j["rect"]) and engine.move_text(d, pno, j["rect"], dx, dy):
            kind = "text"
        else:
            scan.move_pixels(page, j["rect"], dx, dy, j.get("fill"))
            kind = "pixels"
    except ValueError as e:
        S["doc"] = pymupdf.open(stream=S["undo"].pop(), filetype="pdf")
        return jsonify({"error": str(e)}), 400
    _bump()
    return jsonify({**_meta(), "kind": kind})


@app.post("/api/undo")
def undo():
    if S["undo"]:
        S["redo"].append(_doc().tobytes())
        S["doc"] = pymupdf.open(stream=S["undo"].pop(), filetype="pdf")
        _bump()
    return jsonify(_meta())


@app.post("/api/redo")
def redo():
    if S["redo"]:
        S["undo"].append(_doc().tobytes())
        S["doc"] = pymupdf.open(stream=S["redo"].pop(), filetype="pdf")
        _bump()
    return jsonify(_meta())


@app.get("/api/download")
def download():
    d = _doc()
    buf = d.tobytes(garbage=3, deflate=True)
    base, _ = os.path.splitext(S["name"])
    return send_file(io.BytesIO(buf), mimetype="application/pdf", as_attachment=True,
                     download_name=f"{base}-edited.pdf")


if __name__ == "__main__":
    # app.py                      -> restore the last session (doc + undo history), if any
    # app.py file.pdf             -> open file.pdf fresh
    # app.py file.pdf --undo-base older.pdf  -> open file.pdf with older.pdf as one undo step
    args = sys.argv[1:]
    if args:
        with open(args[0], "rb") as fh:
            S.update(doc=pymupdf.open(stream=fh.read(), filetype="pdf"), name=os.path.basename(args[0]))
        if "--undo-base" in args:
            with open(args[args.index("--undo-base") + 1], "rb") as fh:
                S["undo"] = [fh.read()]
        _persist()
    elif _restore():
        print(f"restored session: {S['name']} ({len(S['undo'])} undo steps)", flush=True)
    print(f"PDF editor on http://localhost:{PORT}", flush=True)
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
