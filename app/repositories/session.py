from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator
from urllib.parse import urlparse, urlunparse

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import DATABASE_URL, DATABASE_URL_FALLBACK

log = logging.getLogger(__name__)

_active_url: str | None = None
_engine = None
_session_maker = None
_pool: ConnectionPool | None = None


def get_engine():
    global _engine

    if _engine is None:
        url = resolve_database_url()

        if url.startswith("postgresql://"):
            url = url.replace(
                "postgresql://",
                "postgresql+psycopg://",
                1,
            )

        _engine = create_engine(url)

    return _engine


def get_session_maker():
    global _session_maker
    if _session_maker is None:
        _session_maker = sessionmaker(bind=get_engine())
    return _session_maker


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        url = resolve_database_url()
        _pool = ConnectionPool(
            url,
            kwargs={"row_factory": dict_row},
            min_size=1,
            max_size=20,
            timeout=30.0,
        )
    return _pool


@contextmanager
def get_session() -> Iterator[Session]:
    session = get_session_maker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _auth_failed(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "password authentication failed",
            "authentication failed",
            "28p01",
        )
    )


def _try_connect(url: str, autocommit: bool = False) -> psycopg.Connection:
    # psycopg.connect() doesn't understand SQLAlchemy's +psycopg prefix
    # Convert postgresql+psycopg:// to postgresql://
    if url.startswith("postgresql+psycopg://"):
        url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    return psycopg.connect(
        url,
        row_factory=dict_row,
        connect_timeout=5,
        autocommit=autocommit,
    )


def resolve_database_url() -> str:
    global _active_url
    if _active_url:
        return _active_url
    candidates = [DATABASE_URL]
    if DATABASE_URL_FALLBACK and DATABASE_URL_FALLBACK not in candidates:
        candidates.append(DATABASE_URL_FALLBACK)
    last_error: Exception | None = None
    for url in candidates:
        try:
            with _try_connect(url) as conn:
                conn.execute("SELECT 1")
            # Convert postgresql+psycopg:// to postgresql:// for psycopg compatibility
            normalized_url = url
            if url.startswith("postgresql+psycopg://"):
                normalized_url = url.replace("postgresql+psycopg://", "postgresql://", 1)
            _active_url = normalized_url
            if url != DATABASE_URL:
                log.warning("Primary DATABASE_URL auth failed; using fallback user")
            return normalized_url
        except Exception as exc:
            last_error = exc
            if _auth_failed(exc):
                log.warning("Postgres auth failed for %s", urlparse(url).username)
                continue
            if "does not exist" in str(exc).lower():
                # Convert postgresql+psycopg:// to postgresql:// for psycopg compatibility
                normalized_url = url
                if url.startswith("postgresql+psycopg://"):
                    normalized_url = url.replace("postgresql+psycopg://", "postgresql://", 1)
                _active_url = normalized_url
                return normalized_url
            raise
    assert last_error is not None
    raise last_error


def _admin_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path="/postgres"))


def ensure_database() -> None:
    url = resolve_database_url()
    try:
        with _try_connect(url) as conn:
            conn.execute("SELECT 1")
        return
    except psycopg.OperationalError as exc:
        message = str(exc).lower()
        if "does not exist" not in message:
            raise
        log.warning("Database missing; attempting CREATE DATABASE rag")

    admin = _admin_url(url)
    db_name = (urlparse(url).path or "/rag").lstrip("/") or "rag"
    with _try_connect(admin, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)
        ).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{db_name}"')


def init_schema() -> None:
    """
    Initialize database schema.
    
    Schema is managed by Alembic migrations only.
    This function ensures the database exists but does NOT create tables.
    Run 'alembic upgrade head' to apply migrations before starting the application.
    """
    ensure_database()
    log.info("Schema managed by Alembic - run 'alembic upgrade head' to apply migrations")


def check_alembic_migration() -> bool:
    """
    Check if the database is at the expected Alembic migration head.
    
    Returns True if migrations are up to date, False otherwise.
    Compares current database revision with Alembic's head revision.
    """
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        
        # Get current database version
        with connect() as conn:
            row = conn.execute(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'alembic_version'
                )
                """
            ).fetchone()
            
            if not row or not row["exists"]:
                log.warning("Alembic version table not found - run 'alembic upgrade head'")
                return False
            
            version_row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
            if not version_row:
                log.warning("No Alembic version found - run 'alembic upgrade head'")
                return False
            
            current_version = version_row["version_num"]
        
        # Get Alembic head revision
        config = Config("alembic.ini")
        script = ScriptDirectory.from_config(config)
        head_revision = script.get_current_head()
        
        if not head_revision:
            log.warning("Could not determine Alembic head revision")
            return False
        
        head_revision_id = head_revision.revision
        
        log.info("Current Alembic version: %s, Head revision: %s", current_version, head_revision_id)
        
        # Compare versions
        if current_version != head_revision_id:
            log.error(
                "Database is behind Alembic head. Current: %s, Head: %s. Run 'alembic upgrade head'",
                current_version,
                head_revision_id,
            )
            return False
        
        log.info("Database is at Alembic head revision: %s", current_version)
        return True
            
    except Exception as exc:
        log.warning("Failed to check Alembic migration status: %s", exc)
        return False


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    pool = get_pool()
    with pool.connection() as conn:
        yield conn


def ping() -> bool:
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception as exc:
        log.warning("Postgres ping failed: %s", exc)
        return False
