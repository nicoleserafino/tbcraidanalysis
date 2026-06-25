"""TBC Raid Analysis — FastAPI Backend."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.analysis.report import fetch_full_report

app = FastAPI(title="TBC Raid Analysis", version="2.0.0")

# In-memory cache (TTL-based, simple dict for now)
_report_cache: dict[str, dict] = {}


def extract_report_code(url_or_code: str) -> str:
    """Extract report code from URL or return as-is."""
    match = re.search(r"reports/([A-Za-z0-9]+)", url_or_code)
    if match:
        return match.group(1)
    # Assume it's already a code
    if re.match(r"^[A-Za-z0-9]+$", url_or_code):
        return url_or_code
    raise ValueError(f"Invalid report URL or code: {url_or_code}")


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}


@app.get("/api/report/{report_code}")
async def get_report(report_code: str):
    """Fetch and analyze a full report."""
    try:
        code = extract_report_code(report_code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Check cache
    if code in _report_cache:
        return _report_cache[code]

    try:
        report = await fetch_full_report(code)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch report: {e}")

    # Cache result
    _report_cache[code] = report
    return report


@app.get("/api/report/{report_code}/fights")
async def get_report_fights(report_code: str):
    """Fetch just the fight list (lightweight metadata)."""
    from backend.analysis.report import fetch_report_metadata

    try:
        code = extract_report_code(report_code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        metadata = await fetch_report_metadata(code)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return {
        "title": metadata.get("title", code),
        "fights": metadata["fights"],
        "players": [
            {"id": a["id"], "name": a["name"], "class": a["subType"]}
            for a in metadata["masterData"]["actors"]
        ],
    }


# Serve frontend static files
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@app.get("/")
async def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/compare")
async def serve_compare():
    return FileResponse(FRONTEND_DIR / "compare.html")


# Mount static files (CSS/JS if any are added later)
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
