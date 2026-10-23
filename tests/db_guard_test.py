"""tests/conftest.py keeps every test off the production database."""
import os

import app  # noqa: F401  (imports load_dotenv, which must not restore DATABASE_URL)
from data import database


def test_database_url_is_blank_for_tests():
    assert os.environ["DATABASE_URL"] == ""
    assert os.environ["GSC_DISABLE_BACKGROUND"] == "1"


def test_database_resolves_to_sqlite():
    assert database.get_db_type() == "sqlite"
