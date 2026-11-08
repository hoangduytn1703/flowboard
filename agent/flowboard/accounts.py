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

Roles (8/11): the seed account is the **admin** — the only one that creates
accounts, resets passwords and locks accounts (``routes/account_admin.py``);
every other account can only change its own password. A locked account
cannot log in and its sessions are dropped. Each account is on a plan
(``plan`` column, see ``flowboard/plans.py``) that decides its features.
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

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, func, inspect, select
from sqlalchemy.engine import Engine

from flowboard import config, licensing
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
    # Added 8/11 (ALTERed onto older stores by _ensure_user_columns; NULL = "user" / not locked / no note,
    # so agents still running older code keep working against the same store).
    Column("role", String(16)),
    Column("disabled", Integer),
    Column("note", Text),
    Column("plan", String(32)),  # plans.py id; NULL = the default plan
    Column("plan_expires", DateTime),  # the trial plan ends then (naive UTC); NULL = no end
    Column("profile", Text),  # JSON the account fills in itself: display name, phone, email, contact
    Column("license", Text),  # the admin's signature over role / plan / features / end / lock (licensing.py)
)
ROLE_ADMIN = "admin"
ROLE_USER = "user"
#: Columns added after the first release: name → SQL type for ALTER TABLE.
_LATE_USER_COLUMNS = {"role": "VARCHAR(16)", "disabled": "INTEGER", "note": "TEXT", "plan": "VARCHAR(32)",
                      "plan_expires": "TIMESTAMP", "profile": "TEXT", "license": "TEXT"}
PROFILE_KEYS = ("display_name", "phone", "email", "contact")
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
    if config.PACKAGED:  # the installed app: FLOWBOARD_AUTH=off in .env must not unlock everything
        return True
    return os.getenv("FLOWBOARD_AUTH", "on").lower() not in ("off", "0", "false")


# ── passwords ───────────────────────────────────────────────────────────────

#: Password hashes since the licences (8/11): pbkdf2 over the app's pepper + the username + the password. A hash cannot be
#: made by hand without the compiled app, cannot be copied onto another account (bound to the username), and app builds
#: from before cannot verify it (so they cannot be used to log in).
PASSWORD_SCHEME = "dflow2"


def _peppered(password: str, username: str) -> bytes:
    return licensing.PEPPER + b"\0" + username.strip().lower().encode("utf-8") + b"\0" + password.encode("utf-8")


def hash_password(password: str, username: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", _peppered(password, username), bytes.fromhex(salt), 200_000).hex()
    return f"{PASSWORD_SCHEME}$200000${salt}${digest}"


def verify_password(password: str, stored: str, username: str) -> bool:
    try:
        algo, iters, salt, digest = stored.split("$")
        if algo == PASSWORD_SCHEME:
            data = _peppered(password, username)
        elif algo == "pbkdf2_sha256":  # made before 8/11; re-hashed at the next login in the installed app
            data = password.encode("utf-8")
        else:
            return False
        calc = hashlib.pbkdf2_hmac("sha256", data, bytes.fromhex(salt), int(iters)).hex()
        return hmac.compare_digest(calc, digest)
    except (ValueError, TypeError):
        return False


def needs_rehash(stored: str) -> bool:
    return not (stored or "").startswith(PASSWORD_SCHEME + "$")


# ── central store ───────────────────────────────────────────────────────────

_central: dict[str, Optional[Engine]] = {"engine": None}


def central_engine() -> Engine:
    if _central["engine"] is None:
        url = central_url() or str(Path(config.STORAGE_DIR) / "accounts.db")
        Path(config.STORAGE_DIR).mkdir(parents=True, exist_ok=True)
        _central["engine"] = make_engine(url)
        central_md.create_all(_central["engine"])
        _ensure_user_columns(_central["engine"])
    return _central["engine"]


def _ensure_user_columns(eng: Engine) -> None:
    """Older central stores (Neon since 22/10) lack the 8/11 columns: add them,
    and make the seed account the admin when nobody is one yet."""
    have = {c["name"] for c in inspect(eng).get_columns("account_user")}
    with eng.begin() as c:
        for name, sql_type in _LATE_USER_COLUMNS.items():
            if name not in have:
                c.exec_driver_sql(f"ALTER TABLE account_user ADD COLUMN {name} {sql_type}")
                logger.info("accounts: added account_user.%s", name)
        if c.execute(select(users.c.id).where(users.c.role == ROLE_ADMIN)).first() is None:
            c.execute(users.update().where(users.c.username == SEED_USER).values(role=ROLE_ADMIN))


def reset_central() -> None:
    """Tests: forget the central engine (the storage dir changed)."""
    from flowboard import plans

    _central["engine"] = None
    _session_cache.clear()
    plans.forget()
    licensing.reset()


def central_url() -> Optional[str]:
    """The cloud central store (Neon) when configured — then account data
    can live there too (one schema per account)."""
    url = os.getenv("FLOWBOARD_CENTRAL_DB_URL", "").strip()
    return url or None


def get_setting(key: str) -> Any:
    if _remote(key):  # an account's own entry (AI keys, Page tokens): behind the website's API (cloud_api.py)
        from flowboard import cloud_api
        return cloud_api.get_remote(key)
    with central_engine().connect() as c:
        row = c.execute(select(settings_t).where(settings_t.c.key == key)).first()
    if row is None:
        return None
    try:
        return json.loads(row.value)
    except ValueError:
        return row.value


def set_setting(key: str, value: Any) -> None:
    if _remote(key):
        from flowboard import cloud_api
        cloud_api.set_remote(key, value)
        return
    raw = json.dumps(value, ensure_ascii=False)
    with central_engine().begin() as c:
        if c.execute(select(settings_t.c.key).where(settings_t.c.key == key)).first():
            c.execute(settings_t.update().where(settings_t.c.key == key).values(value=raw))
        else:
            c.execute(settings_t.insert().values(key=key, value=raw))


def _remote(key: str) -> bool:
    from flowboard import cloud_api

    return cloud_api.remote_key(key)


def via_api() -> bool:
    """Phase C: this machine logs in through the DFlow website (cloud_api.py) — the local store is only a copy."""
    from flowboard import cloud_api

    return cloud_api.enabled()


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
    user = {"id": row.id, "username": row.username, "created_at": row.created_at, "backend": backend,
            "password_hash": row.password_hash, "role": getattr(row, "role", None) or ROLE_USER,
            "disabled": bool(getattr(row, "disabled", None)), "note": getattr(row, "note", None) or "",
            "plan": getattr(row, "plan", None) or None, "plan_expires": getattr(row, "plan_expires", None),
            "profile": _profile(getattr(row, "profile", None))}
    # role / plan / end / lock come from the admin's signed licence, not from the row (anyone with the Neon line can edit it)
    licensing.apply(user, getattr(row, "license", None))
    return user


def _profile(raw: Any) -> dict:
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = {}
    return {k: str(data.get(k) or "") for k in PROFILE_KEYS} if isinstance(data, dict) else {k: "" for k in PROFILE_KEYS}


def expired(user: Optional[dict]) -> bool:
    """The account's plan has an end date (the trial, a paid term) that has passed — it cannot log in, like a locked account."""
    if not user or user.get("role") == ROLE_ADMIN:
        return False
    end = user.get("plan_expires")
    return bool(end) and end <= _now()


def is_admin(user: Optional[dict]) -> bool:
    return bool(user) and user.get("role") == ROLE_ADMIN  # type: ignore[union-attr]


def get_user(username: str) -> Optional[dict]:
    with central_engine().connect() as c:
        row = c.execute(select(users).where(users.c.username == username.strip().lower())).first()
    return _row_to_user(row) if row else None


def list_users() -> list[dict]:
    with central_engine().connect() as c:
        rows = c.execute(select(users).order_by(users.c.id)).all()
    return [{k: v for k, v in _row_to_user(r).items() if k != "password_hash"} for r in rows]


def create_user(username: str, password: str, backend: Optional[dict] = None, *,
                role: str = ROLE_USER, note: str = "", plan: Optional[str] = None,
                plan_expires: Optional[datetime] = None) -> dict:
    username = username.strip().lower()
    if not username or len(username) > 64 or not all(ch.isalnum() or ch in "._-" for ch in username):
        raise AuthError("Tên đăng nhập chỉ gồm chữ, số, dấu . _ - (tối đa 64 ký tự).")
    licensing.guard()  # a signed store: only the admin's machine adds accounts
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"Mật khẩu cần ít nhất {MIN_PASSWORD} ký tự.")
    if get_user(username):
        raise AuthError("Tên đăng nhập đã có.")
    with central_engine().begin() as c:
        c.execute(users.insert().values(username=username, password_hash=hash_password(password, username),
                                        created_at=_now(), backend=json.dumps(backend or {"type": "sqlite"}),
                                        role=role, disabled=0, note=(note or "").strip()[:500] or None,
                                        plan=plan or None, plan_expires=plan_expires))
    if licensing.store_licensed():  # (a store nobody signed yet gets its licences from licensing.ensure_epoch)
        licensing.issue(username, plan=plan or None, expires=plan_expires, disabled=False)
    return get_user(username)  # type: ignore[return-value]


def new_account_backend(username: str, cloud: bool = True) -> dict:
    """Where a new account keeps its data: its own schema in the cloud database
    when this machine has one (log in from any machine, no "move to cloud"
    step), else a SQLite file on this machine."""
    if cloud and central_url():
        return {"type": "postgres", "schema": schema_for(username)}
    return {"type": "sqlite"}


def _forget_user_sessions(user_id: int, keep: Optional[str] = None) -> None:
    for tok, (u, _at) in list(_session_cache.items()):
        if u["id"] == user_id and tok != keep:
            _session_cache.pop(tok, None)


def revoke_sessions(username: str, keep: Optional[str] = None) -> int:
    """Log the account out everywhere (but the session ``keep``). Other machines
    notice within their 5-minute session cache."""
    user = get_user(username)
    if user is None:
        return 0
    with central_engine().begin() as c:
        q = sessions.delete().where(sessions.c.user_id == user["id"])
        if keep:
            q = q.where(sessions.c.token != _token_key(keep))
        n = c.execute(q).rowcount or 0
    _forget_user_sessions(user["id"], keep)
    return n


def set_disabled(username: str, disabled: bool) -> None:
    user = get_user(username)
    if licensing.store_licensed() and user is not None and user.get("license") == "ok":
        licensing.issue(username, disabled=disabled)  # the lock goes into the licence: flipping the row back does nothing
    else:
        with central_engine().begin() as c:
            c.execute(users.update().where(users.c.username == username).values(disabled=1 if disabled else 0))
        _refresh_cached(username)
    if disabled:
        revoke_sessions(username)
        lock_db_role(username)


def lock_db_role(username: str) -> None:
    """Phase C: an account the website gave a database login (dflow-web dbrole.ts) loses it at once when locked; its
    next good app login turns it back on. Best effort — only the owner line (the admin's machine) can do it."""
    if central_url() is None:
        return
    from sqlalchemy import text

    try:
        with central_engine().begin() as c:
            row = c.execute(text("SELECT role FROM account_dbrole WHERE username = :u"), {"u": username}).first()
            if row is None or not c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": row.role}).first():
                return
            c.exec_driver_sql('ALTER ROLE "%s" WITH NOLOGIN' % row.role.replace('"', '""'))
            c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = :r"), {"r": row.role})
    except Exception as exc:  # noqa: BLE001 — no table yet (nobody logged in through the website), SQLite store…
        logger.info("accounts: database login of %s not locked (%s)", username, str(exc).splitlines()[0][:120])


def _refresh_cached(username: str) -> None:
    """Sessions cached in RAM carry the user row: re-read it after a plan / role change."""
    fresh = get_user(username)
    if fresh is None:
        return
    for tok, (u, at) in list(_session_cache.items()):
        if u["username"] == username:
            _session_cache[tok] = (fresh, at)
    if _active["user"] and _active["user"]["username"] == username:
        _active["user"].update({k: v for k, v in fresh.items() if k != "password_hash"})


def set_plan(username: str, plan_id: Optional[str], expires: Optional[datetime] = None) -> None:
    """Move an account to a plan; ``expires`` = when it ends (the trial), None = no end. A signed store: a new licence."""
    if licensing.store_licensed():
        licensing.issue(username, plan=plan_id, expires=expires)
        return
    with central_engine().begin() as c:
        c.execute(users.update().where(users.c.username == username).values(plan=plan_id or None, plan_expires=expires))
    _refresh_cached(username)


def set_profile(username: str, profile: dict) -> None:
    clean = {k: " ".join(str(profile.get(k) or "").split())[:120] for k in PROFILE_KEYS}
    with central_engine().begin() as c:
        c.execute(users.update().where(users.c.username == username).values(profile=json.dumps(clean, ensure_ascii=False)))
    _refresh_cached(username)


def fill_null_plans(plan_id: str) -> int:
    """Accounts on "the default plan" (NULL) get that plan written down — before the default changes."""
    with central_engine().begin() as c:
        n = c.execute(users.update().where(users.c.plan.is_(None), users.c.role.is_distinct_from(ROLE_ADMIN))
                      .values(plan=plan_id)).rowcount or 0
    for tok, (u, at) in list(_session_cache.items()):
        _refresh_cached(u["username"])
    return n


def reassign_missing_plans(valid_ids: set[str], default_id: str, expires: Optional[datetime] = None) -> int:
    """After plans were edited: accounts on a deleted plan go to the default one (the trial: it starts now)."""
    with central_engine().begin() as c:
        rows = c.execute(select(users.c.username).where(users.c.plan.is_not(None))
                         .where(users.c.plan.not_in(list(valid_ids)))).all()
        if rows:
            c.execute(users.update().where(users.c.username.in_([r.username for r in rows]))
                      .values(plan=default_id, plan_expires=expires))
    for r in rows:
        _refresh_cached(r.username)
    return len(rows)


def set_note(username: str, note: str) -> None:
    with central_engine().begin() as c:
        c.execute(users.update().where(users.c.username == username).values(note=(note or "").strip()[:500] or None))


def account_overview() -> list[dict]:
    """Every account for the admin page: role, locked, note, where the data
    lives, and its last session (when / from which machine)."""
    with central_engine().connect() as c:
        rows = c.execute(select(users).order_by(users.c.id)).all()
        stats = c.execute(select(sessions.c.user_id, func.count(), func.max(sessions.c.last_seen))
                          .group_by(sessions.c.user_id)).all()
        last_host: dict[int, Optional[str]] = {}
        for r in c.execute(select(sessions.c.user_id, sessions.c.host).order_by(sessions.c.last_seen)).all():
            last_host[r.user_id] = r.host
    by_user = {s[0]: (s[1], s[2]) for s in stats}
    out = []
    for r in rows:
        u = _row_to_user(r)
        n, last = by_user.get(u["id"], (0, None))
        out.append({"username": u["username"], "role": u["role"], "disabled": u["disabled"], "note": u["note"], "plan": u["plan"],
                    "license": u.get("license", "missing"), "tampered": bool(u.get("tampered")),
                    "plan_expires": u["plan_expires"].isoformat() if u["plan_expires"] else None, "expired": expired(u),
                    "display_name": u["profile"]["display_name"],
                    "created_at": u["created_at"].isoformat() if u["created_at"] else None,
                    "backend": (u["backend"] or {}).get("type", "sqlite"),
                    "sessions": int(n or 0), "last_seen": last.isoformat() if last else None,
                    "last_host": last_host.get(u["id"])})
    return out


def set_password(username: str, new_password: str) -> None:
    if len(new_password) < MIN_PASSWORD:
        raise AuthError(f"Mật khẩu cần ít nhất {MIN_PASSWORD} ký tự.")
    with central_engine().begin() as c:
        c.execute(users.update().where(users.c.username == username).values(password_hash=hash_password(new_password, username)))


def seed_default() -> bool:
    """The seed account, once, when there is no user at all. Never in the installed app: its password is public (code,
    README), so an empty account store — e.g. the cloud line removed from .env — would hand out an admin login."""
    if config.PACKAGED or list_users():
        return False
    create_user(SEED_USER, SEED_PASSWORD, role=ROLE_ADMIN)
    logger.info("accounts: seeded user %s", SEED_USER)
    return True


def _authenticate_via_api(username: str, password: str) -> dict:
    """The website checks the password, lock, end date and licence, and hands out the account's database login
    (cloud_api.py). Offline (or the site is down): the copy kept on this machine lets a recent account in."""
    from flowboard import cloud_api

    name = (username or "").strip().lower()
    try:
        cloud_api.login(name, password or "")
    except cloud_api.ApiError as exc:
        if not exc.offline:
            if exc.status == 403 and get_user(name):
                cloud_api.drop(name)  # locked / expired / unlicensed: no offline way in either
                with central_engine().begin() as c:
                    c.execute(users.update().where(users.c.username == name).values(password_hash="!"))
            raise AuthError(exc.detail) from exc
        user = get_user(name)
        if user is None or not verify_password(password or "", user["password_hash"], user["username"]) \
                or not cloud_api.recently_seen(user["username"]):
            raise AuthError(f"Không kết nối được {cloud_api.host()} để đăng nhập — kiểm tra mạng rồi thử lại.") from exc
        logger.warning("accounts: %s logged in offline (%s)", name, exc.detail)
    user = get_user(name)
    if user is None:
        raise AuthError("Sai tên đăng nhập hoặc mật khẩu.")
    return user


def authenticate(username: str, password: str) -> dict:
    if via_api():
        user = _authenticate_via_api(username, password)
    else:
        user = get_user(username or "")
        if user is None or not verify_password(password or "", user["password_hash"], user["username"]):
            raise AuthError("Sai tên đăng nhập hoặc mật khẩu.")
    if user.get("license") == "ok" and needs_rehash(user["password_hash"]) \
            and licensing.legacy_fp(user["password_hash"]) != user.get("license_lh"):
        # an old-format hash the licence was not signed with: written by hand (anyone can make one) — no entry
        raise AuthError("Mật khẩu của tài khoản này cần được người quản lý đặt lại. Liên hệ người quản lý DFlow.")
    if user.get("unlicensed"):
        raise AuthError(licensing.unlicensed_message())
    old_build = licensing.outdated()
    if old_build:
        raise AuthError(old_build)
    if user["disabled"]:
        raise AuthError("Tài khoản này đã bị khoá. Hỏi người quản trị DFlow để mở lại.")
    if expired(user):
        end = user["plan_expires"].strftime("%d/%m/%Y")
        which = "Gói dùng thử" if user.get("plan") == "trial" else "Gói đang dùng"
        raise AuthError(f"{which} của tài khoản này đã hết hạn ({end}). Liên hệ người quản lý DFlow để gia hạn hoặc nâng gói.")
    if licensing.strict() and needs_rehash(user["password_hash"]) and not via_api():
        # the installed app: the hash gets the pepper — app builds from before the licences can no longer log in with it
        with central_engine().begin() as c:
            c.execute(users.update().where(users.c.id == user["id"]).values(password_hash=hash_password(password, user["username"])))
    return user


# ── sessions ────────────────────────────────────────────────────────────────

_session_cache: dict[str, tuple[dict, float]] = {}


def _token_key(token: str) -> str:
    """What the store keeps for a session: a keyed hash (licensing.session_key), never the cookie itself — whoever can
    read or write the table (every machine on the cloud store) can neither log in with what is there nor add a session."""
    return licensing.session_key(token)


def create_session(user: dict, host: Optional[str] = None) -> str:
    # the cookie names its account: a session row pointed at another account by hand (user_id edited) stops matching
    token = f"{user['id']}.{secrets.token_urlsafe(32)}"
    with central_engine().begin() as c:
        c.execute(sessions.insert().values(token=_token_key(token), user_id=user["id"], created_at=_now(), last_seen=_now(),
                                           host=(host or socket.gethostname())[:128]))
    _session_cache[token] = (user, time.time())
    return token


def resolve_session(token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    hit = _session_cache.get(token)
    if hit and time.time() - hit[1] < 300:
        if expired(hit[0]):
            return None
        _check_with_site(hit[0])
        return hit[0]
    with central_engine().connect() as c:
        row = c.execute(select(sessions).where(sessions.c.token == _token_key(token))).first()
        if row is None or str(row.user_id) != token.split(".", 1)[0]:
            return None
        age = (_now() - row.last_seen).total_seconds()
        if age > SESSION_TTL_S:
            return None
        urow = c.execute(select(users).where(users.c.id == row.user_id)).first()
    if urow is None:
        return None
    user = _row_to_user(urow)
    if user["disabled"] or expired(user) or user.get("unlicensed") or licensing.outdated():
        return None
    with central_engine().begin() as c:
        c.execute(sessions.update().where(sessions.c.token == _token_key(token)).values(last_seen=_now()))
    _session_cache[token] = (user, time.time())
    _check_with_site(user)
    return user


def _check_with_site(user: dict) -> None:
    """Phase C: every few minutes the website is asked again (lock, password change, plan change → seen here)."""
    from flowboard import cloud_api

    cloud_api.maybe_refresh(user)


def delete_session(token: Optional[str]) -> None:
    if not token:
        return
    _session_cache.pop(token, None)
    with central_engine().begin() as c:
        c.execute(sessions.delete().where(sessions.c.token == _token_key(token)))


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
    if via_api():
        # the local store is a copy of what the website says: nothing to seed, nothing to sign here
        from flowboard import cloud_api
        logger.info("accounts: logging in through %s (no direct database line)", cloud_api.host())
        return
    seed_default()
    try:  # the admin's machine signs a store nobody signed yet (once — licensing.ensure_epoch)
        signed = licensing.ensure_epoch()
        if signed is not None:
            logger.info("accounts: signed %d accounts (first signing of this store)", signed)
    except Exception:  # noqa: BLE001 — never keep the agent from starting
        logger.exception("accounts: first signing of the store failed")
    # No account active until a request with a valid session arrives.


def user_from_request(request: Any) -> Optional[dict]:
    return resolve_session(request.cookies.get(SESSION_COOKIE))


def status() -> dict:
    u = active_user()
    return {"auth": auth_enabled(), "username": u["username"] if u else None,
            "since": _active["since"], "storage_dir": str(config.STORAGE_DIR),
            "backend": ((u or {}).get("backend") or {}).get("type", "sqlite"), "central_cloud": central_url() is not None,
            "via_api": via_api()}
