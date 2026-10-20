"""The Quicktool model library: ``Reference`` rows of kind ``character``
carrying ``meta`` (gender / country / vibe / extras / prompt / product),
plus the ``reference.meta`` column migration for DBs made before it."""
import sqlite3

from sqlalchemy import create_engine, inspect

from flowboard.db import ensure_reference_meta_column

META = {
    "gender": "female",
    "country": "vn",
    "vibe": "clean",
    "extras": "long black hair, mid 20s",
    "prompt": "a Vietnamese female model, Clean Girl makeup styling",
    "product": "Son dưỡng môi",
}


def _save(client, media_id="model-1", **over):
    body = {
        "media_id": media_id,
        "kind": "character",
        "label": "Nữ · Việt Nam · Clean Girl",
        "ai_brief": "young Vietnamese woman, dewy skin",
        "aspect_ratio": "9:16",
        "source_board_id": None,
        "source_node_short_id": "ab12",
        "meta": META,
    }
    body.update(over)
    r = client.post("/api/references", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_create_character_with_meta(client):
    row = _save(client)
    assert row["kind"] == "character"
    assert row["label"] == "Nữ · Việt Nam · Clean Girl"
    assert row["meta"] == META
    assert row["source_node_short_id"] == "ab12"


def test_create_without_meta_returns_empty_dict(client):
    r = client.post("/api/references", json={"media_id": "plain", "kind": "image"})
    assert r.status_code == 200
    assert r.json()["meta"] == {}


def test_save_same_media_twice_is_idempotent_and_keeps_meta(client):
    a = _save(client)
    b = _save(client, meta={"gender": "male"}, label="other")
    assert a["id"] == b["id"]
    assert b["meta"] == META
    assert b["label"] == a["label"]


def test_list_filtered_by_kind(client):
    _save(client, media_id="c1")
    _save(client, media_id="c2", label="Nam · Hàn Quốc · K-Pop", meta={**META, "gender": "male"})
    client.post("/api/references", json={"media_id": "i1", "kind": "image"})
    client.post("/api/references", json={"media_id": "v1", "kind": "visual_asset"})

    rows = client.get("/api/references", params={"kind": "character"}).json()
    assert {r["media_id"] for r in rows} == {"c1", "c2"}
    assert all(r["kind"] == "character" for r in rows)
    # Each row still carries its own meta.
    by_media = {r["media_id"]: r for r in rows}
    assert by_media["c2"]["meta"]["gender"] == "male"

    # No filter → everything, as before.
    assert len(client.get("/api/references").json()) == 4
    # Unknown kind → 400, not an empty list that hides a typo.
    assert client.get("/api/references", params={"kind": "model"}).status_code == 400


def test_patch_meta_and_label(client):
    row = _save(client)
    r = client.patch(
        f"/api/references/{row['id']}",
        json={"label": "Chị Lan", "meta": {**META, "vibe": "douyin"}},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["label"] == "Chị Lan"
    assert out["meta"]["vibe"] == "douyin"
    assert out["meta"]["product"] == "Son dưỡng môi"

    # PATCH without meta leaves it alone.
    r = client.patch(f"/api/references/{row['id']}", json={"pinned": True})
    assert r.json()["meta"]["vibe"] == "douyin"
    assert r.json()["pinned"] is True


def test_delete_character(client):
    row = _save(client)
    assert client.delete(f"/api/references/{row['id']}").status_code == 204
    assert client.get("/api/references", params={"kind": "character"}).json() == []
    assert client.delete(f"/api/references/{row['id']}").status_code == 404


def test_migration_adds_meta_column_to_old_db(tmp_path):
    """A DB whose ``reference`` table predates ``meta`` gets the column on
    boot without losing rows; running the helper again is a no-op."""
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE board (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL);
        CREATE TABLE reference (
            id INTEGER PRIMARY KEY,
            media_id VARCHAR NOT NULL UNIQUE,
            url VARCHAR,
            label VARCHAR NOT NULL,
            kind VARCHAR NOT NULL,
            ai_brief VARCHAR,
            aspect_ratio VARCHAR,
            tags JSON,
            pinned BOOLEAN NOT NULL,
            position INTEGER NOT NULL,
            source_board_id INTEGER REFERENCES board(id),
            source_node_short_id VARCHAR,
            created_at DATETIME NOT NULL
        );
        INSERT INTO reference (media_id, label, kind, tags, pinned, position, created_at)
        VALUES ('old-1', 'Old row', 'character', '[]', 0, 0, '2026-01-01 00:00:00');
        """
    )
    con.commit()
    con.close()

    engine = create_engine(f"sqlite:///{db}")
    assert ensure_reference_meta_column(engine) is True
    cols = {c["name"] for c in inspect(engine).get_columns("reference")}
    assert "meta" in cols
    # Idempotent.
    assert ensure_reference_meta_column(engine) is False

    with engine.connect() as conn:
        rows = conn.exec_driver_sql("SELECT media_id, meta FROM reference").fetchall()
    assert rows == [("old-1", "{}")]
    engine.dispose()


def test_migration_noop_without_reference_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    assert ensure_reference_meta_column(engine) is False
    engine.dispose()
