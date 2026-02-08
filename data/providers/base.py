"""
Base Data Provider
==================
Abstract interface that all API-backed data providers must implement.

When you're ready to hook up real APIs (e.g., NOAA for weather, MarineTraffic
for port congestion, EIA for energy prices), create a subclass of
``BaseProvider`` in this directory and implement ``fetch_current()`` and
``fetch_history()``.

Example
-------
>>> class NOAAWeatherProvider(BaseProvider):
...     category = "weather"
...     def fetch_current(self) -> float:
...         # call NOAA API, normalize to 0–100
...         ...
...     def fetch_history(self, days: int) -> pd.Series:
...         # return historical scores
...         ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class BaseProvider(ABC):
    """Contract for all supply-chain data providers."""

    # Override in subclass — must match a key in config.CATEGORY_WEIGHTS
    category: str = ""

    @abstractmethod
    def fetch_current(self) -> float:
        """Return the current category score (0–100, 100 = healthiest).

        Implementations should handle API errors gracefully and return
        the last known good value when a fetch fails.
        """

    @abstractmethod
    def fetch_history(self, days: int) -> pd.Series:
        """Return a time-indexed Series of historical scores.

        Parameters
        ----------
        days : int
            Number of trailing days to retrieve.

        Returns
        -------
        pd.Series
            Float scores indexed by ``pd.DatetimeIndex``.
        """

    def __repr__(self) -> str:
        return f"<{type(self).__name__} category={self.category!r}>"
