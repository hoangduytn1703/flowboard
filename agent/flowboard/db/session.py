"""The data engine: one per logged-in account, swapped at login.

``get_session()`` always opens on the *current* engine. Without login
(``FLOWBOARD_AUTH=off``: tests, the old single-user mode) the current engine
is the default local SQLite file; with login, ``flowboard.accounts`` builds
an engine for the account (its own SQLite file today, a Postgres schema
later) and installs it with :func:`set_engine`.
"""
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Union

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from flowboard.config import DB_PATH


#: A pooled Postgres connection idle longer than this is pinged before use.
IDLE_PING_S = 60.0


def _ping_when_idle(eng: Engine) -> None:
    """Pessimistic disconnect handling, but only for connections that sat
    idle: raising DisconnectionError on checkout makes the pool throw the
    dead connection away and hand out a fresh one (up to 3 tries)."""
    import time

    from sqlalchemy import exc

    @event.listens_for(eng, "checkin")
    def _mark(dbapi_conn, rec) -> None:  # noqa: ARG001
        rec.info["fb_last_used"] = time.monotonic()

    @event.listens_for(eng, "checkout")
    def _check(dbapi_conn, rec, proxy) -> None:  # noqa: ARG001
        last = rec.info.get("fb_last_used")
        if last is None or time.monotonic() - last < IDLE_PING_S:
            return  # brand new (just connected) or used a moment ago
        try:
            cur = dbapi_conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            dbapi_conn.rollback()  # don't hand out a connection mid-transaction
        except Exception as err:  # noqa: BLE001 - any failure means "dead"
            raise exc.DisconnectionError() from err


def make_engine(url_or_path: Union[str, Path], schema: Optional[str] = None) -> Engine:
    """An engine for a SQLite file path or any SQLAlchemy URL. ``schema``
    (Postgres) pins every connection's ``search_path`` to that schema — how
    one Neon database holds one account per schema."""
    url = str(url_or_path)
    if "://" not in url:
        url = f"sqlite:///{url}"
    if url.startswith("postgres"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1).replace("postgresql://", "postgresql+psycopg://", 1)
        if schema:
            # Neon's ``-pooler`` host is PgBouncer in transaction mode: a SET
            # search_path is lost between transactions and startup ``options``
            # are rejected, so a per-schema engine talks to the compute
            # directly (same host without ``-pooler``; our own pool is small).
            url = url.replace("-pooler.", ".", 1)
        # No pool_pre_ping: on Neon every ping is a full round trip (~44 ms
        # from Vietnam), paid on each request. A connection is checked only
        # after sitting idle (Neon drops them when the compute suspends).
        eng = create_engine(url, echo=False, pool_size=5, max_overflow=5)
        _ping_when_idle(eng)
        eng._fb_schema = schema  # type: ignore[attr-defined]
        if schema:
            # Raw ``text()`` SQL relies on the search_path (direct host, so it
            # sticks to the pooled connection).
            @event.listens_for(eng, "connect")
            def _set_search_path(dbapi_conn, _connection_record) -> None:
                cur = dbapi_conn.cursor()
                cur.execute(f'SET search_path TO "{schema}", public')
                cur.close()
                dbapi_conn.commit()

            # ORM / Core statements name the schema explicitly on top of that.
            eng = eng.execution_options(schema_translate_map={None: schema})
            eng._fb_schema = schema  # type: ignore[attr-defined]
        return eng
    if url.startswith("sqlite"):
        eng = create_engine(url, echo=False, connect_args={"check_same_thread": False})

        @event.listens_for(eng, "connect")
        def _enable_sqlite_fk(dbapi_conn, _connection_record) -> None:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return eng
    return create_engine(url, echo=False, pool_pre_ping=True)


#: The default (no-login) engine. Kept under this name because tests import it.
engine: Engine = make_engine(DB_PATH)


def _auth_on() -> bool:
    import os

    return os.getenv("FLOWBOARD_AUTH", "on").lower() not in ("off", "0", "false")


# With login on, nothing may touch a database before an account is active:
# the extension connects at start-up and its first message used to open
# the old single-user file through the default engine, which then could not
# be moved into the account folder (Windows keeps it locked).
_state: dict[str, Optional[Engine]] = {"engine": None if _auth_on() else engine}


class NoActiveAccount(RuntimeError):
    """A database call before anyone logged in."""


def has_engine() -> bool:
    return _state["engine"] is not None


def current_engine() -> Engine:
    eng = _state["engine"]
    if eng is None:
        raise NoActiveAccount("Chưa có tài khoản nào đăng nhập — chưa mở được dữ liệu.")
    return eng


def set_engine(eng: Engine) -> None:
    """Make ``eng`` the engine every ``get_session()`` opens on."""
    _state["engine"] = eng


def init_db(target: Optional[Engine] = None) -> None:
    from sqlalchemy import inspect

    from flowboard.db import models

    eng = target or current_engine()
    with eng.connect() as conn:
        insp = inspect(conn)
        if eng.dialect.name == "sqlite":
            # Targeted migration: if an older `asset` table exists without `url`,
            # drop it. Acceptable because the app has not stored real asset rows
            # prior to Run 6; other tables (board, node, edge, chatmessage, request)
            # are left alone.
            if insp.has_table("asset"):
                cols = {c["name"] for c in insp.get_columns("asset")}
                if "url" not in cols:
                    models.Asset.__table__.drop(conn, checkfirst=True)
                    conn.commit()

            # Edge.source_variant_idx — added when per-edge variant pinning
            # shipped. SQLite ALTER TABLE ADD COLUMN is non-destructive (and
            # idempotent via the column-existence check), so existing DBs
            # pick up the new column on first boot without losing data.
            # `create_all` below won't help because it skips ALTERs on
            # existing tables.
            if insp.has_table("edge"):
                edge_cols = {c["name"] for c in insp.get_columns("edge")}
                if "source_variant_idx" not in edge_cols:
                    conn.exec_driver_sql(
                        "ALTER TABLE edge ADD COLUMN source_variant_idx INTEGER"
                    )
                    conn.commit()

            # Board.data — the Quicktool wizard's per-board state; same
            # non-destructive ADD COLUMN as above.
            if insp.has_table("board"):
                board_cols = {c["name"] for c in insp.get_columns("board")}
                if "data" not in board_cols:
                    conn.exec_driver_sql("ALTER TABLE board ADD COLUMN data JSON DEFAULT '{}'")
                    conn.commit()

    if eng.dialect.name == "postgresql":
        schema = _schema_of(eng)
        if schema:
            with eng.begin() as conn:
                conn.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    SQLModel.metadata.create_all(eng)
    # Absolute file paths written before 22/10 → relative to the data folder.
    from flowboard.db.paths import normalize_asset_paths
    normalize_asset_paths(eng)


def _schema_of(eng: Engine) -> Optional[str]:
    return getattr(eng, "_fb_schema", None)


@contextmanager
def get_session():
    with Session(current_engine()) as session:
        yield session
