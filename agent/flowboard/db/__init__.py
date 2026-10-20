from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from .session import engine, get_session
from .session import init_db as _init_db_tables

__all__ = ["engine", "get_session", "init_db", "ensure_reference_meta_column"]


def ensure_reference_meta_column(db_engine: Engine = engine) -> bool:
    """Add ``reference.meta`` to a DB created before the column existed.

    Same non-destructive ``ALTER TABLE … ADD COLUMN`` pattern as the
    migrations in ``session.init_db``; ``create_all`` skips existing
    tables, so an old ``reference`` table would otherwise make every
    reference query fail with "no such column: meta".

    Returns True when the column was added, False when nothing had to be
    done (fresh DB, no table yet, or already migrated).
    """
    with db_engine.connect() as conn:
        insp = inspect(conn)
        if not insp.has_table("reference"):
            return False
        cols = {c["name"] for c in insp.get_columns("reference")}
        if "meta" in cols:
            return False
        conn.exec_driver_sql("ALTER TABLE reference ADD COLUMN meta JSON DEFAULT '{}'")
        conn.commit()
        return True


def init_db() -> None:
    """Create tables and apply the lightweight column migrations."""
    _init_db_tables()
    ensure_reference_meta_column(engine)
