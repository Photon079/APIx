"""
Price Index Calculator — Chain-based Laspeyres Index with DGCA traffic weights.
Computes a unified daily APIx value aligned with MoSPI's CPI methodology.
Persists all computed index values to disk.
"""

import json
import logging
from datetime import date, timedelta, datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from pipeline.models import CleanedFare, DailyIndexRecord
from config import INDEX_BASE_VALUE, INDEX_BASE_DATE, DATA_DIR, SCRAPED_DIR

logger = logging.getLogger("vayu.calculator")

INDEX_CACHE_FILE = DATA_DIR / "index_history.json"


class VayuCalculator:
    """
    Computes the Vayu Airfare Price Index using a chain-based Laspeyres methodology.

    Formula:
        Vayu_t = Vayu_{t-1} × Σ(w_r × P_r,t) / Σ(w_r × P_r,t-1)

    Where:
        w_r   = DGCA passenger traffic weight for route r
        P_r,t = weighted average fare for route r on day t
    """

    def __init__(self):
        self.weights = self._load_traffic_weights()
        self.index_history: list[DailyIndexRecord] = []
        self.fare_history: dict[str, dict[str, float]] = {}
        self._base_value = INDEX_BASE_VALUE
        self._base_date = INDEX_BASE_DATE
        self._loaded_from_cache = False

    def _load_traffic_weights(self) -> dict[str, float]:
        """Load DGCA passenger traffic volume weights."""
        weights_path = DATA_DIR / "traffic_weights.json"
        try:
            with open(weights_path) as f:
                data = json.load(f)
            weights = {route: info["weight"] for route, info in data.items()}
            logger.info(f"Loaded traffic weights: {weights}")
            return weights
        except FileNotFoundError:
            logger.warning("traffic_weights.json not found — using defaults")
            return {"DEL-BOM": 0.45, "BOM-BLR": 0.30, "DEL-BLR": 0.25}

    def load_cached_history(self) -> bool:
        """Load previously computed index history from disk."""
        if INDEX_CACHE_FILE.exists():
            try:
                with open(INDEX_CACHE_FILE) as f:
                    data = json.load(f)

                self.index_history = []
                self.fare_history = data.get("fare_history", {})

                for record in data.get("index_history", []):
                    self.index_history.append(DailyIndexRecord(
                        date=date.fromisoformat(record["date"]),
                        vayu_value=record["vayu_value"],
                        daily_change_pct=record.get("daily_change_pct", 0),
                        num_fares=record.get("num_fares", 0),
                        routes_covered=record.get("routes_covered", 0),
                        weighted_avg_fare=record.get("weighted_avg_fare", 0),
                    ))

                self._loaded_from_cache = True
                logger.info(f"Loaded {len(self.index_history)} cached index records")
                return True
            except Exception as e:
                logger.warning(f"Failed to load cached history: {e}")

        return False

    def save_history(self) -> None:
        """Persist computed index history to disk."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "index_history": [
                {
                    "date": record.date.isoformat(),
                    "vayu_value": record.vayu_value,
                    "daily_change_pct": record.daily_change_pct,
                    "num_fares": record.num_fares,
                    "routes_covered": record.routes_covered,
                    "weighted_avg_fare": record.weighted_avg_fare,
                }
                for record in self.index_history
            ],
            "fare_history": self.fare_history,
        }
        with open(INDEX_CACHE_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved {len(self.index_history)} index records to cache")

    def compute_daily_index(
        self,
        fares: list[CleanedFare],
        target_date: Optional[date] = None,
    ) -> DailyIndexRecord:
        """
        Compute the Vayu value for a given day from cleaned fare data.
        """
        if target_date is None:
            target_date = date.today()

        date_str = target_date.isoformat()

        # Check if we already have this date computed
        for existing in self.index_history:
            if existing.date == target_date:
                # Update with new data (re-scrape for same day)
                self.index_history.remove(existing)
                break

        # Aggregate fares by route
        route_avg_fares = self._aggregate_by_route(fares)

        if not route_avg_fares:
            logger.warning(f"No fare data for {date_str}")
            if self.index_history:
                return self.index_history[-1]
            return DailyIndexRecord(
                date=target_date, vayu_value=self._base_value,
                daily_change_pct=0.0, num_fares=0,
                routes_covered=0, weighted_avg_fare=0.0,
            )

        # Store fare history
        self.fare_history[date_str] = route_avg_fares

        # Compute chain-based index
        vayu_value = self._chain_index(target_date, route_avg_fares)

        # Calculate daily change
        prev_value = self._base_value
        for rec in self.index_history:
            if rec.date < target_date:
                prev_value = rec.vayu_value
        daily_change = ((vayu_value / prev_value) - 1) * 100 if prev_value else 0.0

        # Weighted average fare
        total_weighted = sum(self.weights.get(r, 0) * fare for r, fare in route_avg_fares.items())
        total_weight = sum(self.weights.get(r, 0) for r in route_avg_fares)
        weighted_avg = total_weighted / total_weight if total_weight else 0

        record = DailyIndexRecord(
            date=target_date,
            vayu_value=round(vayu_value, 2),
            daily_change_pct=round(daily_change, 4),
            num_fares=len(fares),
            routes_covered=len(route_avg_fares),
            weighted_avg_fare=round(weighted_avg, 2),
        )

        self.index_history.append(record)
        # Keep sorted by date
        self.index_history.sort(key=lambda r: r.date)

        # Auto-save after each computation
        self.save_history()

        logger.info(
            f"Vayu[{date_str}] = {record.vayu_value} "
            f"({record.daily_change_pct:+.3f}%) │ "
            f"{record.num_fares} fares, {record.routes_covered} routes)"
        )

        return record

    def _aggregate_by_route(self, fares: list[CleanedFare]) -> dict[str, float]:
        """Aggregate cleaned fares by route using weighted average."""
        route_fares: dict[str, list[tuple[float, float]]] = {}

        for fare in fares:
            weight = 1.0 / (1.0 + fare.advance_days * 0.05)
            route_fares.setdefault(fare.route, []).append((fare.total_fare, weight))

        route_avgs = {}
        for route, fare_weights in route_fares.items():
            prices = np.array([fw[0] for fw in fare_weights])
            weights = np.array([fw[1] for fw in fare_weights])
            weighted_avg = float(np.average(prices, weights=weights))
            route_avgs[route] = round(weighted_avg, 2)

        return route_avgs

    def _chain_index(self, target_date: date, current_fares: dict[str, float]) -> float:
        """Compute chain-based Laspeyres index."""
        prev_date = target_date - timedelta(days=1)
        prev_date_str = prev_date.isoformat()
        prev_fares = self.fare_history.get(prev_date_str)

        if not prev_fares:
            if self.index_history:
                # Find the most recent record before target_date
                prev_records = [r for r in self.index_history if r.date < target_date]
                if prev_records:
                    if prev_records[-1].date == prev_date:
                        return prev_records[-1].vayu_value
            return self._base_value

        numerator = 0.0
        denominator = 0.0

        for route, weight in self.weights.items():
            p_current = current_fares.get(route)
            p_previous = prev_fares.get(route)

            if p_current is not None and p_previous is not None and p_previous > 0:
                numerator += weight * p_current
                denominator += weight * p_previous
            elif p_current is not None:
                numerator += weight * p_current
                denominator += weight * p_current

        if denominator == 0:
            return self._base_value

        prev_records = [r for r in self.index_history if r.date < target_date]
        prev_index = prev_records[-1].vayu_value if prev_records else self._base_value
        price_ratio = numerator / denominator
        return prev_index * price_ratio

    def generate_backtest_history(self, days: int = 30) -> list[DailyIndexRecord]:
        """
        Generate a 30-day backtested index history.
        Uses deterministic data so results are identical across restarts.
        """
        # If we already have cached history with enough data, skip regeneration
        if self._loaded_from_cache and len(self.index_history) >= days:
            logger.info(f"Using cached backtest history ({len(self.index_history)} records)")
            return self.index_history

        from scraper.engine import VayuScraper
        from pipeline.cleaner import FareCleaner
        from pipeline.validator import FareValidator

        scraper = VayuScraper()
        cleaner = FareCleaner()
        validator = FareValidator()

        logger.info(f"Generating {days}-day backtest history (deterministic)...")

        today = date.today()
        start_date = today - timedelta(days=days)

        for day_offset in range(days + 1):
            current_date = start_date + timedelta(days=day_offset)

            # Skip if we already have this date
            if any(r.date == current_date for r in self.index_history):
                continue

            all_fares = []
            scrape_ts = datetime.combine(current_date, datetime.min.time().replace(hour=12))

            for origin, dest in [("DEL", "BOM"), ("BOM", "BLR"), ("DEL", "BLR")]:
                for advance in [1, 15]:
                    travel_date = current_date + timedelta(days=advance)
                    fares = scraper._generate_deterministic(
                        origin, dest, travel_date, advance, scrape_ts
                    )
                    for fare in fares:
                        fare["scrape_timestamp"] = scrape_ts.isoformat()
                    all_fares.extend(fares)

            cleaned = cleaner.clean_batch(all_fares)
            validated = validator.validate_batch(cleaned)
            self.compute_daily_index(validated, current_date)

        logger.info(f"Backtest complete: {len(self.index_history)} data points")
        return self.index_history

    def get_correlation_data(self) -> dict:
        """Load historical DGCA data and compute correlation with Vayu."""
        dgca_path = DATA_DIR / "historical_dgca.csv"
        try:
            dgca_df = pd.read_csv(dgca_path, parse_dates=["date"])
        except FileNotFoundError:
            return {"correlation_r": 0, "r_squared": 0, "data_points": 0, "series": {"dates": [], "vayu": [], "dgca_fare": [], "dgca_normalized": []}}

        # Build Vayu series
        vayu_series = {record.date.isoformat(): record.vayu_value for record in self.index_history}

        matched_dates, vayu_values, dgca_values = [], [], []

        for _, row in dgca_df.iterrows():
            date_str = row["date"].strftime("%Y-%m-%d")
            if date_str in vayu_series:
                matched_dates.append(date_str)
                vayu_values.append(vayu_series[date_str])
                dgca_values.append(row["dgca_avg_fare"])

        correlation = 0.0
        if len(vayu_values) >= 3:
            vayu_arr = np.array(vayu_values)
            dgca_arr = np.array(dgca_values)
            dgca_normalized = (dgca_arr / dgca_arr[0]) * 100
            correlation = float(np.corrcoef(vayu_arr, dgca_normalized)[0, 1])

        return {
            "correlation_r": round(correlation, 4),
            "r_squared": round(correlation ** 2, 4),
            "data_points": len(matched_dates),
            "series": {
                "dates": matched_dates,
                "vayu": vayu_values,
                "dgca_fare": dgca_values,
                "dgca_normalized": (np.array(dgca_values) / dgca_values[0] * 100).tolist() if dgca_values else [],
            },
        }

    def get_current_value(self) -> Optional[DailyIndexRecord]:
        return self.index_history[-1] if self.index_history else None

    def get_history_json(self) -> list[dict]:
        return [
            {
                "date": r.date.isoformat(),
                "vayu_value": r.vayu_value,
                "daily_change_pct": r.daily_change_pct,
                "num_fares": r.num_fares,
                "routes_covered": r.routes_covered,
                "weighted_avg_fare": r.weighted_avg_fare,
            }
            for r in self.index_history
        ]

    def get_route_breakdown(self) -> dict:
        if not self.fare_history:
            return {}

        latest_date = max(self.fare_history.keys())
        latest_fares = self.fare_history[latest_date]

        breakdown = {}
        dates = sorted(self.fare_history.keys())
        for route in latest_fares:
            sparkline = []
            for d in dates[-7:]:
                if route in self.fare_history[d]:
                    sparkline.append(self.fare_history[d][route])
            breakdown[route] = {
                "current_fare": latest_fares[route],
                "sparkline": sparkline,
            }
        return breakdown
