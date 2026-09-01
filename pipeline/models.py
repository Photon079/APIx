"""
Pydantic Data Models for the Vayu pipeline.
Strict validation for raw scraper output and cleaned fare records.
"""

from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator
import re


class RawFareQuote(BaseModel):
    """Raw fare data as extracted from the scraper (loose typing)."""

    origin: str
    destination: str
    airline: Optional[str] = None
    flight_number: Optional[str] = None
    departure_time: Optional[str] = None
    arrival_time: Optional[str] = None
    base_fare: Optional[float] = None
    taxes: Optional[float] = None
    total_fare: Optional[float] = None
    travel_date: str | date
    scrape_timestamp: Optional[datetime] = None
    advance_days: Optional[int] = None
    source: str = "google_flights"


class CleanedFare(BaseModel):
    """
    Validated, normalized fare record ready for index calculation.
    Enforces strict types and business rules.
    """

    origin: str = Field(..., min_length=3, max_length=3, description="3-letter IATA origin code")
    destination: str = Field(..., min_length=3, max_length=3, description="3-letter IATA destination code")
    route: str = Field(..., description="Route string e.g. DEL-BOM")
    airline: str = Field(..., min_length=1, description="Airline name")
    flight_number: Optional[str] = None
    base_fare: float = Field(..., ge=0, description="Base fare in INR (excl. taxes)")
    taxes: float = Field(..., ge=0, description="Taxes, UDF, convenience fees in INR")
    total_fare: float = Field(..., gt=0, description="Total fare in INR")
    travel_date: date
    scrape_timestamp: datetime
    advance_days: int = Field(..., ge=0, description="Days between scrape and travel")
    source: str = "google_flights"

    @field_validator("origin", "destination")
    @classmethod
    def validate_iata_code(cls, v: str) -> str:
        """Validate that airport codes are 3 uppercase letters."""
        v = v.strip().upper()
        if not re.match(r"^[A-Z]{3}$", v):
            raise ValueError(f"Invalid IATA code: '{v}' — must be exactly 3 uppercase letters")
        return v

    @model_validator(mode="after")
    def validate_fare_consistency(self):
        """Ensure base_fare + taxes approximately equals total_fare."""
        if self.base_fare and self.taxes:
            computed_total = self.base_fare + self.taxes
            tolerance = self.total_fare * 0.05  # 5% tolerance
            if abs(computed_total - self.total_fare) > tolerance:
                # Auto-correct: trust total_fare, adjust taxes
                self.taxes = self.total_fare - self.base_fare
        return self

    @model_validator(mode="after")
    def validate_route_field(self):
        """Auto-populate the route field."""
        self.route = f"{self.origin}-{self.destination}"
        return self


class DailyIndexRecord(BaseModel):
    """A single day's computed Vayu value."""

    date: date
    vayu_value: float = Field(..., gt=0, description="Computed Vayu index value")
    daily_change_pct: Optional[float] = Field(None, description="Day-over-day % change")
    num_fares: int = Field(..., ge=0, description="Number of fare quotes used")
    routes_covered: int = Field(..., ge=0, description="Number of routes with data")
    weighted_avg_fare: float = Field(..., gt=0, description="Weighted average fare in INR")


class ValidationDataPoint(BaseModel):
    """A single data point for backtest validation."""

    date: date
    vayu_value: float
    dgca_avg_fare: float
    route: str
