"""TBC Raid Analysis — FastAPI Backend."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.analysis.compare import fetch_compare_report, fetch_player_details
from backend.analysis.report import fetch_full_report

app = FastAPI(title="TBC Raid Analysis", version="2.0.0")

CACHE_TTL = 1800  # 30 minutes

# In-memory cache (timestamp, data[, extra metadata])
_report_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_compare_report_cache: dict[str, tuple[float, dict[str, Any], dict[int, str]]] = {}
_player_details_cache: dict[tuple[str, int, int], tuple[float, dict[str, Any]]] = {}


def _is_cache_fresh(timestamp: float) -> bool:
    return (time.time() - timestamp) < CACHE_TTL


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
    cached = _report_cache.get(code)
    if cached and _is_cache_fresh(cached[0]):
        return cached[1]
    if cached:
        _report_cache.pop(code, None)

    try:
        report = await fetch_full_report(code)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch report: {e}")

    # Cache result
    _report_cache[code] = (time.time(), report)
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
        "fights": metadata.get("fights", []) or [],
        "players": [
            {"id": a["id"], "name": a["name"], "class": a.get("subType", "")}
            for a in metadata.get("masterData", {}).get("actors", []) or []
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

    cached = _compare_report_cache.get(code)
    if cached and _is_cache_fresh(cached[0]):
        return cached[1]
    if cached:
        _compare_report_cache.pop(code, None)

    try:
        report, ability_names = await fetch_compare_report(code)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch compare report: {e}")

    _compare_report_cache[code] = (time.time(), report, ability_names)
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
    cached_details = _player_details_cache.get(cache_key)
    if cached_details and _is_cache_fresh(cached_details[0]):
        return cached_details[1]
    if cached_details:
        _player_details_cache.pop(cache_key, None)

    compare_cached = _compare_report_cache.get(code)
    if not compare_cached or not _is_cache_fresh(compare_cached[0]):
        try:
            report, ability_names = await fetch_compare_report(code)
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch compare report: {e}")
        compare_cached = (time.time(), report, ability_names)
        _compare_report_cache[code] = compare_cached

    _, compare_report, ability_names = compare_cached
    fight = next((boss for boss in compare_report.get("bosses", []) if boss.get("fight_id") == fight_id), None)
    if fight is None:
        raise HTTPException(status_code=404, detail=f"Fight {fight_id} was not found in report {code}.")

    try:
        details = await fetch_player_details(
            code,
            fight_id,
            player_id,
            ability_names,
            int(fight.get("start_time", 0) or 0),
            int(fight.get("end_time", 0) or 0),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch player details: {e}")

    _player_details_cache[cache_key] = (time.time(), details)
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
