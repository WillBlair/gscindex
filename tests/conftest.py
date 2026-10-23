"""Test-wide guards, loaded by pytest before any test module imports app, config or data.

The local ``.env`` DATABASE_URL points at the production database. It is blanked here so
every test uses SQLite (or its own mock) even when the shell exports a Postgres URL;
python-dotenv never overrides a variable that is already set, even to an empty string.
The background updater is disabled so importing ``app`` never starts fetching.
"""
import os

os.environ["DATABASE_URL"] = ""
os.environ["GSC_DISABLE_BACKGROUND"] = "1"
