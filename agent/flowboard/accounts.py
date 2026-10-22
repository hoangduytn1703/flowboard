"""Login and per-account data.

Two stores:

* the **central** store (``storage/accounts.db``, or ``FLOWBOARD_CENTRAL_DB_URL``
  once it lives in the cloud): who the users are and their login sessions;
* one **data** store per account: everything else (boards, products, models,
  prompts, history, media). Today a SQLite file + media folder under
  ``storage/accounts/<username>/``; an account's ``backend`` row says where
  (``{"type": "sqlite"}`` now, a Postgres schema + bucket later), so moving
  an account to the cloud is a row change, not a code change.

The agent serves one account at a time (it drives the Chrome next to it):
a request with a valid session cookie *activates* that account — swaps the
data engine (:func:`flowboard.db.set_engine`) and the media folders — and
every ``get_session()`` after that reads and writes that account's data.
Switching accounts waits for the worker to finish the job in flight.

``FLOWBOARD_AUTH=off`` keeps the old single-user behaviour (the tests run
that way): no login, the default ``storage/flowboard.db``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import shutil
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, select
from sqlalchemy.engine import Engine

from flowboard import config
from flowboard.db import init_db, make_engine, set_engine

logger = logging.getLogger(__name__)

SESSION_COOKIE = "fb_session"
SESSION_TTL_S = 30 * 24 * 3600
#: The account created on first start (user's request, 22/10).
SEED_USER = os.getenv("FLOWBOARD_SEED_USER", "akiragosho")
SEED_PASSWORD = os.getenv("FLOWBOARD_SEED_PASSWORD", "Password@123")
MIN_PASSWORD = 6
#: Seconds a login waits for the worker to finish the other account's job.
SWITCH_WAIT_S = 30.0

central_md = MetaData()
users = Table(
    "account_user", central_md,
    Column("id", Integer, primary_key=True),
    Column("username", String(64), unique=True, nullable=False),
    Column("password_hash", String(256), nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("backend", Text, nullable=False, default="{}"),
)
#: Settings every machine should share once it logs in (the media bucket…).
settings_t = Table(
    "account_setting", central_md,
    Column("key", String(64), primary_key=True),
    Column("value", Text, nullable=False),
)
sessions = Table(
    "account_session", central_md,
    Column("token", String(64), primary_key=True),
    Column("user_id", Integer, nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("last_seen", DateTime, nullable=False),
    Column("host", String(128)),
)


class AuthError(RuntimeError):
    """Bad credentials / invalid session."""


class AccountBusy(RuntimeError):
    """Cannot switch accounts while a job of the other one is running."""


def auth_enabled() -> bool:
    return os.getenv("FLOWBOARD_AUTH", "on").lower() not in ("off", "0", "false")


# ── passwords ───────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000).hex()
    return f"pbkdf2_sha256$200000${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iters)).hex()
        return hmac.compare_digest(calc, digest)
    except (ValueError, TypeError):
        return False


# ── central store ───────────────────────────────────────────────────────────

_central: dict[str, Optional[Engine]] = {"engine": None}


def central_engine() -> Engine:
    if _central["engine"] is None:
        url = central_url() or str(Path(config.STORAGE_DIR) / "accounts.db")
        Path(config.STORAGE_DIR).mkdir(parents=True, exist_ok=True)
        _central["engine"] = make_engine(url)
        central_md.create_all(_central["engine"])
    return _central["engine"]


def reset_central() -> None:
    """Tests: forget the central engine (the storage dir changed)."""
    _central["engine"] = None
    _session_cache.clear()


def central_url() -> Optional[str]:
    """The cloud central store (Neon) when configured — then account data
    can live there too (one schema per account)."""
    url = os.getenv("FLOWBOARD_CENTRAL_DB_URL", "").strip()
    return url or None


def get_setting(key: str) -> Any:
    with central_engine().connect() as c:
        row = c.execute(select(settings_t).where(settings_t.c.key == key)).first()
    if row is None:
        return None
    try:
        return json.loads(row.value)
    except ValueError:
        return row.value


def set_setting(key: str, value: Any) -> None:
    raw = json.dumps(value, ensure_ascii=False)
    with central_engine().begin() as c:
        if c.execute(select(settings_t.c.key).where(settings_t.c.key == key)).first():
            c.execute(settings_t.update().where(settings_t.c.key == key).values(value=raw))
        else:
            c.execute(settings_t.insert().values(key=key, value=raw))


def set_backend(username: str, backend: dict) -> None:
    with central_engine().begin() as c:
        c.execute(users.update().where(users.c.username == username).values(backend=json.dumps(backend)))
    for tok, (u, at) in list(_session_cache.items()):
        if u["username"] == username:
            _session_cache[tok] = ({**u, "backend": backend}, at)
    if _active["user"] and _active["user"]["username"] == username:
        _active["user"]["backend"] = backend


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _row_to_user(row: Any) -> dict:
    try:
        backend = json.loads(row.backend or "{}")
    except ValueError:
        backend = {}
    return {"id": row.id, "username": row.username, "created_at": row.created_at, "backend": backend,
            "password_hash": row.password_hash}


def get_user(username: str) -> Optional[dict]:
    with central_engine().connect() as c:
        row = c.execute(select(users).where(users.c.username == username.strip().lower())).first()
    return _row_to_user(row) if row else None


def list_users() -> list[dict]:
    with central_engine().connect() as c:
        rows = c.execute(select(users).order_by(users.c.id)).all()
    return [{k: v for k, v in _row_to_user(r).items() if k != "password_hash"} for r in rows]


def create_user(username: str, password: str, backend: Optional[dict] = None) -> dict:
    username = username.strip().lower()
    if not username or len(username) > 64 or not all(ch.isalnum() or ch in "._-" for ch in username):
        raise AuthError("Tên đăng nhập chỉ gồm chữ, số, dấu . _ - (tối đa 64 ký tự).")
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"Mật khẩu cần ít nhất {MIN_PASSWORD} ký tự.")
    if get_user(username):
        raise AuthError("Tên đăng nhập đã có.")
    with central_engine().begin() as c:
        c.execute(users.insert().values(username=username, password_hash=hash_password(password),
                                        created_at=_now(), backend=json.dumps(backend or {"type": "sqlite"})))
    return get_user(username)  # type: ignore[return-value]


def set_password(username: str, new_password: str) -> None:
    if len(new_password) < MIN_PASSWORD:
        raise AuthError(f"Mật khẩu cần ít nhất {MIN_PASSWORD} ký tự.")
    with central_engine().begin() as c:
        c.execute(users.update().where(users.c.username == username).values(password_hash=hash_password(new_password)))


def seed_default() -> bool:
    """The seed account, once, when there is no user at all."""
    if list_users():
        return False
    create_user(SEED_USER, SEED_PASSWORD)
    logger.info("accounts: seeded user %s", SEED_USER)
    return True


def authenticate(username: str, password: str) -> dict:
    user = get_user(username or "")
    if user is None or not verify_password(password or "", user["password_hash"]):
        raise AuthError("Sai tên đăng nhập hoặc mật khẩu.")
    return user


# ── sessions ────────────────────────────────────────────────────────────────

_session_cache: dict[str, tuple[dict, float]] = {}


def create_session(user: dict, host: Optional[str] = None) -> str:
    token = secrets.token_urlsafe(32)
    with central_engine().begin() as c:
        c.execute(sessions.insert().values(token=token, user_id=user["id"], created_at=_now(), last_seen=_now(),
                                           host=(host or socket.gethostname())[:128]))
    _session_cache[token] = (user, time.time())
    return token


def resolve_session(token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    hit = _session_cache.get(token)
    if hit and time.time() - hit[1] < 300:
        return hit[0]
    with central_engine().connect() as c:
        row = c.execute(select(sessions).where(sessions.c.token == token)).first()
        if row is None:
            return None
        age = (_now() - row.last_seen).total_seconds()
        if age > SESSION_TTL_S:
            return None
        urow = c.execute(select(users).where(users.c.id == row.user_id)).first()
    if urow is None:
        return None
    user = _row_to_user(urow)
    with central_engine().begin() as c:
        c.execute(sessions.update().where(sessions.c.token == token).values(last_seen=_now()))
    _session_cache[token] = (user, time.time())
    return user


def delete_session(token: Optional[str]) -> None:
    if not token:
        return
    _session_cache.pop(token, None)
    with central_engine().begin() as c:
        c.execute(sessions.delete().where(sessions.c.token == token))


# ── the active account ──────────────────────────────────────────────────────

_active: dict[str, Any] = {"user": None, "since": None}
_switch_lock = threading.Lock()
#: Run after an account's data store is opened (orphan recovery, seeds…).
after_activate: list[Callable[[], None]] = []
_ROOT_STORAGE = Path(config.STORAGE_DIR)
_ROOT_DB = Path(config.DB_PATH)


def active_user() -> Optional[dict]:
    return _active["user"]


def account_dir(username: str) -> Path:
    return _ROOT_STORAGE / "accounts" / username


def _adopt_legacy_data(dest: Path) -> bool:
    """First login of the seed account on a machine that already has the old
    single-user data: move it into the account folder instead of starting
    empty. Only when the account folder does not exist yet."""
    if dest.exists() or not _ROOT_DB.is_file():
        return False
    dest.mkdir(parents=True, exist_ok=True)
    shutil.move(str(_ROOT_DB), str(dest / "flowboard.db"))
    for sub in ("media", "chat_uploads"):
        src = _ROOT_STORAGE / sub
        if src.is_dir():
            shutil.move(str(src), str(dest / sub))
    logger.info("accounts: moved the old single-user data into %s", dest)
    return True


def _point_storage(dest: Path) -> None:
    """Re-point every module-level path at this account's folder."""
    from flowboard.services import media as media_service
    from flowboard.services import tts

    dest.mkdir(parents=True, exist_ok=True)
    config.STORAGE_DIR = dest
    config.DB_PATH = dest / "flowboard.db"
    media_service.MEDIA_CACHE_DIR = dest / "media"
    media_service.MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tts.TTS_DIR = dest / "media" / "tts"


def _wait_worker_idle() -> None:
    try:
        from flowboard.worker.processor import get_worker
        worker = get_worker()
    except Exception:  # noqa: BLE001
        return
    end = time.time() + SWITCH_WAIT_S
    while worker.active_count > 0:  # a property
        if time.time() > end:
            raise AccountBusy("Đang có việc của tài khoản khác chạy (tạo ảnh/video). Chờ xong rồi đăng nhập lại.")
        time.sleep(0.5)


def activate(user: dict) -> None:
    """Make ``user``'s data the one the agent serves."""
    cur = _active["user"]
    if cur is not None and cur["id"] == user["id"]:
        return
    with _switch_lock:
        cur = _active["user"]
        if cur is not None and cur["id"] == user["id"]:
            return
        if cur is not None:
            _wait_worker_idle()
        backend = user.get("backend") or {}
        dest = account_dir(user["username"])
        if user["username"] == SEED_USER:
            _adopt_legacy_data(dest)
        _point_storage(dest)
        eng = data_engine(user)
        set_engine(eng)
        init_db(eng)
        _active.update(user={k: v for k, v in user.items() if k != "password_hash"}, since=time.time())
        logger.info("accounts: active account → %s (%s, %s)", user["username"], dest, backend.get("type") or "sqlite")
        for fn in list(after_activate):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                logger.warning("accounts: after_activate hook %s failed: %s", getattr(fn, "__name__", fn), exc)
        # Media of the account: upload what the bucket lacks, fetch what this machine lacks.
        from flowboard.services import file_store
        file_store.reset()
        file_store.reconcile_in_background()


def schema_for(username: str) -> str:
    return "acct_" + "".join(ch if ch.isalnum() else "_" for ch in username.lower())


def data_engine(user: dict) -> Engine:
    """The engine for an account's data: its Postgres schema in the central
    cloud database when its backend says so, else its SQLite file."""
    backend = user.get("backend") or {}
    if backend.get("type") == "postgres":
        url = backend.get("url") or central_url()
        if not url:
            raise AuthError("Tài khoản này để dữ liệu trên cloud nhưng máy này chưa có FLOWBOARD_CENTRAL_DB_URL trong .env.")
        return make_engine(url, schema=backend.get("schema") or schema_for(user["username"]))
    return make_engine(account_dir(user["username"]) / "flowboard.db")


def move_to_cloud(username: str) -> dict:
    """Copy an account's SQLite data into its Postgres schema and switch the
    account's backend to it (the SQLite file stays as a backup). Run with the
    account NOT in the middle of a job."""
    import sqlite3

    from sqlalchemy import text
    from sqlmodel import SQLModel

    url = central_url()
    if not url:
        raise AuthError("Chưa có FLOWBOARD_CENTRAL_DB_URL (chuỗi kết nối Neon) trong .env.")
    user = get_user(username)
    if user is None:
        raise AuthError("Không có tài khoản này.")
    if (user.get("backend") or {}).get("type") == "postgres":
        return {"moved": False, "reason": "already on cloud", "tables": {}}
    src = account_dir(username) / "flowboard.db"
    schema = schema_for(username)
    dest = make_engine(url, schema=schema)
    init_db(dest)
    with dest.connect() as c:
        n = (c.execute(text("SELECT count(*) FROM board")).scalar() or 0) + (c.execute(text("SELECT count(*) FROM product")).scalar() or 0)
    if n:
        raise AuthError(f"Schema {schema} trên cloud đã có {n} clip/sản phẩm — không chép đè. Xoá schema đó trước nếu muốn chép lại.")
    copied: dict[str, int] = {}
    if src.is_file():
        srcdb = sqlite3.connect(str(src))
        src_tables = {r[0] for r in srcdb.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        with dest.begin() as conn:
            for table in SQLModel.metadata.sorted_tables:
                if table.name not in src_tables:
                    continue
                src_cols = [r[1] for r in srcdb.execute(f"PRAGMA table_info({table.name})")]
                cols = [c for c in table.columns if c.name in src_cols]
                if not cols:
                    continue
                rows = srcdb.execute(f"SELECT {', '.join(c.name for c in cols)} FROM {table.name}").fetchall()
                if not rows:
                    continue
                conn.execute(table.delete())  # seeds written by init_db on the empty side
                conn.execute(table.insert(), [dict(zip([c.name for c in cols], _coerce_row(cols, r))) for r in rows])
                copied[table.name] = len(rows)
            # Sequences continue after the copied ids (integer ids only —
            # ``providerjob.id`` and friends are text keys without a sequence).
            from sqlalchemy import Integer as _Int

            for table in SQLModel.metadata.sorted_tables:
                if table.name not in copied or "id" not in table.columns:
                    continue
                id_type = table.columns["id"].type
                if isinstance(getattr(id_type, "impl", id_type), _Int):
                    q = 'SELECT setval(pg_get_serial_sequence(\'"%s"."%s"\', \'id\'), COALESCE((SELECT MAX(id) FROM "%s"."%s"), 1))' % (schema, table.name, schema, table.name)
                    conn.exec_driver_sql(q)
        srcdb.close()
    set_backend(username, {"type": "postgres", "schema": schema})
    dest.dispose()
    return {"moved": True, "schema": schema, "tables": copied}


def _coerce_row(cols: list, row: tuple) -> list:
    """SQLite gives JSON as text and datetimes as strings; Postgres wants the real thing."""
    import json as _json
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    from sqlalchemy import JSON as _JSON
    from sqlalchemy import Boolean as _Bool
    from sqlalchemy import DateTime as _DT

    out = []
    for col, val in zip(cols, row):
        # SQLModel wraps DateTime in a TypeDecorator (UTCDateTime): look at ``impl``.
        t = col.type
        base = getattr(t, "impl", t)
        if val is not None and isinstance(base, _JSON) and isinstance(val, str):
            try:
                val = _json.loads(val)
            except ValueError:
                pass
        elif val is not None and isinstance(base, _DT) and isinstance(val, str):
            try:
                val = _dt.fromisoformat(val.replace("Z", "+00:00"))
            except ValueError:
                pass
            else:
                if val.tzinfo is None:  # SQLite rows are naive UTC; UTCDateTime insists on tz
                    val = val.replace(tzinfo=_tz.utc)
        elif val is not None and isinstance(base, _Bool) and isinstance(val, int):
            val = bool(val)
        out.append(val)
    return out


def deactivate() -> None:
    _active.update(user=None, since=None)


def startup() -> None:
    """Called from the app lifespan before anything touches the data."""
    if not auth_enabled():
        init_db()
        for fn in list(after_activate):
            fn()
        return
    central_engine()
    seed_default()
    # No account active until a request with a valid session arrives.


def user_from_request(request: Any) -> Optional[dict]:
    return resolve_session(request.cookies.get(SESSION_COOKIE))


def status() -> dict:
    u = active_user()
    return {"auth": auth_enabled(), "username": u["username"] if u else None,
            "since": _active["since"], "storage_dir": str(config.STORAGE_DIR),
            "backend": ((u or {}).get("backend") or {}).get("type", "sqlite"), "central_cloud": central_url() is not None}
