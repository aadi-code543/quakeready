#!/usr/bin/env bash
# Start QuakeReady on http://127.0.0.1:8000 (Mac/Linux). On Windows use run.bat.
cd "$(dirname "$0")"
[ -f .venv/bin/activate ] && source .venv/bin/activate
python -m uvicorn app.main:app --reload --port 8000
