"""
Vayu — Airfare Price Index & Regulatory Suite
FastAPI application with persistent data and real scraping.
Version: 1.0.0
"""

import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

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

import asyncio
import io
import csv
import database
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

# ─── Global State ───────────────────────────────────────────────────────────
calculator = VayuCalculator()
scraper = VayuScraper()
cleaner = FareCleaner()
validator = FareValidator()
connected_websockets: list[WebSocket] = []
latest_validated_fares: list = []
background_task: asyncio.Task = None


async def run_scrape_pipeline():
    """Execute full scrape, clean, validate, index, and broadcast pipeline."""
    global latest_validated_fares
    logger.info("Scrape pipeline started...")
    raw_fares = await scraper.scrape_all_routes()
    cleaned = cleaner.clean_batch(raw_fares)
    validated = validator.validate_batch(cleaned)
    latest_validated_fares = validated

    record = calculator.compute_daily_index(validated)
    await broadcast_update(record)

    surges = calculator.check_surge_events(validated)
    for surge in surges:
        await broadcast_surge_alert(surge)

    logger.info(f"Scrape pipeline completed: {len(raw_fares)} raw -> {len(validated)} valid")
    return raw_fares, cleaned, validated, record, surges


async def background_scraper_loop():
    """Automated continuous background scraper running every 15 minutes (900s)."""
    logger.info("Continuous 15-minute background scraper loop started.")
    await asyncio.sleep(10)  # Initial delay
    while True:
        try:
            await run_scrape_pipeline()
        except asyncio.CancelledError:
            logger.info("Background scraper loop cancelled for server shutdown.")
            break
        except Exception as e:
            logger.error(f"Error in continuous background scraper loop: {e}")

        # Strict 15-minute delay (900s) to prevent IP bans
        await asyncio.sleep(900)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info(f"  {APP_TITLE} v{APP_VERSION}")
    logger.info("=" * 60)

    # Initialize SQLite database and baseline seed
    database.init_db()

    # Load cached index history
    if not calculator.load_cached_history():
        logger.info("No cached index history found. Awaiting first scrape.")
    else:
        logger.info(f"Loaded {len(calculator.index_history)} cached/seed index records")

    await scraper.initialize()

    # Launch continuous background scraper loop task
    global background_task
    background_task = asyncio.create_task(background_scraper_loop())

    yield

    # Cancel background task gracefully on shutdown
    if background_task:
        background_task.cancel()
        try:
            await background_task
        except asyncio.CancelledError:
            pass

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


# ─── Multi-Page Routing ──────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Page 1: Macro Economy Dashboard (APIx index, 30-day macro trend, Route-Based Tracker)."""
    current = calculator.get_current_value()
    elasticity = calculator.compute_lead_time_elasticity()
    routes_breakdown = calculator.get_route_breakdown(latest_validated_fares)
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "title": APP_TITLE,
            "page": "dashboard",
            "current_index": current.vayu_value if current else 100.0,
            "daily_change": current.daily_change_pct if current else 0.0,
            "num_fares": current.num_fares if current else 0,
            "routes_covered": current.routes_covered if current else 0,
            "weighted_avg_fare": current.weighted_avg_fare if current else 0,
            "elasticity": elasticity,
            "routes_breakdown": routes_breakdown,
            "route_names": ROUTE_NAMES,
            "scraper_mode": scraper.scrape_mode,
        },
    )


@app.get("/regulatory", response_class=HTMLResponse)
async def regulatory_page(request: Request):
    """Page 2: Compliance & Antitrust (Rule 135 Tracker & HHI Concentration Meter)."""
    current = calculator.get_current_value()
    return templates.TemplateResponse(
        request=request,
        name="regulatory.html",
        context={
            "title": f"{APP_TITLE} — Regulatory & Compliance",
            "page": "regulatory",
            "current_index": current.vayu_value if current else 100.0,
            "route_names": ROUTE_NAMES,
            "scraper_mode": scraper.scrape_mode,
        },
    )


@app.get("/telemetry", response_class=HTMLResponse)
async def telemetry_page(request: Request):
    """Page 3: Alerts & System Logs (Live scrape logs & Automated Surge Feed)."""
    return templates.TemplateResponse(
        request=request,
        name="telemetry.html",
        context={
            "title": f"{APP_TITLE} — Telemetry & Alerts",
            "page": "telemetry",
            "scraper_mode": scraper.scrape_mode,
        },
    )


# ─── API Endpoints ──────────────────────────────────────────────────────────
@app.get("/api/v1/export/fares")
async def export_fares_csv():
    """
    Data API for MoSPI/RBI:
    Queries ScrapedFare SQLite table and returns full dataset as downloadable CSV.
    Outputs newest live scraped fares first with explicit data_type categorization.
    """
    from database import SessionLocal
    from pipeline.db_models import ScrapedFare

    session = SessionLocal()
    try:
        fares = session.query(ScrapedFare).order_by(ScrapedFare.id.desc()).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "data_type", "timestamp", "route", "airline", "advance_window",
            "base_fare", "tax_amount", "total_price", "rule_135_breach"
        ])

        for f in fares:
            data_type = "HISTORICAL_BASELINE" if f.id <= 186 else "LIVE_SCRAPE"
            writer.writerow([
                f.id,
                data_type,
                f.timestamp.isoformat() if f.timestamp else "",
                f.route,
                f.airline,
                f.advance_window,
                f.base_fare,
                f.tax_amount,
                f.total_price,
                f.rule_135_breach,
            ])

        csv_content = output.getvalue()
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=vayu_fares_export.csv"},
        )
    finally:
        session.close()


@app.get("/api/index/projection")
async def get_index_projection():
    """Price Prediction (ML): Returns 3-day projected APIx values."""
    return calculator.compute_3day_projection()


@app.get("/api/elasticity")
async def get_lead_time_elasticity():
    """Lead Time Elasticity: Compares T+1 vs T+15 fares and returns discount metric."""
    return calculator.compute_lead_time_elasticity()


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
    global latest_validated_fares
    return {"status": "ok", "data": calculator.get_route_breakdown(latest_validated_fares), "route_names": ROUTE_NAMES}


@app.get("/api/scrape")
async def trigger_scrape():
    try:
        logger.info("Manual scrape triggered")
        raw_fares, cleaned, validated, record, surges = await run_scrape_pipeline()

        return {
            "status": "ok",
            "message": f"{len(raw_fares)} raw -> {len(cleaned)} cleaned -> {len(validated)} valid",
            "scraper_mode": scraper.scrape_mode,
            "surges_detected": len(surges),
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
    """Returns real-time data pipeline statistics and database row count."""
    from database import SessionLocal
    from pipeline.db_models import ScrapedFare
    session = SessionLocal()
    total_db = 0
    try:
        total_db = session.query(ScrapedFare).count()
    except Exception:
        pass
    finally:
        session.close()

    cleaner_stats = cleaner.get_stats()
    cleaner_stats["total_db_fares"] = total_db
    if cleaner_stats["cleaned"] == 0 and total_db > 0:
        cleaner_stats["cleaned"] = total_db

    return {
        "status": "ok",
        "data": {
            "cleaner": cleaner_stats,
            "validator": validator.get_stats(),
            "scraper": scraper.get_status(),
            "index_records": len(calculator.index_history),
        },
    }


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
    """Event-Driven WebSocket Broadcaster: Pushes recalculated index, routes, HHI, and elasticity to all connected clients."""
    global latest_validated_fares
    route_breakdown = calculator.get_route_breakdown(latest_validated_fares)
    elasticity = calculator.compute_lead_time_elasticity()

    message = {
        "type": "index_update",
        "data": {
            "index": {
                "date": record.date.isoformat(),
                "vayu_value": record.vayu_value,
                "daily_change_pct": record.daily_change_pct,
                "num_fares": record.num_fares,
                "routes_covered": record.routes_covered,
                "weighted_avg_fare": record.weighted_avg_fare,
            },
            "routes": route_breakdown,
            "elasticity": elasticity,
        }
    }
    disconnected = []
    for ws in connected_websockets:
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        try:
            connected_websockets.remove(ws)
        except ValueError:
            pass


async def broadcast_surge_alert(surge_data: dict):
    """Broadcast high-priority surge alerts over WebSockets."""
    message = {"type": "surge_alert", "data": surge_data}
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
