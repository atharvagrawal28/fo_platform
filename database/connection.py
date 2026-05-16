"""
database/connection.py
----------------------
Single database connection utility used by both:
  - Pipeline (psycopg2 direct connection)
  - Streamlit dashboard (cached via st.cache_resource)

Never import Streamlit here — this file is used by the pipeline too.
"""

import logging
import sys
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)


def get_connection(database_url: str):
    """
    Create and return a raw psycopg2 connection.
    Used by the pipeline (run.py, store.py, etc.)

    Neon PostgreSQL requires sslmode=require — include it in your
    DATABASE_URL or it's added automatically here as a fallback.
    """
    if not database_url:
        logger.error("DATABASE_URL is empty. Set it in .env or as an environment variable.")
        sys.exit(1)

    try:
        conn = psycopg2.connect(database_url)
        conn.autocommit = False
        logger.info("Database connection established.")
        return conn
    except psycopg2.OperationalError as e:
        logger.error("Could not connect to database: %s", e)
        raise


@contextmanager
def pipeline_cursor(database_url: str):
    """
    Context manager for pipeline database operations.
    Commits on success, rolls back on any exception.

    Usage:
        with pipeline_cursor(DATABASE_URL) as cur:
            cur.execute("INSERT INTO ...")
    """
    conn = get_connection(database_url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_streamlit_connection(database_url: str):
    """
    Called inside st.cache_resource in the Streamlit app.
    Returns a persistent connection reused across all Streamlit reruns.

    Streamlit reads only. Autocommit avoids long-lived idle transactions on
    cached dashboard connections, especially when Neon suspends and resumes.
    """
    conn = get_connection(database_url)
    conn.autocommit = True
    return conn


def ensure_connected(conn, database_url: str):
    """
    Return a healthy connection, rebuilding stale cached connections.

    Neon free tier can suspend compute while Streamlit keeps a cached psycopg2
    connection object. The first query after a long idle period may then fail
    with an OperationalError/InterfaceError. This health check keeps that
    failure from leaking into dashboard queries.
    """
    if not database_url:
        return None

    if conn is None or getattr(conn, "closed", 1) != 0:
        logger.info("Opening Streamlit database connection.")
        return get_streamlit_connection(database_url)

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return conn
    except psycopg2.Error as e:
        logger.warning("Cached database connection is stale; reconnecting: %s", e)
        _close_quietly(conn)
        return get_streamlit_connection(database_url)


def run_query_df(conn, sql: str, params=None):
    """
    Execute a SELECT query and return results as a list of dicts.
    Returns empty list if table has no data — never raises on empty result.
    """
    import pandas as pd

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            rows = cur.fetchall()
            if not rows:
                return pd.DataFrame()
            return pd.DataFrame([dict(r) for r in rows])
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        logger.warning("Connection-level query failure. Caller should reconnect.")
        raise
    except psycopg2.Error as e:
        logger.error("Query failed: %s | SQL: %s", e, sql[:200])
        try:
            conn.rollback()
        except Exception:
            pass
        return pd.DataFrame()


def _close_quietly(conn) -> None:
    try:
        conn.close()
    except Exception:
        pass
