"""
main.py - the web server (FastAPI).

Run it from the quakeready folder with:
    python -m uvicorn app.main:app --reload
then open http://127.0.0.1:8000 in a browser.

Routes:
    GET  /                  the web page (static/index.html)
    POST /api/analyze       upload a photo, get the full analysis back
    POST /api/recalculate   redo the physics (and the rocking simulation)
                            after the user edits items
    GET  /api/shaking       look up shaking for an address on its own
"""

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import shaking
from .analyze import analyze_photo, evaluate

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB is plenty for a phone photo

app = FastAPI(title="QuakeReady")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/analyze")
async def analyze(photo: UploadFile = File(...),
                  address: str = Form(""),
                  floor: int = Form(1),
                  total_floors: int = Form(1),
                  scenario: str = Form("design"),
                  quake_type: str = Form("cascadia"),
                  budget: int = Form(25)):
    data = await photo.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Photo is too large (15 MB max).")
    try:
        return analyze_photo(data, address, floor, total_floors, scenario, quake_type, budget)
    except ValueError as err:
        raise HTTPException(400, str(err))


class RecalcRequest(BaseModel):
    """What the browser sends back after the user edits something."""
    items: list[dict]
    pga: float
    floor: int = 1
    total_floors: int = 1
    scenario: str = "design"
    quake_type: str = "cascadia"   # kind of shaking for the rocking simulation
    budget: int = 25               # dollars, for the "buy these first" plan


@app.post("/api/recalculate")
def recalculate(req: RecalcRequest):
    for item in req.items:
        # Basic sanity limits so a typo can't break the math.
        item["height_in"] = min(max(float(item["height_in"]), 1), 200)
        item["depth_in"] = min(max(float(item["depth_in"]), 0.5), 100)
    return evaluate(req.items, req.pga, req.floor, req.total_floors, req.scenario,
                    req.quake_type, req.budget)


@app.get("/api/shaking")
def get_shaking(address: str = ""):
    return shaking.lookup(address)
