"""
Strait of Hormuz Ship Monitor
==============================
Tracks commercial shipping through the Strait of Hormuz — the narrow waterway
between the Persian Gulf and the Gulf of Oman through which ~20% of global
oil supply transits.

Data sourced from https://hormuz.data-tracking.net/ — free public API, no key.

Score logic
-----------
Higher score = healthier chokepoint flow.
Crossing volume vs trailing 30-day average determines the baseline.
Oil export barrel volume adds additional signal layers.

If crossings drop significantly below normal, the score drops — that means
something is blocking the strait (geopolitical tension, military action, etc.).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
import requests

from data.providers.base import BaseProvider

logger = logging.getLogger(__name__)

_BASE_URL = "https://hormuz.data-tracking.net/api"
_TIMEOUT = 15

class HormuzStraitProvider(BaseProvider):
    """Chokepoint flow monitor for the Strait of Hormuz."""

    category = "geopolitical"

    def fetch_current(self) -> tuple[float, dict]:
        """Score current strait health based on crossing volume vs trailing norm."""
        summary = self._get_summary()
        daily = self._get_daily_crossings()

        crossings_24h = summary.get("total_crossings", 0)
        oil_barrels = summary.get("oil_export_barrels", 0)
        ships_in_strait = summary.get("in_strait", 0)
        total_ships = summary.get("total_ships", 0)

        # Trailing 30-day average crossing volume
        trailing = self._compute_trailing_avg(daily)

        # Baseline score: how does today compare to the trailing norm?
        if trailing and trailing > 0:
            ratio = crossings_24h / trailing
        else:
            ratio = 1.0

        # Ratio of 1.0 = normal flow → score ~80
        # Ratio < 0.5 = major disruption → score plummets
        # Ratio > 1.5 = elevated flow → still healthy but slightly cautious
        score = 80.0
        if ratio < 1.0:
            score = 50.0 + (ratio * 30.0)  # 50–80 range
        elif ratio > 1.5:
            score = 85.0  # busy but fine
        else:
            score = 80.0 + (ratio - 1.0) * 40.0  # 80–100 range

        score = max(0.0, min(100.0, score))

        # Oil barrel flow as a confirming signal
        oil_score = 80.0
        if oil_barrels < 200_000:
            oil_score = 20.0  # severe disruption
        elif oil_barrels < 500_000:
            oil_score = 50.0
        elif oil_barrels < 800_000:
            oil_score = 70.0
        elif oil_barrels < 1_200_000:
            oil_score = 85.0
        else:
            oil_score = 95.0  # robust flow

        additional = {
            "hormuz_oil_flow": (
                oil_score,
                {
                    "source": "Strait of Hormuz Ship Monitor",
                    "raw_value": f"{oil_barrels:,}",
                    "raw_label": "Oil exports (24h barrels)",
                    "description": "Crude + petrochemical barrels transiting the Strait of Hormuz in the last 24 hours. A critical energy chokepoint signal.",
                    "calculation": "Linear thresholds — below 200K barrels = severe disruption",
                    "updated": summary.get("last_poll", ""),
                },
            ),
        }

        metadata = {
            "source": "Strait of Hormuz Ship Monitor",
            "raw_value": str(crossings_24h),
            "raw_label": "Strait crossings (24h)",
            "description": "Total commercial vessel crossings through the Strait of Hormuz (inbound + outbound). ~20% of global oil supply transits this chokepoint.",
            "calculation": f"Crossing volume vs 30-day trailing avg ({trailing:.1f}/day). Ratio: {ratio:.2f}. Score clamped to 0–100.",
            "updated": summary.get("last_poll", ""),
            "additional_scores": additional,
            "extra": {
                "ships_in_strait": ships_in_strait,
                "total_ships": total_ships,
                "persian_gulf_ships": summary.get("persian_gulf_ships", 0),
                "oil_exports": oil_barrels,
            },
        }

        return score, metadata

    def fetch_history(self, days: int = 90) -> pd.Series:
        """Build history from daily crossing counts."""
        daily = self._get_daily_crossings()
        if not daily:
            return _make_hormuz_fallback(days, self.category)

        records = []
        for entry in daily:
            try:
                ts = pd.Timestamp(entry["day"])
            except Exception:
                continue
            count = entry.get("count", 0)
            records.append({"date": ts, "count": count})

        if not records:
            return _make_hormuz_fallback(days, self.category)

        df = pd.DataFrame(records)
        df = df.sort_values("date").drop_duplicates(subset="date")

        # Normalize to score (same logic as fetch_current, per day)
        # Simple approach: 80 = normal, higher = better flow
        rolling_avg = df["count"].rolling(30, min_periods=7).mean().shift(1)
        ratio = df["count"] / rolling_avg
        scores = 50.0 + ratio.clip(0.0, 2.0) * 25.0
        scores = scores.clip(0.0, 100.0)

        df["score"] = scores
        df = df.set_index("date")["score"]
        df = df.reindex(
            pd.date_range(
                end=df.index.max(),
                periods=days,
                freq="D",
            )
        )
        return df.fillna(method="ffill").fillna(80.0).tail(days).rename(self.category)

    def _get_summary(self) -> dict:
        try:
            r = requests.get(f"{_BASE_URL}/summary?hours=24", timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"Hormuz summary fetch failed: {e}")
            return {}

    def _get_daily_crossings(self) -> list:
        try:
            r = requests.get(f"{_BASE_URL}/crossings/daily?days=30", timeout=_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning(f"Hormuz daily crossings fetch failed: {e}")
            return []

    def _compute_trailing_avg(self, daily: list) -> float:
        """Compute trailing 30-day average of total daily crossings."""
        if not daily:
            return 0.0
        # Sum direction counts per day (inbound + outbound + in_strait)
        from collections import defaultdict

        day_totals: dict[str, int] = defaultdict(int)
        for entry in daily:
            day_totals[entry["day"]] += entry.get("count", 0)

        sorted_days = sorted(day_totals.keys())
        if len(sorted_days) < 2:
            return 0.0

        recent = sorted_days[-30:] if len(sorted_days) >= 30 else sorted_days
        values = [day_totals[d] for d in recent]
        return sum(values) / len(values) if values else 0.0


def _make_hormuz_fallback(days: int, name: str) -> pd.Series:
    dates = pd.date_range(
        end=datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0),
        periods=days,
        freq="D",
    )
    series = pd.Series(float("nan"), index=dates, name=name)
    series.iloc[-1] = 80.0
    return series