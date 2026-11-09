"""PDF text editor: local server. Run: .venv/bin/python app.py  ->  http://localhost:43063"""
from __future__ import annotations

import io
import os
import sys
import threading

import pymupdf
from flask import Flask, abort, jsonify, request, send_file, send_from_directory

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


def _bump():
    S["ver"] += 1


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


@app.post("/api/patch")
def patch():
    j = request.get_json()
    _snapshot()
    engine.patch(_doc(), j["page"], j["rect"], j.get("fill"), j.get("text", ""),
                 float(j.get("size", 11)), j.get("color", [0, 0, 0]), j.get("font", "helv"),
                 x=j.get("x"), baseline=j.get("baseline"), pitch=j.get("pitch"),
                 fit=j.get("fit", False), hscale=float(j.get("hscale", 1.0)))
    _bump()
    return jsonify(_meta())


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
    if len(sys.argv) > 1:  # optional: preload a file
        with open(sys.argv[1], "rb") as fh:
            S.update(doc=pymupdf.open(stream=fh.read(), filetype="pdf"), name=os.path.basename(sys.argv[1]))
    print(f"PDF editor on http://localhost:{PORT}", flush=True)
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
