"""Pooled connections are pinged only after sitting idle, and a dead one is
replaced instead of failing the request (Postgres engines; tested on SQLite)."""
from sqlalchemy import create_engine, event, text

from flowboard.db import session as dbs


def _engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'p.db'}", pool_size=1, max_overflow=0)
    dbs._ping_when_idle(eng)
    pings = []
    event.listen(eng, "before_cursor_execute", lambda *a: None)  # keep engine events alive
    return eng, pings


def test_no_ping_while_hot_and_dead_idle_connection_is_replaced(tmp_path, monkeypatch):
    eng, _ = _engine(tmp_path)
    with eng.connect() as c:
        c.execute(text("select 1"))
    raw_before = eng.pool._pool.queue[0].dbapi_connection  # the pooled sqlite connection

    # Used a moment ago: handed out as is (no ping, same connection).
    with eng.connect() as c:
        assert c.connection.dbapi_connection is raw_before

    # Idle "too long" and dead underneath: the checkout ping fails, the pool
    # discards it and the caller still gets a working connection.
    monkeypatch.setattr(dbs, "IDLE_PING_S", 0.0)
    raw_before.close()
    with eng.connect() as c:
        assert c.execute(text("select 1")).scalar() == 1
        assert c.connection.dbapi_connection is not raw_before
