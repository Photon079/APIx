"""
Data Cleaning & Normalization Pipeline
Separates base fares from taxes, handles missing values, deduplicates records.
"""

import logging
from datetime import datetime, date
from typing import Optional

import pandas as pd

from pipeline.models import RawFareQuote, CleanedFare
from config import TAX_RATIO_ESTIMATE, MIN_FARE_INR, MAX_FARE_INR

logger = logging.getLogger("apix.cleaner")


class FareCleaner:
    """
    Cleans and normalizes raw fare data into validated CleanedFare records.
    Handles tax separation, missing values, and deduplication.
    """

    def __init__(self):
        self.stats = {
            "total_raw": 0,
            "cleaned": 0,
            "dropped_invalid": 0,
            "dropped_duplicate": 0,
            "dropped_outlier": 0,
            "tax_estimated": 0,
        }

    def clean_batch(self, raw_fares: list[dict]) -> list[CleanedFare]:
        """
        Process a batch of raw fare dictionaries into cleaned records.

        Steps:
        1. Parse into RawFareQuote models
        2. Separate base fare from taxes
        3. Validate and convert to CleanedFare
        4. Deduplicate
        5. Remove outliers
        """
        self.stats["total_raw"] += len(raw_fares)
        logger.info(f"Cleaning batch of {len(raw_fares)} raw fares")

        # Step 1: Parse raw quotes
        raw_quotes = []
        for fare_dict in raw_fares:
            try:
                quote = RawFareQuote(**fare_dict)
                raw_quotes.append(quote)
            except Exception as e:
                logger.warning(f"Failed to parse raw fare: {e}")
                self.stats["dropped_invalid"] += 1

        # Step 2 & 3: Clean and validate each quote
        cleaned = []
        for quote in raw_quotes:
            try:
                cleaned_fare = self._clean_single(quote)
                if cleaned_fare:
                    cleaned.append(cleaned_fare)
            except Exception as e:
                logger.warning(f"Failed to clean fare {quote.origin}-{quote.destination}: {e}")
                self.stats["dropped_invalid"] += 1

        # Step 4: Deduplicate
        cleaned = self._deduplicate(cleaned)

        # Step 5: Remove outliers
        cleaned = self._remove_outliers(cleaned)

        self.stats["cleaned"] = len(cleaned)
        logger.info(
            f"Cleaning complete: {len(cleaned)} valid fares "
            f"({self.stats['dropped_invalid']} invalid, "
            f"{self.stats['dropped_duplicate']} dupes, "
            f"{self.stats['dropped_outlier']} outliers)"
        )

        return cleaned

    def _clean_single(self, raw: RawFareQuote) -> Optional[CleanedFare]:
        """Clean a single raw fare quote."""
        # Normalize airport codes
        origin = raw.origin.strip().upper()
        destination = raw.destination.strip().upper()

        # Determine total fare
        total_fare = raw.total_fare
        if total_fare is None or total_fare <= 0:
            if raw.base_fare and raw.base_fare > 0:
                total_fare = raw.base_fare / (1 - TAX_RATIO_ESTIMATE)
            else:
                logger.warning(f"No valid fare data for {origin}-{destination}")
                self.stats["dropped_invalid"] += 1
                return None

        # Separate base fare from taxes
        base_fare, taxes = self._separate_taxes(raw.base_fare, raw.taxes, total_fare)

        # Parse travel date
        if isinstance(raw.travel_date, str):
            try:
                travel_date = date.fromisoformat(raw.travel_date)
            except ValueError:
                try:
                    travel_date = datetime.strptime(raw.travel_date, "%d/%m/%Y").date()
                except ValueError:
                    logger.warning(f"Unparseable travel date: {raw.travel_date}")
                    self.stats["dropped_invalid"] += 1
                    return None
        else:
            travel_date = raw.travel_date

        # Scrape timestamp
        scrape_ts = raw.scrape_timestamp or datetime.now()

        # Advance days
        advance_days = raw.advance_days
        if advance_days is None:
            advance_days = (travel_date - scrape_ts.date()).days
            advance_days = max(0, advance_days)

        # Airline name cleanup
        airline = (raw.airline or "Unknown").strip().title()

        try:
            return CleanedFare(
                origin=origin,
                destination=destination,
                route=f"{origin}-{destination}",
                airline=airline,
                flight_number=raw.flight_number,
                base_fare=round(base_fare, 2),
                taxes=round(taxes, 2),
                total_fare=round(total_fare, 2),
                travel_date=travel_date,
                scrape_timestamp=scrape_ts,
                advance_days=advance_days,
                source=raw.source,
            )
        except Exception as e:
            logger.warning(f"Validation error: {e}")
            self.stats["dropped_invalid"] += 1
            return None

    def _separate_taxes(
        self,
        base_fare: Optional[float],
        taxes: Optional[float],
        total_fare: float,
    ) -> tuple[float, float]:
        """
        Separate base fare from taxes/UDF/surcharges.

        Logic:
        - If both base and taxes provided: use them directly
        - If only base provided: taxes = total - base
        - If only taxes provided: base = total - taxes
        - If neither: estimate using industry ratio (~78% base, ~22% tax)
        """
        if base_fare and base_fare > 0 and taxes is not None and taxes >= 0:
            return base_fare, taxes

        if base_fare and base_fare > 0:
            return base_fare, total_fare - base_fare

        if taxes is not None and taxes > 0:
            return total_fare - taxes, taxes

        # Estimate: Indian domestic economy tax breakdown
        # GST (5%) + UDF (~₹200-500) + PSF (~₹200) + convenience fee
        # Roughly 22% of total fare
        self.stats["tax_estimated"] += 1
        estimated_taxes = total_fare * TAX_RATIO_ESTIMATE
        estimated_base = total_fare - estimated_taxes
        logger.debug(
            f"Estimated tax split: ₹{estimated_base:.0f} base + ₹{estimated_taxes:.0f} tax "
            f"= ₹{total_fare:.0f} total"
        )
        return estimated_base, estimated_taxes

    def _deduplicate(self, fares: list[CleanedFare]) -> list[CleanedFare]:
        """Remove duplicate fare quotes based on key fields."""
        seen = set()
        unique = []

        for fare in fares:
            # Dedup key: airline + route + date + fare amount
            key = (
                fare.airline.lower(),
                fare.origin,
                fare.destination,
                fare.travel_date.isoformat(),
                round(fare.total_fare),
            )
            if key not in seen:
                seen.add(key)
                unique.append(fare)
            else:
                self.stats["dropped_duplicate"] += 1

        if len(fares) != len(unique):
            logger.info(f"Deduplication: {len(fares)} → {len(unique)} fares")

        return unique

    def _remove_outliers(self, fares: list[CleanedFare]) -> list[CleanedFare]:
        """Remove statistical outliers using IQR method within each route."""
        if len(fares) < 4:
            return fares

        # Group by route
        route_groups: dict[str, list[CleanedFare]] = {}
        for fare in fares:
            route_groups.setdefault(fare.route, []).append(fare)

        result = []
        for route, group in route_groups.items():
            prices = [f.total_fare for f in group]
            df = pd.Series(prices)
            q1 = df.quantile(0.25)
            q3 = df.quantile(0.75)
            iqr = q3 - q1
            lower = max(MIN_FARE_INR, q1 - 1.5 * iqr)
            upper = min(MAX_FARE_INR, q3 + 1.5 * iqr)

            for fare in group:
                if lower <= fare.total_fare <= upper:
                    result.append(fare)
                else:
                    logger.info(
                        f"Outlier removed: {route} ₹{fare.total_fare:.0f} "
                        f"(bounds: ₹{lower:.0f}–₹{upper:.0f})"
                    )
                    self.stats["dropped_outlier"] += 1

        return result

    def get_stats(self) -> dict:
        """Return cleaning statistics."""
        return self.stats.copy()
