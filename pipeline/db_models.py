"""
SQLAlchemy ORM Models for database persistence (vayu_production.db).
"""

from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Float, Boolean, Date, DateTime
from database import Base


class ScrapedFare(Base):
    """SQLAlchemy model for persistent scraped flight quotes."""

    __tablename__ = "scraped_fares"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.now, index=True)
    route = Column(String(10), index=True, nullable=False)  # e.g., DEL-BOM
    airline = Column(String(50), nullable=False)
    advance_window = Column(Integer, nullable=False)  # 1 for T+1, 15 for T+15
    base_fare = Column(Float, nullable=False)
    tax_amount = Column(Float, nullable=False)
    total_price = Column(Float, nullable=False)
    rule_135_breach = Column(Boolean, default=False, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "route": self.route,
            "airline": self.airline,
            "advance_window": self.advance_window,
            "base_fare": self.base_fare,
            "tax_amount": self.tax_amount,
            "total_price": self.total_price,
            "rule_135_breach": self.rule_135_breach,
        }


class DailyIndex(Base):
    """SQLAlchemy model for persistent daily APIx inflation index values."""

    __tablename__ = "daily_index"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    date = Column(Date, unique=True, index=True, nullable=False)
    apix_value = Column(Float, nullable=False)
    daily_change_pct = Column(Float, default=0.0)
    num_fares = Column(Integer, default=0)
    routes_covered = Column(Integer, default=0)
    weighted_avg_fare = Column(Float, default=0.0)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "date": self.date.isoformat() if self.date else None,
            "vayu_value": self.apix_value,
            "daily_change_pct": self.daily_change_pct,
            "num_fares": self.num_fares,
            "routes_covered": self.routes_covered,
            "weighted_avg_fare": self.weighted_avg_fare,
        }
