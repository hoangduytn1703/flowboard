"""An account's data in a Postgres schema. Runs only when
``FLOWBOARD_TEST_PG_URL`` points at a database (Neon); each run uses its own
throw-away schema and drops it afterwards."""
import os
import uuid

import pytest
from sqlalchemy import text

from flowboard.db import init_db, make_engine

PG_URL = os.getenv("FLOWBOARD_TEST_PG_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="FLOWBOARD_TEST_PG_URL not set")


@pytest.fixture
def pg_schema():
    schema = "test_" + uuid.uuid4().hex[:8]
    eng = make_engine(PG_URL, schema=schema)
    yield schema, eng
    eng.dispose()
    admin = make_engine(PG_URL)
    with admin.begin() as c:
        c.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    admin.dispose()


def test_init_db_creates_every_table_in_the_schema_and_rows_round_trip(pg_schema):
    from sqlmodel import Session, select

    from flowboard.db.models import Asset, Board, Node, SavedPrompt

    schema, eng = pg_schema
    init_db(eng)
    with eng.connect() as c:
        tables = {r[0] for r in c.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = :s"), {"s": schema})}
    assert {"board", "node", "edge", "asset", "product", "reference", "savedprompt", "request"} <= tables
    with Session(eng) as s:
        b = Board(name="clip Neon", data={"quicktool": {"step": 2}})
        s.add(b); s.commit(); s.refresh(b)
        s.add(Node(board_id=b.id, short_id="n1", type="note", x=0, y=0, data={"prompt": "xin chào"}))
        s.add(Asset(kind="video", uuid_media_id="v" * 32, local_path="media/x.mp4"))
        s.add(SavedPrompt(kind="image", title="Thân · Đáng tiền", text="t", tags=["mẫu có sẵn"]))
        s.commit()
    with Session(eng) as s:
        board = s.exec(select(Board)).one()
        assert board.data["quicktool"]["step"] == 2
        node = s.exec(select(Node)).one()
        assert node.data["prompt"] == "xin chào" and node.board_id == board.id
        asset = s.exec(select(Asset)).one()
        assert asset.local_path.endswith("x.mp4") and asset.local_path != "media/x.mp4"  # resolved to this machine
        assert s.exec(select(SavedPrompt)).one().tags == ["mẫu có sẵn"]


def test_move_to_cloud_copies_sqlite_rows(pg_schema, tmp_path, monkeypatch, request):
    from flowboard import accounts
    from flowboard.db import session as db_session

    schema, _eng = pg_schema
    monkeypatch.setenv("FLOWBOARD_CENTRAL_DB_URL", PG_URL)
    monkeypatch.setattr(accounts, "_ROOT_STORAGE", tmp_path)
    monkeypatch.setattr(accounts, "schema_for", lambda username: schema)
    accounts.reset_central()
    username = "mover_" + schema[-8:]
    # The central store is the shared Neon database: leave no test user behind,
    # even when an assertion below fails (a leftover row blocks seeding).
    request.addfinalizer(lambda: _drop_user(accounts, username))
    user = accounts.create_user(username, "secret123")
    src = db_session.make_engine(tmp_path / "accounts" / username / "flowboard.db")
    (tmp_path / "accounts" / username).mkdir(parents=True)
    init_db(src)
    with src.begin() as c:
        c.exec_driver_sql("INSERT INTO board (name, data, created_at) VALUES ('clip cũ', '{\"a\": 1}', '2026-10-01 00:00:00')")
        c.exec_driver_sql("INSERT INTO product (name, description, category, price, selling_points, link, notes, media_ids, created_at, updated_at, gender) "
                          "VALUES ('áo', '', 'fashion', '', '[]', '', '', '[]', '2026-10-01 00:00:00', '2026-10-01 00:00:00', 'unisex')")
    src.dispose()
    out = accounts.move_to_cloud(username)
    assert out["moved"] and out["tables"]["board"] == 1 and out["tables"]["product"] == 1
    assert accounts.get_user(username)["backend"]["type"] == "postgres"
    eng = accounts.data_engine(accounts.get_user(username))
    with eng.connect() as c:
        assert c.execute(text("SELECT name FROM board")).scalar() == "clip cũ"
        assert c.execute(text("SELECT data->>'a' FROM board")).scalar() == "1"
        # New rows keep counting after the copied ids.
        c.execute(text("INSERT INTO board (name, data, created_at) VALUES ('clip mới', '{}', now())")); c.commit()
        assert c.execute(text("SELECT max(id) FROM board")).scalar() == 2
    eng.dispose()


def _drop_user(accounts, username: str) -> None:
    with accounts.central_engine().begin() as c:
        c.execute(text("DELETE FROM account_user WHERE username = :u"), {"u": username})
    accounts.reset_central()
