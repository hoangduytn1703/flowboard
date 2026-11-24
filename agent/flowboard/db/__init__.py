from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from .session import NoActiveAccount, current_engine, engine, get_session, has_engine, make_engine, set_engine
from .session import init_db as _init_db_tables

__all__ = ["engine", "get_session", "init_db", "current_engine", "set_engine", "make_engine", "has_engine", "NoActiveAccount",
           "ensure_reference_meta_column", "ensure_product_gender_column", "ensure_reference_media_id_not_unique",
           "ensure_post_channel_column", "ensure_post_series_columns", "ensure_channel_link_columns",
           "ensure_channel_categories_column", "ensure_product_aff_columns", "ensure_channel_facebook_columns", "ensure_post_video_column",
           "ensure_schedule_format_column", "ensure_fbpost_stats_column", "ensure_schedule_story_column",
           "ensure_decorpreset_favorite_column"]


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


def ensure_post_channel_column(db_engine: Engine | None = None) -> bool:
    """Add ``post.channel_id`` to a DB whose post table predates channels."""
    db_engine = db_engine or current_engine()
    with db_engine.connect() as conn:
        insp = inspect(conn)
        if not insp.has_table("post"):
            return False
        if "channel_id" in {c["name"] for c in insp.get_columns("post")}:
            return False
        conn.exec_driver_sql("ALTER TABLE post ADD COLUMN channel_id INTEGER")
        conn.commit()
        return True


def ensure_post_series_columns(db_engine: Engine | None = None) -> bool:
    """Add ``post.series`` / ``post.episode`` to a DB whose post table predates series."""
    db_engine = db_engine or current_engine()
    with db_engine.connect() as conn:
        insp = inspect(conn)
        if not insp.has_table("post"):
            return False
        cols = {c["name"] for c in insp.get_columns("post")}
        added = False
        if "series" not in cols:
            conn.exec_driver_sql("ALTER TABLE post ADD COLUMN series VARCHAR DEFAULT ''")
            added = True
        if "episode" not in cols:
            conn.exec_driver_sql("ALTER TABLE post ADD COLUMN episode INTEGER DEFAULT 0")
            added = True
        conn.commit()
        return added


def ensure_channel_link_columns(db_engine: Engine | None = None) -> bool:
    """Add ``channel.link`` / ``channel.page_review`` to a DB from before them."""
    db_engine = db_engine or current_engine()
    with db_engine.connect() as conn:
        insp = inspect(conn)
        if not insp.has_table("channel"):
            return False
        cols = {c["name"] for c in insp.get_columns("channel")}
        added = False
        if "link" not in cols:
            conn.exec_driver_sql("ALTER TABLE channel ADD COLUMN link VARCHAR DEFAULT ''")
            added = True
        if "page_review" not in cols:
            json_type = "JSONB" if conn.dialect.name == "postgresql" else "JSON"
            conn.exec_driver_sql(f"ALTER TABLE channel ADD COLUMN page_review {json_type}")
            added = True
        conn.commit()
        return added


def ensure_channel_categories_column(db_engine: Engine | None = None) -> bool:
    """Add ``channel.categories`` (JSON list) and seed it from the single ``category``."""
    db_engine = db_engine or current_engine()
    with db_engine.connect() as conn:
        insp = inspect(conn)
        if not insp.has_table("channel"):
            return False
        if "categories" in {c["name"] for c in insp.get_columns("channel")}:
            return False
        json_type = "JSONB" if conn.dialect.name == "postgresql" else "JSON"
        conn.exec_driver_sql(f"ALTER TABLE channel ADD COLUMN categories {json_type}")
        for cid, cat in conn.exec_driver_sql("SELECT id, category FROM channel").fetchall():
            value = f'["{cat}"]' if cat else "[]"
            conn.exec_driver_sql("UPDATE channel SET categories = ? WHERE id = ?" if conn.dialect.name != "postgresql"
                                 else "UPDATE channel SET categories = %s::jsonb WHERE id = %s", (value, cid))
        conn.commit()
        return True


def ensure_post_video_column(db_engine: Engine | None = None) -> bool:
    """Add ``post.video`` (a Flow video's media id posted instead of the images)."""
    db_engine = db_engine or current_engine()
    with db_engine.connect() as conn:
        insp = inspect(conn)
        if not insp.has_table("post"):
            return False
        if "video" in {c["name"] for c in insp.get_columns("post")}:
            return False
        conn.exec_driver_sql("ALTER TABLE post ADD COLUMN video VARCHAR DEFAULT ''")
        conn.commit()
        return True


def ensure_schedule_format_column(db_engine: Engine | None = None) -> bool:
    """Add ``schedule.fb_format`` ("post" | "reel": how a video goes out on Facebook)."""
    db_engine = db_engine or current_engine()
    with db_engine.connect() as conn:
        insp = inspect(conn)
        if not insp.has_table("schedule"):
            return False
        if "fb_format" in {c["name"] for c in insp.get_columns("schedule")}:
            return False
        conn.exec_driver_sql("ALTER TABLE schedule ADD COLUMN fb_format VARCHAR DEFAULT 'post'")
        conn.commit()
        return True


def ensure_schedule_story_column(db_engine: Engine | None = None) -> bool:
    """Add ``schedule.fb_story`` ("📲 Thêm vào tin": also post it to the Page's Story)."""
    db_engine = db_engine or current_engine()
    with db_engine.connect() as conn:
        insp = inspect(conn)
        if not insp.has_table("schedule"):
            return False
        if "fb_story" in {c["name"] for c in insp.get_columns("schedule")}:
            return False
        default = "FALSE" if conn.dialect.name == "postgresql" else "0"
        conn.exec_driver_sql(f"ALTER TABLE schedule ADD COLUMN fb_story BOOLEAN DEFAULT {default}")
        conn.commit()
        return True


def ensure_decorpreset_favorite_column(db_engine: Engine | None = None) -> bool:
    """Add ``decorpreset.favorite`` (★ a template the seller marked: listed first)."""
    db_engine = db_engine or current_engine()
    with db_engine.connect() as conn:
        insp = inspect(conn)
        if not insp.has_table("decorpreset"):
            return False
        if "favorite" in {c["name"] for c in insp.get_columns("decorpreset")}:
            return False
        default = "FALSE" if conn.dialect.name == "postgresql" else "0"
        conn.exec_driver_sql(f"ALTER TABLE decorpreset ADD COLUMN favorite BOOLEAN DEFAULT {default}")
        conn.commit()
        return True


def ensure_channel_facebook_columns(db_engine: Engine | None = None) -> bool:
    """Add ``channel.fb_page_id`` / ``channel.fb_page_name`` (connected Facebook Page)."""
    db_engine = db_engine or current_engine()
    with db_engine.connect() as conn:
        insp = inspect(conn)
        if not insp.has_table("channel"):
            return False
        cols = {c["name"] for c in insp.get_columns("channel")}
        added = False
        for col in ("fb_page_id", "fb_page_name"):
            if col not in cols:
                conn.exec_driver_sql(f"ALTER TABLE channel ADD COLUMN {col} VARCHAR DEFAULT ''")
                added = True
        conn.commit()
        return added


def ensure_product_aff_columns(db_engine: Engine | None = None) -> bool:
    """Add ``product.aff_link`` / ``product.shop`` and ``post.first_comment``
    to a DB from before affiliate links."""
    db_engine = db_engine or current_engine()
    added = False
    with db_engine.connect() as conn:
        insp = inspect(conn)
        if insp.has_table("product"):
            cols = {c["name"] for c in insp.get_columns("product")}
            for col in ("aff_link", "shop"):
                if col not in cols:
                    conn.exec_driver_sql(f"ALTER TABLE product ADD COLUMN {col} VARCHAR DEFAULT ''")
                    added = True
        if insp.has_table("post"):
            if "first_comment" not in {c["name"] for c in insp.get_columns("post")}:
                conn.exec_driver_sql("ALTER TABLE post ADD COLUMN first_comment VARCHAR DEFAULT ''")
                added = True
        conn.commit()
    return added


def ensure_fbpost_stats_column(db_engine: Engine | None = None) -> bool:
    """Add ``fbpost.stats`` (views, reactions… read back from Facebook) to a table made before it."""
    db_engine = db_engine or current_engine()
    with db_engine.connect() as conn:
        insp = inspect(conn)
        if not insp.has_table("fbpost"):
            return False
        if "stats" in {c["name"] for c in insp.get_columns("fbpost")}:
            return False
        json_type = "JSONB" if conn.dialect.name == "postgresql" else "JSON"
        conn.exec_driver_sql(f"ALTER TABLE fbpost ADD COLUMN stats {json_type}")
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
    ensure_post_channel_column(target)
    ensure_post_series_columns(target)
    ensure_channel_link_columns(target)
    ensure_channel_categories_column(target)
    ensure_product_aff_columns(target)
    ensure_channel_facebook_columns(target)
    ensure_post_video_column(target)
    ensure_schedule_format_column(target)
    ensure_fbpost_stats_column(target)
    ensure_schedule_story_column(target)
    ensure_decorpreset_favorite_column(target)
