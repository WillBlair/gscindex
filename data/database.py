"""
Database Module for Newsletter Subscribers
==========================================
Handles connections to PostgreSQL (for production) or SQLite (for local fallback)
to persist user emails.
"""

import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Path for local SQLite fallback (development only).
SQLITE_PATH = os.path.join(os.path.dirname(__file__), "subscribers.db")


def _resolve_db_config() -> tuple[str, str | None]:
    """Determine the database backend to use.

    Evaluated lazily at *connection time* — not at import time — so that
    environment variables loaded after this module is first imported (e.g.
    via ``dotenv.load_dotenv()`` in a cron script) are respected.
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        try:
            import psycopg2  # noqa: F401 – import validates availability
            return "postgres", url
        except ImportError:
            logger.error(
                "psycopg2-binary is required for PostgreSQL connections. "
                "Falling back to SQLite."
            )
            return "sqlite", None
    return "sqlite", None


def get_db_type() -> str:
    """Return the current database backend type ('postgres' or 'sqlite')."""
    db_type, _ = _resolve_db_config()
    return db_type



def __getattr__(name: str):
    """Module-level __getattr__ so ``from data.database import DB_TYPE``
    resolves lazily instead of being pinned at import time."""
    if name == "DB_TYPE":
        return get_db_type()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_connection():
    db_type, url = _resolve_db_config()
    if db_type == "postgres":
        import psycopg2
        return psycopg2.connect(url)
    elif db_type == "sqlite":
        import sqlite3
        # check_same_thread=False is needed because Dash runs in threads
        return sqlite3.connect(SQLITE_PATH, check_same_thread=False)
    return None

def init_db():
    conn = get_connection()
    if not conn:
        logger.warning("No database configured. Cannot initialize.")
        return
        
    db_type = get_db_type()
    try:
        with conn:
            cursor = conn.cursor()
            if db_type == "postgres":
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS subscribers (
                        id SERIAL PRIMARY KEY,
                        email VARCHAR(255) UNIQUE NOT NULL,
                        subscribed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        is_active BOOLEAN DEFAULT TRUE
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS daily_scores (
                        date DATE PRIMARY KEY,
                        score REAL NOT NULL
                    )
                """)
            elif db_type == "sqlite":
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS subscribers (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        email TEXT UNIQUE NOT NULL,
                        subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        is_active BOOLEAN DEFAULT 1
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS daily_scores (
                        date DATE PRIMARY KEY,
                        score REAL NOT NULL
                    )
                """)
        logger.info("Database initialized (%s).", db_type)
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
    finally:
        conn.close()

def add_subscriber(email: str) -> dict:
    conn = get_connection()
    if not conn:
        return {"success": False, "message": "Database not configured."}

    db_type = get_db_type()
    try:
        with conn:
            cursor = conn.cursor()
            if db_type == "postgres":
                # Use ON CONFLICT DO UPDATE to reactivate if previously unsubscribed
                cursor.execute("""
                    INSERT INTO subscribers (email, is_active)
                    VALUES (%s, TRUE)
                    ON CONFLICT (email) DO UPDATE 
                    SET is_active = TRUE
                """, (email,))
            elif db_type == "sqlite":
                # SQLite upsert
                cursor.execute("""
                    INSERT INTO subscribers (email, is_active)
                    VALUES (?, 1)
                    ON CONFLICT(email) DO UPDATE 
                    SET is_active = 1
                """, (email,))
        return {"success": True, "message": "Successfully subscribed!"}
    except Exception as e:
        logger.error(f"Failed to add subscriber: {e}")
        return {"success": False, "message": "An error occurred while subscribing."}
    finally:
        conn.close()

def get_active_subscribers() -> list[str]:
    conn = get_connection()
    if not conn:
        logger.warning("get_active_subscribers: no database connection available.")
        return []

    db_type = get_db_type()
    try:
        cursor = conn.cursor()
        if db_type == "postgres":
            cursor.execute("SELECT email FROM subscribers WHERE is_active = TRUE")
        elif db_type == "sqlite":
            cursor.execute("SELECT email FROM subscribers WHERE is_active = 1")

        rows = cursor.fetchall()
        emails = [row[0] for row in rows]
        logger.info(
            "Fetched %d active subscriber(s) from %s database.",
            len(emails),
            db_type,
        )
        return emails
    except Exception as e:
        logger.error(f"Failed to fetch subscribers: {e}")
        return []
    finally:
        conn.close()

def unsubscribe_user(email: str) -> bool:
    conn = get_connection()
    if not conn:
        return False

    db_type = get_db_type()
    try:
        with conn:
            cursor = conn.cursor()
            if db_type == "postgres":
                cursor.execute("UPDATE subscribers SET is_active = FALSE WHERE email = %s", (email,))
            elif db_type == "sqlite":
                cursor.execute("UPDATE subscribers SET is_active = 0 WHERE email = ?", (email,))
        return True
    except Exception as e:
        logger.error(f"Failed to unsubscribe: {e}")
        return False
    finally:
        conn.close()

def record_daily_score(score: float) -> bool:
    """Record today's score into the database."""
    conn = get_connection()
    if not conn:
        return False

    db_type = get_db_type()
    try:
        with conn:
            cursor = conn.cursor()
            if db_type == "postgres":
                cursor.execute("""
                    INSERT INTO daily_scores (date, score)
                    VALUES (CURRENT_DATE, %s)
                    ON CONFLICT (date) DO UPDATE 
                    SET score = EXCLUDED.score
                """, (score,))
            elif db_type == "sqlite":
                cursor.execute("""
                    INSERT INTO daily_scores (date, score)
                    VALUES (DATE('now'), ?)
                    ON CONFLICT(date) DO UPDATE 
                    SET score = excluded.score
                """, (score,))
        return True
    except Exception as e:
        logger.error(f"Failed to record daily score: {e}")
        return False
    finally:
        conn.close()

def get_previous_daily_score() -> float | None:
    """Fetch the most recent daily score strictly prior to today."""
    conn = get_connection()
    if not conn:
        return None

    db_type = get_db_type()
    try:
        cursor = conn.cursor()
        if db_type == "postgres":
            cursor.execute("SELECT score FROM daily_scores WHERE date < CURRENT_DATE ORDER BY date DESC LIMIT 1")
        elif db_type == "sqlite":
            cursor.execute("SELECT score FROM daily_scores WHERE date < DATE('now') ORDER BY date DESC LIMIT 1")

        row = cursor.fetchone()
        return float(row[0]) if row else None
    except Exception as e:
        logger.error(f"Failed to fetch previous daily score: {e}")
        return None
    finally:
        conn.close()
