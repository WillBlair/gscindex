"""
Database Module
===============
Handles connections to PostgreSQL (for production) or SQLite (for local fallback).

Tables:
    subscribers           — newsletter emails
    daily_scores          — one composite score per calendar day
    daily_category_scores — one score per category per calendar day
                            (the real measurement history behind trend charts)
"""

import os
import logging
import threading
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# In-memory cache to avoid hammering Neon on every page load / background cycle.
# previous_score is fetched once per calendar day; daily scores are written at
# most once per hour (upsert, so the stored row converges to the day's last value).
_score_cache_lock = threading.Lock()
_cached_previous_score: float | None = None
_cached_previous_date: date | None = None       # The date we fetched it for
_daily_scores_written_hour: datetime | None = None  # Hour of the last daily-score write

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
        import time
        # Timeout prevents Neon serverless cold starts from blocking Gunicorn
        # threads indefinitely, but we retry to allow for cold starts.
        for attempt in range(3):
            try:
                return psycopg2.connect(url, connect_timeout=10)
            except psycopg2.OperationalError as e:
                if attempt == 2:
                    raise
                logger.warning(f"Database connection timeout, retrying... ({e})")
                time.sleep(2)
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
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS daily_category_scores (
                        date DATE NOT NULL,
                        category VARCHAR(64) NOT NULL,
                        score REAL NOT NULL,
                        PRIMARY KEY (date, category)
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS dashboard_snapshot (
                        id INTEGER PRIMARY KEY,
                        payload TEXT NOT NULL,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS newsletter_sends (
                        send_date DATE NOT NULL,
                        email VARCHAR(255) NOT NULL,
                        sent_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (send_date, email)
                    )
                """)
                cursor.execute(
                    "ALTER TABLE subscribers ADD COLUMN IF NOT EXISTS unsubscribed_at "
                    "TIMESTAMP WITH TIME ZONE"
                )
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
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS daily_category_scores (
                        date DATE NOT NULL,
                        category TEXT NOT NULL,
                        score REAL NOT NULL,
                        PRIMARY KEY (date, category)
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS dashboard_snapshot (
                        id INTEGER PRIMARY KEY,
                        payload TEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS newsletter_sends (
                        send_date DATE NOT NULL,
                        email TEXT NOT NULL,
                        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (send_date, email)
                    )
                """)
                columns = {row[1] for row in cursor.execute("PRAGMA table_info(subscribers)")}
                if "unsubscribed_at" not in columns:
                    cursor.execute("ALTER TABLE subscribers ADD COLUMN unsubscribed_at TIMESTAMP")
        logger.info("Database initialized (%s).", db_type)
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
    finally:
        conn.close()

_OPTED_OUT_RESULT = {
    "success": False,
    "message": "This address unsubscribed earlier, so it can't be re-added from the form. "
               "Reply to any past briefing to resubscribe.",
}


def add_subscriber(email: str) -> dict:
    conn = get_connection()
    if not conn:
        return {"success": False, "message": "Database not configured."}

    db_type = get_db_type()
    try:
        with conn:
            cursor = conn.cursor()
            if db_type == "postgres":
                # Anyone can type any address into the form, so an address
                # that unsubscribed is never silently reactivated.
                cursor.execute(
                    "SELECT unsubscribed_at FROM subscribers WHERE email = %s", (email,)
                )
                row = cursor.fetchone()
                if row and row[0] is not None:
                    return _OPTED_OUT_RESULT
                cursor.execute("""
                    INSERT INTO subscribers (email, is_active)
                    VALUES (%s, TRUE)
                    ON CONFLICT (email) DO NOTHING
                """, (email,))
            elif db_type == "sqlite":
                cursor.execute(
                    "SELECT unsubscribed_at FROM subscribers WHERE email = ?", (email,)
                )
                row = cursor.fetchone()
                if row and row[0] is not None:
                    return _OPTED_OUT_RESULT
                cursor.execute("""
                    INSERT INTO subscribers (email, is_active)
                    VALUES (?, 1)
                    ON CONFLICT(email) DO NOTHING
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
                cursor.execute(
                    "UPDATE subscribers SET is_active = FALSE, "
                    "unsubscribed_at = COALESCE(unsubscribed_at, CURRENT_TIMESTAMP) WHERE email = %s",
                    (email,),
                )
            elif db_type == "sqlite":
                cursor.execute(
                    "UPDATE subscribers SET is_active = 0, "
                    "unsubscribed_at = COALESCE(unsubscribed_at, CURRENT_TIMESTAMP) WHERE email = ?",
                    (email,),
                )
        return True
    except Exception as e:
        logger.error(f"Failed to unsubscribe: {e}")
        return False
    finally:
        conn.close()

def record_daily_scores(composite: float, category_scores: dict[str, float]) -> bool:
    """Upsert today's composite and per-category scores.

    Writes at most once per hour (the 5-minute background cycle would
    otherwise burn Neon compute). Upserts mean the stored row converges
    to the day's last reading rather than freezing the first one.
    """
    global _daily_scores_written_hour

    now_hour = datetime.now().replace(minute=0, second=0, microsecond=0)
    with _score_cache_lock:
        if _daily_scores_written_hour == now_hour:
            return True  # Already persisted this hour

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
                """, (composite,))
                for category, score in category_scores.items():
                    cursor.execute("""
                        INSERT INTO daily_category_scores (date, category, score)
                        VALUES (CURRENT_DATE, %s, %s)
                        ON CONFLICT (date, category) DO UPDATE
                        SET score = EXCLUDED.score
                    """, (category, float(score)))
            elif db_type == "sqlite":
                cursor.execute("""
                    INSERT INTO daily_scores (date, score)
                    VALUES (DATE('now'), ?)
                    ON CONFLICT(date) DO UPDATE
                    SET score = excluded.score
                """, (composite,))
                for category, score in category_scores.items():
                    cursor.execute("""
                        INSERT INTO daily_category_scores (date, category, score)
                        VALUES (DATE('now'), ?, ?)
                        ON CONFLICT(date, category) DO UPDATE
                        SET score = excluded.score
                    """, (category, float(score)))
        with _score_cache_lock:
            _daily_scores_written_hour = now_hour
        return True
    except Exception as e:
        logger.error(f"Failed to record daily scores: {e}")
        return False
    finally:
        conn.close()


def get_category_score_history(category: str, days: int):
    """Return stored daily scores for one category as a pd.Series.

    The series only covers days that were actually measured — it may be
    shorter than ``days`` (or empty) while history is still accumulating.
    Charts render the gap honestly instead of backfilling synthetic data.
    """
    import pandas as pd

    conn = get_connection()
    if not conn:
        return pd.Series(dtype=float, name=category)

    db_type = get_db_type()
    try:
        cursor = conn.cursor()
        if db_type == "postgres":
            cursor.execute("""
                SELECT date, score FROM daily_category_scores
                WHERE category = %s AND date >= CURRENT_DATE - %s
                ORDER BY date ASC
            """, (category, days))
        elif db_type == "sqlite":
            cursor.execute("""
                SELECT date, score FROM daily_category_scores
                WHERE category = ? AND date >= DATE('now', ?)
                ORDER BY date ASC
            """, (category, f"-{days} days"))

        rows = cursor.fetchall()
        if not rows:
            return pd.Series(dtype=float, name=category)
        index = pd.DatetimeIndex([pd.Timestamp(r[0]) for r in rows])
        return pd.Series([float(r[1]) for r in rows], index=index, name=category)
    except Exception as e:
        logger.error(f"Failed to fetch category score history for {category}: {e}")
        return pd.Series(dtype=float, name=category)
    finally:
        conn.close()

def get_previous_daily_score() -> float | None:
    """Fetch the most recent daily score strictly prior to today.

    Cached in memory for the current calendar day so that repeated page
    loads don't each open a Neon connection.
    """
    global _cached_previous_score, _cached_previous_date

    today = date.today()
    with _score_cache_lock:
        if _cached_previous_date == today:
            return _cached_previous_score

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
        score = float(row[0]) if row else None
        with _score_cache_lock:
            _cached_previous_score = score
            _cached_previous_date = today
        return score
    except Exception as e:
        logger.error(f"Failed to fetch previous daily score: {e}")
        return None
    finally:
        conn.close()


_snapshot_written_hour: datetime | None = None


def save_dashboard_snapshot(payload_json: str) -> bool:
    """Persist the latest good dashboard snapshot (one row, upserted).

    Render's disk is wiped on every deploy; this lets a new instance start
    from data that is at most an hour old instead of the committed file.
    Written at most once per hour to keep Neon compute low.
    """
    global _snapshot_written_hour

    now_hour = datetime.now().replace(minute=0, second=0, microsecond=0)
    with _score_cache_lock:
        if _snapshot_written_hour == now_hour:
            return True

    conn = get_connection()
    if not conn:
        return False
    db_type = get_db_type()
    try:
        with conn:
            cursor = conn.cursor()
            if db_type == "postgres":
                cursor.execute("""
                    INSERT INTO dashboard_snapshot (id, payload, updated_at)
                    VALUES (1, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO UPDATE
                    SET payload = EXCLUDED.payload, updated_at = EXCLUDED.updated_at
                """, (payload_json,))
            else:
                cursor.execute("""
                    INSERT INTO dashboard_snapshot (id, payload, updated_at)
                    VALUES (1, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(id) DO UPDATE
                    SET payload = excluded.payload, updated_at = excluded.updated_at
                """, (payload_json,))
        with _score_cache_lock:
            _snapshot_written_hour = now_hour
        return True
    except Exception as e:
        logger.error("Failed to save dashboard snapshot: %s", e)
        return False
    finally:
        conn.close()


def load_dashboard_snapshot() -> dict | None:
    """Return the last persisted dashboard snapshot (JSON-safe dict) or None."""
    import json

    conn = get_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT payload FROM dashboard_snapshot WHERE id = 1")
        row = cursor.fetchone()
        return json.loads(row[0]) if row else None
    except Exception as e:
        logger.warning("Failed to load dashboard snapshot: %s", e)
        return None
    finally:
        conn.close()


def get_sent_today(send_date: date) -> set[str]:
    """Addresses that already received the newsletter for ``send_date``."""
    conn = get_connection()
    if not conn:
        return set()
    ph = "%s" if get_db_type() == "postgres" else "?"
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT email FROM newsletter_sends WHERE send_date = {ph}", (send_date,))
        return {row[0] for row in cursor.fetchall()}
    except Exception as e:
        logger.warning("Failed to read newsletter sends: %s", e)
        return set()
    finally:
        conn.close()


def record_newsletter_send(send_date: date, email: str) -> None:
    """Mark one delivery so a retried run does not email the same person twice."""
    conn = get_connection()
    if not conn:
        return
    ph = "%s" if get_db_type() == "postgres" else "?"
    try:
        with conn:
            conn.cursor().execute(
                f"INSERT INTO newsletter_sends (send_date, email) VALUES ({ph}, {ph}) "
                "ON CONFLICT (send_date, email) DO NOTHING",
                (send_date, email),
            )
    except Exception as e:
        logger.warning("Failed to record newsletter send: %s", e)
    finally:
        conn.close()


def get_daily_category_scores(days: int) -> dict:
    """Return stored daily scores for every category over the last ``days`` days.

    Shape: ``{"dates": ["YYYY-MM-DD", ...ascending], "scores": {category:
    [float | None, ...aligned to dates]}}``. The date axis runs from
    ``today - days`` through today, so days with no stored row show up as
    ``None`` instead of being skipped or backfilled. Returns the empty shape
    when no database is configured or the query fails.
    """
    empty = {"dates": [], "scores": {}}
    conn = get_connection()
    if not conn:
        return empty

    db_type = get_db_type()
    try:
        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=days)
        cursor = conn.cursor()
        if db_type == "postgres":
            cursor.execute("""
                SELECT date, category, score FROM daily_category_scores
                WHERE date >= %s
                ORDER BY date ASC
            """, (start,))
        elif db_type == "sqlite":
            cursor.execute("""
                SELECT date, category, score FROM daily_category_scores
                WHERE date >= ?
                ORDER BY date ASC
            """, (start.isoformat(),))
        else:
            return empty

        dates = [(start + timedelta(days=i)).isoformat() for i in range((today - start).days + 1)]
        index = {d: i for i, d in enumerate(dates)}
        scores: dict[str, list[float | None]] = {}
        for row_date, category, score in cursor.fetchall():
            pos = index.get(str(row_date)[:10])
            if pos is None:
                continue
            scores.setdefault(category, [None] * len(dates))[pos] = float(score)
        return {"dates": dates, "scores": scores}
    except Exception as e:
        logger.error(f"Failed to fetch daily category scores: {e}")
        return empty
    finally:
        conn.close()
