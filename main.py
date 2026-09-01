"""
Vayu — Airfare Price Index
FastAPI application with persistent data and real scraping.
"""

import logging
import json
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import (
    APP_TITLE, APP_DESCRIPTION, APP_VERSION,
    STATIC_DIR, TEMPLATES_DIR, ROUTE_NAMES,
)
from scraper.engine import VayuScraper
from pipeline.cleaner import FareCleaner
from pipeline.validator import FareValidator
from calculator.index import VayuCalculator

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-20s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("vayu.main")

# ─── Global State ───────────────────────────────────────────────────────────
calculator = VayuCalculator()
scraper = VayuScraper()
cleaner = FareCleaner()
validator = FareValidator()
connected_websockets: list[WebSocket] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info(f"  {APP_TITLE} v{APP_VERSION}")
    logger.info("=" * 60)

    # Try loading cached index first (survives restarts)
    if not calculator.load_cached_history():
        logger.info("No cached history — generating 30-day backtest...")
        calculator.generate_backtest_history(days=30)
    else:
        logger.info(f"Loaded {len(calculator.index_history)} cached records")

    await scraper.initialize()
    yield
    await scraper.close()
    logger.info("Vayu shutdown complete")


app = FastAPI(
    title=APP_TITLE,
    description=APP_DESCRIPTION,
    version=APP_VERSION,
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ─── Dashboard ──────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    current = calculator.get_current_value()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "title": APP_TITLE,
            "current_index": current.vayu_value if current else 100.0,
            "daily_change": current.daily_change_pct if current else 0.0,
            "num_fares": current.num_fares if current else 0,
            "routes_covered": current.routes_covered if current else 0,
            "weighted_avg_fare": current.weighted_avg_fare if current else 0,
            "route_names": ROUTE_NAMES,
            "scraper_mode": scraper.scrape_mode,
        },
    )


# ─── API Endpoints ──────────────────────────────────────────────────────────
@app.get("/api/index/current")
async def get_current_index():
    current = calculator.get_current_value()
    if current:
        return {"status": "ok", "data": {
            "date": current.date.isoformat(),
            "vayu_value": current.vayu_value,
            "daily_change_pct": current.daily_change_pct,
            "num_fares": current.num_fares,
            "routes_covered": current.routes_covered,
            "weighted_avg_fare": current.weighted_avg_fare,
        }}
    return {"status": "no_data", "data": None}


@app.get("/api/index/history")
async def get_index_history():
    history = calculator.get_history_json()
    return {"status": "ok", "count": len(history), "data": history}


@app.get("/api/validation")
async def get_validation_data():
    return {"status": "ok", "data": calculator.get_correlation_data()}


@app.get("/api/routes/breakdown")
async def get_route_breakdown():
    return {"status": "ok", "data": calculator.get_route_breakdown(), "route_names": ROUTE_NAMES}


@app.get("/api/scrape")
async def trigger_scrape():
    try:
        logger.info("Manual scrape triggered")
        raw_fares = await scraper.scrape_all_routes()
        cleaned = cleaner.clean_batch(raw_fares)
        validated = validator.validate_batch(cleaned)
        record = calculator.compute_daily_index(validated)
        await broadcast_update(record)

        return {
            "status": "ok",
            "message": f"{len(raw_fares)} raw → {len(cleaned)} cleaned → {len(validated)} valid",
            "scraper_mode": scraper.scrape_mode,
            "index": {
                "date": record.date.isoformat(),
                "vayu_value": record.vayu_value,
                "daily_change_pct": record.daily_change_pct,
            },
            "pipeline_stats": {
                "cleaner": cleaner.get_stats(),
                "validator": validator.get_stats(),
                "scraper": scraper.get_status(),
            },
        }
    except Exception as e:
        logger.error(f"Scrape failed: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@app.get("/api/pipeline/stats")
async def get_pipeline_stats():
    return {"status": "ok", "data": {
        "cleaner": cleaner.get_stats(),
        "validator": validator.get_stats(),
        "scraper": scraper.get_status(),
        "index_records": len(calculator.index_history),
    }}


@app.get("/api/scrape/log")
async def get_scrape_log():
    return {"status": "ok", "data": scraper.get_scrape_log()}


@app.get("/api/methodology")
async def get_methodology():
    return {"status": "ok", "data": {
        "name": "Chain-Based Laspeyres Index",
        "formula": "Vayu_t = Vayu_{t-1} × Σ(w_r × P_r,t) / Σ(w_r × P_r,t-1)",
        "description": (
            "Vayu uses a chain-based Laspeyres methodology "
            "aligned with MoSPI's 2024 CPI modernization. Daily fare data from "
            "3 DGCA high-traffic routes is aggregated using passenger volume weights "
            "and chained to the previous day's index value."
        ),
        "base_period": "2026-07-28 = 100.0",
        "routes": ROUTE_NAMES,
        "weights": {"DEL-BOM": "0.45 (9.2M annual pax)", "BOM-BLR": "0.30 (6.1M annual pax)", "DEL-BLR": "0.25 (5.1M annual pax)"},
    }}


# ─── WebSocket ──────────────────────────────────────────────────────────────
@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    await websocket.accept()
    connected_websockets.append(websocket)
    logger.info(f"WebSocket connected ({len(connected_websockets)} total)")
    try:
        current = calculator.get_current_value()
        if current:
            await websocket.send_json({
                "type": "index_update",
                "data": {"date": current.date.isoformat(), "vayu_value": current.vayu_value, "daily_change_pct": current.daily_change_pct},
            })
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        connected_websockets.remove(websocket)
        logger.info(f"WebSocket disconnected ({len(connected_websockets)} remaining)")


async def broadcast_update(record):
    message = {"type": "index_update", "data": {
        "date": record.date.isoformat(), "vayu_value": record.vayu_value,
        "daily_change_pct": record.daily_change_pct, "num_fares": record.num_fares,
    }}
    disconnected = []
    for ws in connected_websockets:
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        connected_websockets.remove(ws)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
