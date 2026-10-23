from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from .session import NoActiveAccount, current_engine, engine, get_session, has_engine, make_engine, set_engine
from .session import init_db as _init_db_tables

__all__ = ["engine", "get_session", "init_db", "current_engine", "set_engine", "make_engine", "has_engine", "NoActiveAccount",
           "ensure_reference_meta_column", "ensure_product_gender_column", "ensure_reference_media_id_not_unique"]


def ensure_reference_meta_column(db_engine: Engine | None = None) -> bool:
    """Add ``reference.meta`` to a DB created before the column existed.

    Same non-destructive ``ALTER TABLE … ADD COLUMN`` pattern as the
    migrations in ``session.init_db``; ``create_all`` skips existing
    tables, so an old ``reference`` table would otherwise make every
    reference query fail with "no such column: meta".

    Returns True when the column was added, False when nothing had to be
    done (fresh DB, no table yet, or already migrated).
    """
    db_engine = db_engine or current_engine()
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


def ensure_product_gender_column(db_engine: Engine | None = None) -> bool:
    """Add ``product.gender`` to a DB created before the column existed (same
    non-destructive pattern as :func:`ensure_reference_meta_column`)."""
    db_engine = db_engine or current_engine()
    with db_engine.connect() as conn:
        insp = inspect(conn)
        if not insp.has_table("product"):
            return False
        if "gender" in {c["name"] for c in insp.get_columns("product")}:
            return False
        conn.exec_driver_sql("ALTER TABLE product ADD COLUMN gender VARCHAR DEFAULT ''")
        # Products saved before the column existed get a guess from their
        # name / description, once — afterwards "" means the user said "unknown".
        from flowboard.services.product_gender import guess

        for pid, name, desc in conn.exec_driver_sql("SELECT id, name, description FROM product").fetchall():
            g = guess(name, desc)
            if g:
                conn.exec_driver_sql("UPDATE product SET gender = ? WHERE id = ?", (g, pid))
        conn.commit()
        return True


def ensure_reference_media_id_not_unique(db_engine: Engine | None = None) -> bool:
    """Turn the unique index on ``reference.media_id`` of an older DB into a
    plain one, so a cloned model can share its original's photo. Works on
    SQLite and on the account's Postgres schema (the connection's search
    path is that schema). Returns True when an index was replaced."""
    db_engine = db_engine or current_engine()
    with db_engine.connect() as conn:
        insp = inspect(conn)
        if not insp.has_table("reference"):
            return False
        stale = [ix["name"] for ix in insp.get_indexes("reference")
                 if ix.get("unique") and ix.get("column_names") == ["media_id"]]
        if not stale:
            return False
        for name in stale:
            conn.exec_driver_sql(f'DROP INDEX IF EXISTS "{name}"')
        conn.exec_driver_sql('CREATE INDEX IF NOT EXISTS "ix_reference_media_id" ON reference (media_id)')
        conn.commit()
        return True


def init_db(target: Engine | None = None) -> None:
    """Create tables and apply the lightweight column migrations on
    ``target`` (default: the current account's engine)."""
    target = target or current_engine()
    _init_db_tables(target)
    ensure_reference_meta_column(target)
    ensure_product_gender_column(target)
    ensure_reference_media_id_not_unique(target)
