"""
Database Persistence Layer — SQLAlchemy + SQLite (vayu_production.db)
Initializes database engine, session factory, and handles database setup.
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from config import DATA_DIR, HISTORICAL_SEED_FILE

logger = logging.getLogger("vayu.database")

DB_FILE = DATA_DIR / "vayu_production.db"
DATABASE_URL = f"sqlite:///{DB_FILE}"

# SQLAlchemy Engine & Session Factory
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Generator:
    """FastAPI Dependency for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Initialize database tables and seed baseline data if empty."""
    from pipeline.db_models import ScrapedFare, DailyIndex

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    logger.info(f"SQLite database initialized at {DB_FILE}")

    session = SessionLocal()
    try:
        # Seed DailyIndex and ScrapedFare baseline from historical_seed.json if empty
        index_count = session.query(DailyIndex).count()
        if index_count == 0 and HISTORICAL_SEED_FILE.exists():
            logger.info("Seeding database baseline from historical_seed.json...")
            with open(HISTORICAL_SEED_FILE) as f:
                seed_records = json.load(f)

            for item in seed_records:
                d = date.fromisoformat(item["date"])
                idx_entry = DailyIndex(
                    date=d,
                    apix_value=item["vayu_value"],
                    daily_change_pct=item.get("daily_change_pct", 0.0),
                    num_fares=item.get("num_fares", 50),
                    routes_covered=item.get("routes_covered", 3),
                    weighted_avg_fare=item.get("weighted_avg_fare", 5200.0),
                )
                session.add(idx_entry)

                # Seed sample historical route fares for calculation context
                route_fares = item.get("route_fares", {})
                for route, fare_val in route_fares.items():
                    origin, dest = route.split("-")
                    # Seed T+1 and T+15 sample records
                    for advance in [1, 15]:
                        mult = 1.15 if advance == 1 else 0.85
                        fare_obj = ScrapedFare(
                            timestamp=datetime.combine(d, datetime.min.time()),
                            route=route,
                            airline="IndiGo",
                            advance_window=advance,
                            base_fare=round(fare_val * mult * 0.78, 2),
                            tax_amount=round(fare_val * mult * 0.22, 2),
                            total_price=round(fare_val * mult, 2),
                            rule_135_breach=fare_val * mult * 0.78 > 12000.0,
                        )
                        session.add(fare_obj)

            session.commit()
            logger.info("Successfully seeded baseline data into SQLite database.")
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to seed database: {e}")
    finally:
        session.close()
