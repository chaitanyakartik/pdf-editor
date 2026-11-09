#!/bin/sh
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
(sleep 1.5 && open "http://localhost:${PORT:-43063}") &
exec .venv/bin/python app.py "$@"
