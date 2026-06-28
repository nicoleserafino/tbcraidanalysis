"""TBC Raid Analysis — FastAPI Backend."""

from __future__ import annotations

import logging
import re
import time
import traceback
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

from backend.analysis.compare import fetch_compare_report, fetch_player_details
from backend.analysis.guild import fetch_guild_reports, compute_attendance, fetch_gear_audit
from backend.analysis.report import fetch_full_report
from backend.config import get_settings

app = FastAPI(title="TBC Raid Analysis", version="2.0.0")

CACHE_TTL = 1800  # 30 minutes

# In-memory cache (timestamp, data[, extra metadata])
_report_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_compare_report_cache: dict[str, tuple[float, dict[str, Any], dict[int, str]]] = {}
_player_details_cache: dict[tuple[str, int, int], tuple[float, dict[str, Any]]] = {}


def _is_cache_fresh(timestamp: float, ttl: float = CACHE_TTL) -> bool:
    return (time.time() - timestamp) < ttl


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


# ─── Guild Endpoints ─────────────────────────────────────────────────

_guild_reports_cache: dict[int, tuple[float, dict[str, Any]]] = {}
_guild_attendance_cache: dict[int, tuple[float, dict[str, Any]]] = {}
_gear_audit_cache: dict[str, tuple[float, dict[str, Any]]] = {}


@app.get("/api/guild/reports")
async def get_guild_reports(
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=50),
):
    """Fetch guild report list with attendance."""
    settings = get_settings()
    guild_id = settings.guild_id

    cache_key = guild_id * 1000 + page
    cached = _guild_reports_cache.get(cache_key)
    if cached and _is_cache_fresh(cached[0]):
        return cached[1]

    try:
        result = await fetch_guild_reports(guild_id, limit=limit, page=page)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Guild reports error: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to fetch guild reports: {e}")

    _guild_reports_cache[cache_key] = (time.time(), result)
    return result


@app.get("/api/guild/attendance")
async def get_guild_attendance():
    """Fetch aggregated attendance across recent raids."""
    settings = get_settings()
    guild_id = settings.guild_id

    cached = _guild_attendance_cache.get(guild_id)
    if cached and _is_cache_fresh(cached[0]):
        return cached[1]

    try:
        result = await compute_attendance(guild_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Guild attendance error: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to compute attendance: {e}")

    _guild_attendance_cache[guild_id] = (time.time(), result)
    return result


@app.get("/api/report/{report_code}/gear")
async def get_gear_audit(report_code: str):
    """Fetch gear/enchant/consumable audit for a report."""
    try:
        code = extract_report_code(report_code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    cached = _gear_audit_cache.get(code)
    if cached and _is_cache_fresh(cached[0]):
        return cached[1]

    try:
        result = await fetch_gear_audit(code)
    except Exception as e:
        logger.error("Gear audit error: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to fetch gear audit: {e}")

    _gear_audit_cache[code] = (time.time(), result)
    return result


@app.get("/api/guild/player-prep")
async def get_player_prep_history(
    player: str = Query(..., description="Player name"),
    raids: int = Query(8, ge=1, le=20, description="Number of recent raids to check"),
):
    """Fetch prep/gear audit for a specific player across recent raids."""
    settings = get_settings()
    guild_id = settings.guild_id

    # Get recent raid reports
    try:
        reports_data = await fetch_guild_reports(guild_id, limit=raids, page=1)
    except Exception as e:
        logger.error("Player prep history error (reports): %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch guild reports: {e}")

    reports = reports_data.get("reports", [])
    if not reports:
        return {"player": player, "raids": []}

    # Fetch gear audit for each report (use cache where possible)
    results = []
    for report in reports:
        code = report.get("code")
        if not code:
            continue
        # Check cache
        cached = _gear_audit_cache.get(code)
        if cached and _is_cache_fresh(cached[0]):
            audit = cached[1]
        else:
            try:
                audit = await fetch_gear_audit(code)
                _gear_audit_cache[code] = (time.time(), audit)
            except Exception:
                continue

        # Find the player in this audit
        players = audit.get("players", [])
        player_data = next(
            (p for p in players if p.get("name", "").lower() == player.lower()),
            None,
        )
        if player_data:
            results.append({
                "report_code": code,
                "zone": report.get("zone", "Unknown"),
                "date": report.get("date") or report.get("startTime"),
                "player": player_data,
            })

    return {"player": player, "raids": results}



# ── AI Advice Endpoint ───────────────────────────────────────────────────────

from pydantic import BaseModel


class AIAdviceRequest(BaseModel):
    player_name: str
    player_class: str
    player_role: str
    boss_name: str
    pull_data: dict[str, Any]


_ai_advice_cache: dict[str, tuple[float, str]] = {}


@app.post("/api/report/ai-advice")
async def post_ai_advice(req: AIAdviceRequest):
    """Get AI-powered individual player advice for a specific fight."""
    from backend.analysis.ai_advice import get_ai_advice
    import hashlib, json

    # Cache key based on player + boss + pull summary
    cache_key = hashlib.md5(
        f"{req.player_name}:{req.boss_name}:{json.dumps(req.pull_data, sort_keys=True, default=str)[:2000]}".encode()
    ).hexdigest()

    cached = _ai_advice_cache.get(cache_key)
    if cached and _is_cache_fresh(cached[0], ttl=1800):  # 30min TTL
        return {"advice": cached[1]}

    try:
        advice = await get_ai_advice(
            player_name=req.player_name,
            player_class=req.player_class,
            player_role=req.player_role,
            boss_name=req.boss_name,
            pull_data=req.pull_data,
        )
        _ai_advice_cache[cache_key] = (time.time(), advice)
        return {"advice": advice}
    except Exception as e:
        logger.error("AI advice error: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"AI advice failed: {e}")


# ── Threat Data Endpoint ─────────────────────────────────────────────────────

@app.get("/api/report/{report_code}/threat")
async def get_threat_data(report_code: str, fight_id: int):
    """Fetch threat data for top 5 DPS on a specific fight."""
    from backend.analysis.threat import fetch_threat_data
    try:
        code = extract_report_code(report_code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        result = await fetch_threat_data(code, fight_id)
        return result
    except Exception as e:
        logger.error("Threat data error: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Threat data failed: {e}")


# ── Positioning Data Endpoint ─────────────────────────────────────────────────

@app.get("/api/report/{report_code}/positioning")
async def get_positioning_data(report_code: str, fight_id: int):
    """Fetch player positioning snapshots around key mechanic events."""
    from backend.analysis.positioning import fetch_positioning_data
    try:
        code = extract_report_code(report_code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        result = await fetch_positioning_data(code, fight_id)
        return result
    except Exception as e:
        logger.error("Positioning data error: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Positioning data failed: {e}")


# Serve frontend static files
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@app.get("/")
async def serve_guild():
    return FileResponse(FRONTEND_DIR / "guild.html")


@app.get("/report")
async def serve_report():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/compare")
async def serve_compare():
    return FileResponse(FRONTEND_DIR / "compare.html")


# Mount static files (CSS/JS if any are added later)
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
