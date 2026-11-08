"""Phase C (8/11): the installed app reaches its cloud data through the DFlow website, never the database owner line.

Before, every machine that logged in held the Neon owner line (pasted on the login page): whoever had it could read and
change every account, the prices, the bank account and the bucket key. Now a friend's app holds only:

- a **token** for the website's app API (``/api/app/*`` on dflow.io.vn), got by logging in there with the account's
  password — the website checks the password, the lock, the end date and the licence;
- the account's **own database login** the website hands out with it: a Postgres role that owns the account's schema
  (``acct_<username>``) and nothing else (dflow-web ``src/lib/dbrole.ts``). The data engine connects with it like before.

Everything that used to live in the shared tables goes through the API:

- the account row (licence, plan, profile) and the signed documents (plans, billing, minimum app build) are copied into a
  **local** account store on the machine (``storage/accounts.db``, the same tables as before): the licence checks,
  the plan features and the local login session work unchanged, offline included (:data:`OFFLINE_OK_S`);
- the account's AI keys (``secrets:<user>``) and Facebook Page tokens (``fb_token:<user>:<channel>``) are read and written
  through ``/api/app/settings`` (:func:`remote_key` — accounts.get_setting / set_setting route them here);
- media files go up and down with short-lived signed links (``/api/app/media``; file_store._ApiBucket);
- upgrade requests, profile, password and "log out other machines" are API calls (routes/account.py, billing.py).

The app re-reads its account every :data:`REFRESH_S` (a lock, password change, plan change or "log out other machines"
reaches it within minutes) — :func:`maybe_refresh`, called from accounts.resolve_session.

On by default in the installed app when its ``.env`` has no ``FLOWBOARD_CENTRAL_DB_URL`` (the admin's own machine may
keep the direct line). ``FLOWBOARD_CLOUD_API`` names another site, or turns it off when empty (tests, repo runs without it).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx

from flowboard import config

logger = logging.getLogger(__name__)

DEFAULT_SITE = "https://dflow.io.vn"
#: How often a logged-in account is checked again with the website.
REFRESH_S = 600
#: Logging in without the website (offline, or it is down) works this long after the last good check.
OFFLINE_OK_S = 7 * 24 * 3600
#: The account's API-kept settings (AI keys, Page tokens) are re-read after this.
SETTINGS_TTL_S = 60
TIMEOUT = httpx.Timeout(25.0, connect=10.0)
#: Shared settings keys that belong to one account and live behind the API (the rest are local copies).
REMOTE_PREFIXES = ("secrets:", "fb_token:")


class ApiError(RuntimeError):
    """The website answered with an error (``detail`` is written for the person), or could not be reached (status 0)."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail

    @property
    def offline(self) -> bool:
        """Not the account's fault: no network, the site is down / erroring."""
        return self.status == 0 or self.status >= 500


def site() -> Optional[str]:
    raw = os.getenv("FLOWBOARD_CLOUD_API")
    if raw is not None:
        raw = raw.strip().rstrip("/")
        return raw or None
    return DEFAULT_SITE if config.PACKAGED else None


def enabled() -> bool:
    """This machine logs in through the website (no direct database line, login on)."""
    from flowboard import accounts

    return site() is not None and accounts.central_url() is None and accounts.auth_enabled()


def host() -> str:
    return urlsplit(site() or DEFAULT_SITE).netloc or "dflow.io.vn"


# ── HTTP ────────────────────────────────────────────────────────────────────

_http: Optional[httpx.Client] = None
_http_lock = threading.Lock()


def _client() -> httpx.Client:
    global _http
    with _http_lock:
        if _http is None:
            from flowboard import __version__

            _http = httpx.Client(timeout=TIMEOUT, headers={"User-Agent": f"DFlow-app/{__version__}", "X-DFlow-App": __version__})
        return _http


def call(method: str, path: str, *, token: Optional[str] = None, body: Any = None,
         params: Optional[dict] = None, timeout: Optional[float] = None) -> Any:
    base = site()
    if not base:
        raise ApiError(0, "App chưa có địa chỉ máy chủ DFlow.")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        resp = _client().request(method, base + path, json=body, params=params, headers=headers,
                                 timeout=timeout if timeout is not None else TIMEOUT)
    except httpx.HTTPError as exc:
        raise ApiError(0, f"Không kết nối được {host()} — kiểm tra mạng rồi thử lại ({type(exc).__name__}).") from exc
    try:
        data = resp.json()
    except ValueError:
        data = None
    if resp.status_code >= 400:
        detail = data.get("detail") if isinstance(data, dict) else None
        raise ApiError(resp.status_code, str(detail or f"Máy chủ DFlow trả lỗi {resp.status_code}."))
    if data is None:
        raise ApiError(502, "Máy chủ DFlow trả dữ liệu không đọc được.")
    return data


# ── the account's token and last good check (local store) ───────────────────

def _local_get(key: str) -> Any:
    from flowboard import accounts

    return accounts.get_setting(key)


def _local_set(key: str, value: Any) -> None:
    from flowboard import accounts

    accounts.set_setting(key, value)


def token(username: str) -> Optional[str]:
    tok = _local_get(f"api_token:{username}")
    return str(tok) if tok else None


def _save_token(username: str, tok: Optional[str]) -> None:
    _local_set(f"api_token:{username}", tok or None)


def recently_seen(username: str) -> bool:
    """The website vouched for this account recently enough to let it in offline."""
    seen = _local_get(f"api_seen:{username}")
    return isinstance(seen, (int, float)) and time.time() - float(seen) < OFFLINE_OK_S


def _need_token(username: str) -> str:
    tok = token(username)
    if not tok:
        raise ApiError(401, "App chưa đăng nhập với máy chủ DFlow — đăng xuất rồi đăng nhập lại.")
    return tok


def account_call(username: str, method: str, path: str, **kw: Any) -> Any:
    """An API call as this account. A 401 (token voided: password changed, logged out elsewhere) logs it out here too."""
    try:
        return call(method, path, token=_need_token(username), **kw)
    except ApiError as exc:
        if exc.status == 401:
            drop(username)
        raise


# ── logging in, storing what the website says ───────────────────────────────

def _parse(text: Any) -> Optional[datetime]:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "")).replace(tzinfo=None)
    except ValueError:
        return None


def login(username: str, password: str) -> dict:
    data = call("POST", "/api/app/login", body={"username": username, "password": password})
    store(data, password=password)
    return data


def store(data: dict, *, password: Optional[str] = None) -> str:
    """Copy the account row, the signed documents and the account's database login into the local store."""
    from sqlalchemy import and_, or_, select

    from flowboard import accounts, plans

    acc = data.get("account") or {}
    db = data.get("db") or {}
    uid, uname = int(acc["id"]), str(acc["username"])
    backend = {"type": "postgres", "schema": str(db.get("schema") or accounts.schema_for(uname)), "url": str(db.get("url") or ""), "via": "api"}
    values = {"username": uname, "created_at": _parse(acc.get("created_at")) or accounts._now(), "backend": json.dumps(backend),
              "role": acc.get("role") or None, "disabled": 1 if acc.get("disabled") else 0, "plan": acc.get("plan") or None,
              "plan_expires": _parse(acc.get("plan_expires")), "profile": acc.get("profile"), "license": acc.get("license")}
    if password is not None:
        values["password_hash"] = accounts.hash_password(password, uname)  # for logging in offline on this machine
    eng = accounts.central_engine()
    old = accounts.get_user(uname)
    with eng.begin() as c:
        # the website decides which id goes with which name (the licence is bound to both)
        clash = [r.id for r in c.execute(select(accounts.users.c.id).where(or_(
            and_(accounts.users.c.username == uname, accounts.users.c.id != uid),
            and_(accounts.users.c.id == uid, accounts.users.c.username != uname)))).all()]
        if clash:
            c.execute(accounts.sessions.delete().where(accounts.sessions.c.user_id.in_(clash)))
            c.execute(accounts.users.delete().where(accounts.users.c.id.in_(clash)))
        if c.execute(select(accounts.users.c.id).where(accounts.users.c.id == uid)).first():
            c.execute(accounts.users.update().where(accounts.users.c.id == uid).values(**values))
        else:
            c.execute(accounts.users.insert().values(id=uid, **{"password_hash": "!", **values}))
    for key, raw in (data.get("settings") or {}).items():
        try:
            _local_set(key, json.loads(raw) if isinstance(raw, str) else raw)
        except ValueError:
            _local_set(key, None)
    if data.get("token"):
        _save_token(uname, str(data["token"]))
    _local_set(f"api_seen:{uname}", time.time())
    _last_check[uname] = time.time()
    plans.forget()
    accounts._refresh_cached(uname)
    active = accounts.active_user()
    if old is not None and active is not None and active["username"] == uname and (old.get("backend") or {}).get("url") != backend["url"]:
        accounts.deactivate()  # a new database login: the next request opens the data with it
    return uname


def drop(username: str) -> None:
    """The website no longer vouches for this account: log it out on this machine."""
    from flowboard import accounts

    try:
        _save_token(username, None)
        accounts.revoke_sessions(username)
    except Exception:  # noqa: BLE001
        logger.exception("cloud_api: could not log %s out locally", username)


# ── checking again every few minutes ────────────────────────────────────────

_last_check: dict[str, float] = {}
_checking: set[str] = set()
_check_lock = threading.Lock()


def maybe_refresh(user: dict) -> None:
    if not enabled():
        return
    name = user["username"]
    with _check_lock:
        if name in _checking or time.time() - _last_check.get(name, 0.0) < REFRESH_S:
            return
        _checking.add(name)
        _last_check[name] = time.time()
    threading.Thread(target=_refresh_quietly, args=(name,), name=f"cloud-check-{name}", daemon=True).start()


def _refresh_quietly(username: str) -> None:
    try:
        refresh(username)
    except Exception:  # noqa: BLE001
        logger.exception("cloud_api: checking %s failed", username)
    finally:
        with _check_lock:
            _checking.discard(username)


def refresh(username: str) -> bool:
    """Re-read the account from the website. False = it is no longer allowed here (logged out on this machine)."""
    tok = token(username)
    if not tok:
        drop(username)
        return False
    try:
        data = call("GET", "/api/app/me", token=tok)
    except ApiError as exc:
        if exc.offline:
            if not recently_seen(username):
                logger.warning("cloud_api: %s not checked for %d days — logged out here", username, OFFLINE_OK_S // 86400)
                drop(username)
                return False
            return True
        logger.info("cloud_api: %s refused by the website (%s): %s", username, exc.status, exc.detail)
        drop(username)
        return False
    store(data)
    return True


# ── the account's own settings behind the API ───────────────────────────────

_settings: dict[str, tuple[float, Any]] = {}


def remote_key(key: str) -> bool:
    return key.startswith(REMOTE_PREFIXES) and enabled()


def _owner(key: str) -> str:
    return key.split(":", 2)[1]


def get_remote(key: str) -> Any:
    hit = _settings.get(key)
    if hit and time.time() - hit[0] < SETTINGS_TTL_S:
        return hit[1]
    try:
        value = account_call(_owner(key), "GET", "/api/app/settings", params={"key": key}).get("value")
    except ApiError as exc:
        logger.warning("cloud_api: reading %s failed: %s", key.split(":", 1)[0], exc.detail)
        return hit[1] if hit else None
    _settings[key] = (time.time(), value)
    return value


def set_remote(key: str, value: Any) -> None:
    account_call(_owner(key), "PUT", "/api/app/settings", body={"key": key, "value": value})
    _settings[key] = (time.time(), value)


def reset() -> None:
    """Tests."""
    _settings.clear()
    _last_check.clear()
    _checking.clear()
