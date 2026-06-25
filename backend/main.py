"""TBC Raid Analysis — FastAPI Backend."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.analysis.compare import fetch_compare_report, fetch_player_details
from backend.analysis.report import fetch_full_report

app = FastAPI(title="TBC Raid Analysis", version="2.0.0")

# In-memory cache (TTL-based, simple dict for now)
_report_cache: dict[str, dict] = {}
_compare_report_cache: dict[str, dict] = {}
_player_details_cache: dict[tuple[str, int, int], dict] = {}


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
            {"id": a["id"], "name": a["name"], "class": a.get("subType", "")}
            for a in metadata["masterData"]["actors"]
            if a.get("type") == "Player"
        ],
    }


@app.get("/api/compare-report/{report_code}")
async def get_compare_report(report_code: str):
    """Fetch comparison-focused data for a report."""
    try:
        code = extract_report_code(report_code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if code in _compare_report_cache:
        return _compare_report_cache[code]

    try:
        report = await fetch_compare_report(code)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch compare report: {e}")

    _compare_report_cache[code] = report
    return report


@app.get("/api/report/{report_code}/player-details")
async def get_player_details(
    report_code: str,
    fight_id: int = Query(...),
    player_id: int = Query(...),
):
    """Fetch detailed per-player boss data for compare.html."""
    try:
        code = extract_report_code(report_code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    cache_key = (code, fight_id, player_id)
    if cache_key in _player_details_cache:
        return _player_details_cache[cache_key]

    try:
        details = await fetch_player_details(code, fight_id, player_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch player details: {e}")

    _player_details_cache[cache_key] = details
    return details


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
