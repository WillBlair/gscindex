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

# Render provides DATABASE_URL when a PostgreSQL database is attached.
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    try:
        import psycopg2
        DB_TYPE = "postgres"
    except ImportError:
        logger.error("psycopg2-binary is required for PostgreSQL connections.")
        DB_TYPE = "none"
else:
    import sqlite3
    DB_TYPE = "sqlite"
    SQLITE_PATH = os.path.join(os.path.dirname(__file__), "subscribers.db")

def get_connection():
    if DB_TYPE == "postgres":
        return psycopg2.connect(DATABASE_URL)
    elif DB_TYPE == "sqlite":
        # check_same_thread=False is needed because Dash runs in threads
        return sqlite3.connect(SQLITE_PATH, check_same_thread=False)
    return None

def init_db():
    conn = get_connection()
    if not conn:
        logger.warning("No database configured. Cannot initialize.")
        return
        
    try:
        with conn:
            cursor = conn.cursor()
            if DB_TYPE == "postgres":
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS subscribers (
                        id SERIAL PRIMARY KEY,
                        email VARCHAR(255) UNIQUE NOT NULL,
                        subscribed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        is_active BOOLEAN DEFAULT TRUE
                    )
                """)
            elif DB_TYPE == "sqlite":
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS subscribers (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        email TEXT UNIQUE NOT NULL,
                        subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        is_active BOOLEAN DEFAULT 1
                    )
                """)
        logger.info(f"Database initialized ({DB_TYPE}).")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
    finally:
        conn.close()

def add_subscriber(email: str) -> dict:
    conn = get_connection()
    if not conn:
        return {"success": False, "message": "Database not configured."}
        
    try:
        with conn:
            cursor = conn.cursor()
            if DB_TYPE == "postgres":
                # Use ON CONFLICT DO UPDATE to reactivate if previously unsubscribed
                cursor.execute("""
                    INSERT INTO subscribers (email, is_active)
                    VALUES (%s, TRUE)
                    ON CONFLICT (email) DO UPDATE 
                    SET is_active = TRUE
                """, (email,))
            elif DB_TYPE == "sqlite":
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
        return []
        
    try:
        cursor = conn.cursor()
        if DB_TYPE == "postgres":
            cursor.execute("SELECT email FROM subscribers WHERE is_active = TRUE")
        elif DB_TYPE == "sqlite":
            cursor.execute("SELECT email FROM subscribers WHERE is_active = 1")
            
        rows = cursor.fetchall()
        # Ensure we return a list of strings
        return [row[0] for row in rows]
    except Exception as e:
        logger.error(f"Failed to fetch subscribers: {e}")
        return []
    finally:
        conn.close()

def unsubscribe_user(email: str) -> bool:
    conn = get_connection()
    if not conn:
        return False
        
    try:
        with conn:
            cursor = conn.cursor()
            if DB_TYPE == "postgres":
                cursor.execute("UPDATE subscribers SET is_active = FALSE WHERE email = %s", (email,))
            elif DB_TYPE == "sqlite":
                cursor.execute("UPDATE subscribers SET is_active = 0 WHERE email = ?", (email,))
        return True
    except Exception as e:
        logger.error(f"Failed to unsubscribe: {e}")
        return False
    finally:
        conn.close()
