"""Test-wide guards, loaded by pytest before any test module imports app, config or data.

The local ``.env`` DATABASE_URL points at the production database. It is blanked here so
every test uses SQLite (or its own mock) even when the shell exports a Postgres URL;
python-dotenv never overrides a variable that is already set, even to an empty string.
The background updater is disabled so importing ``app`` never starts fetching.
"""
import os
import sys

import pytest

os.environ["DATABASE_URL"] = ""
os.environ["GSC_DISABLE_BACKGROUND"] = "1"


@pytest.fixture(autouse=True)
def _no_remembered_database_reads():
    """The aggregator remembers stored-score reads for the clock hour; never across tests."""
    aggregator = sys.modules.get("data.aggregator")
    if aggregator is not None and hasattr(aggregator, "_HOURLY"):
        aggregator._HOURLY.clear()
    yield
