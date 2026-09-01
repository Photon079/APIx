"""
Data Validator
IATA code validation, fare range checks, and record-level quality assurance.
"""

import logging
from pipeline.models import CleanedFare
from config import VALID_IATA_CODES, MIN_FARE_INR, MAX_FARE_INR

logger = logging.getLogger("vayu.validator")


class FareValidator:
    """Validates cleaned fare records against business rules."""

    def __init__(self):
        self.stats = {
            "total_validated": 0,
            "passed": 0,
            "failed_iata": 0,
            "failed_fare_range": 0,
            "failed_date": 0,
            "warnings": [],
        }

    def validate_batch(self, fares: list[CleanedFare]) -> list[CleanedFare]:
        """Validate a batch of cleaned fares, returning only valid records."""
        valid = []
        for fare in fares:
            self.stats["total_validated"] += 1
            issues = self._validate_single(fare)
            if not issues:
                valid.append(fare)
                self.stats["passed"] += 1
            else:
                for issue in issues:
                    logger.warning(f"Validation failed for {fare.route}: {issue}")

        logger.info(
            f"Validation: {self.stats['passed']}/{self.stats['total_validated']} passed"
        )
        return valid

    def _validate_single(self, fare: CleanedFare) -> list[str]:
        """Validate a single fare record. Returns list of issues (empty = valid)."""
        issues = []

        # IATA code check against known Indian airports
        if fare.origin not in VALID_IATA_CODES:
            issues.append(f"Unknown origin IATA code: {fare.origin}")
            self.stats["failed_iata"] += 1

        if fare.destination not in VALID_IATA_CODES:
            issues.append(f"Unknown destination IATA code: {fare.destination}")
            self.stats["failed_iata"] += 1

        # Same origin/destination check
        if fare.origin == fare.destination:
            issues.append(f"Origin and destination are the same: {fare.origin}")

        # Fare range sanity check
        if fare.total_fare < MIN_FARE_INR:
            issues.append(
                f"Fare too low: ₹{fare.total_fare:.0f} (min: ₹{MIN_FARE_INR})"
            )
            self.stats["failed_fare_range"] += 1
        elif fare.total_fare > MAX_FARE_INR:
            issues.append(
                f"Fare too high: ₹{fare.total_fare:.0f} (max: ₹{MAX_FARE_INR})"
            )
            self.stats["failed_fare_range"] += 1

        # Base fare should be less than total fare
        if fare.base_fare > fare.total_fare:
            issues.append(
                f"Base fare (₹{fare.base_fare:.0f}) exceeds total "
                f"(₹{fare.total_fare:.0f})"
            )

        # Tax ratio sanity (taxes should be 5-40% of total)
        if fare.total_fare > 0:
            tax_ratio = fare.taxes / fare.total_fare
            if tax_ratio > 0.40:
                self.stats["warnings"].append(
                    f"High tax ratio ({tax_ratio:.0%}) for {fare.route}"
                )
            elif tax_ratio < 0.05:
                self.stats["warnings"].append(
                    f"Low tax ratio ({tax_ratio:.0%}) for {fare.route}"
                )

        # Advance days check
        if fare.advance_days < 0:
            issues.append(f"Negative advance days: {fare.advance_days}")
            self.stats["failed_date"] += 1

        return issues

    def get_stats(self) -> dict:
        """Return validation statistics."""
        return self.stats.copy()
