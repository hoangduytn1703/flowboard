"""Signed entitlements ("chữ ký số" of the plans) — what keeps a copy of the app from unlocking itself.

Every machine that logs in to the cloud account store can read and write it (the friends paste the Neon line), so
nothing the agent reads there can be trusted on its own. What decides what an account may do — its role, plan, end date
and lock, the plans with their features and prices, the bank account customers pay to — is **signed** with the admin's
Ed25519 private key, which lives only on the admin's machine (``~/.flowboard/dflow-license.key``: never in the store,
never in the repo). Every agent checks with the public key built into it; a row someone edited by hand no longer matches
its signature and counts for nothing. The website (dflow-web) has a key of its own that the app trusts the same way
(``WEB_PUBLIC_KEY_B64``), so its admin pages change accounts and plans without waiting for the admin's machine.

- **Account licence** (``account_user.license``): ``{v, u, id, r, p, n, f, e, x, t}`` = format, username, user id, role,
  plan id, plan name, features, end date (naive UTC ISO, null = forever), locked, issued at. Bound to the username and id:
  someone else's licence copied onto your row does not work. :func:`apply` lays the licence over the row read from the
  store, so everything that reads ``user["role" | "plan" | "plan_expires" | "disabled"]`` sees the signed values.
- **Signed documents** (``account_setting`` ``"<key>:sig"``): the plans (``plans``), the bank settings (``billing``) and the
  oldest app build allowed (``min_app``).
- The store is **licensed** once the admin's machine has signed it (``account_setting`` ``license_epoch``). From then on —
  and always in the installed app (``config.PACKAGED``) — an account without a valid licence cannot log in. A store
  nobody signed, read by an agent run from the repo, keeps the old behaviour (tests, development).
- **Only the admin's machine signs, and only what the admin decides** (create an account, change a plan / end date / lock,
  save the plans or the bank settings, approve an upgrade). It never re-signs what it finds in the store — that would
  bless a hand-edited row. Unchanged parts of a licence come from the current valid licence, not from the row. The first
  signing of a store ("trust on first use", :func:`ensure_epoch`) happens once per store per admin machine — remembered
  in ``~/.flowboard/license-state.json`` — and never again, even if someone deletes the marker or every licence.

Also here: the **pepper** of password hashes and session keys. Hashes made with it cannot be forged without the app's
compiled code, and app builds from before the licences cannot log in with them (accounts.hash_password).

Not covered (needs a server of our own, Phase C): someone replaying an older licence of their own (e.g. one saved before
a lock), using an app build older than this one with a hand-made password hash, reading other accounts' data with the
Neon line.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from flowboard import config

logger = logging.getLogger(__name__)

#: The admin's public key (Ed25519, raw, base64) — the private half is ~/.flowboard/dflow-license.key on the admin's machine.
PUBLIC_KEY_B64 = "s0Mo+2pZBEqZ34RwBxbuEBJzOH4amOeDLgFLKtP337M="
#: The website's own key (dflow-web manages accounts, plans and prices in parallel with the app — the user's choice, 8/11):
#: what it signs counts like the admin's signature. Private half: ~/.flowboard/dflow-web-license.key, given to the website
#: only (DFLOW_LICENSE_KEY / DFLOW_LICENSE_KEY_FILE). The app itself still signs only with the admin key.
WEB_PUBLIC_KEY_B64 = "R/dwDam2L5e7WXn67EE9J966Ivn42CH/p5cFmNhPCPA="
#: Mixed into password hashes and session keys (accounts.py). Changing it logs everybody out and breaks every password.
PEPPER = bytes.fromhex("1a2b0e6cdec3ca897ace158de5ff14bbb8d0ca3eb107e84175959e3e18b69f37")

FORMAT = 1
EPOCH_KEY = "license_epoch"
_LICENCE_TAG = b"dflow-license:1:"
_DOC_TAG = b"dflow-doc:1:"


class LicenseError(RuntimeError):
    """A signing step this machine cannot do (no key, the plans were edited by hand…), in words for the admin."""


_UNSET: Any = object()
_lock = threading.Lock()
_cache: dict[str, Any] = {"key": None, "key_sig": None, "licensed": {}, "verified": {}}


def reset() -> None:
    """Tests: forget the cached key, verdicts and store state."""
    with _lock:
        _cache.update(key=None, key_sig=None, licensed={}, verified={})


def strict() -> bool:
    """The installed app (and FLOWBOARD_LICENSE_STRICT=1): no licence, no login — whatever the store says."""
    return config.PACKAGED or os.getenv("FLOWBOARD_LICENSE_STRICT") == "1"


# ── keys ────────────────────────────────────────────────────────────────────

def key_file() -> Path:
    return Path(os.getenv("FLOWBOARD_LICENSE_KEY") or (Path.home() / ".flowboard" / "dflow-license.key"))


def _state_file() -> Path:
    return key_file().with_name("license-state.json")


def _public() -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(PUBLIC_KEY_B64))


def _trusted() -> list[Ed25519PublicKey]:
    """Whose signatures count: the admin's key, and the website's."""
    sig = (PUBLIC_KEY_B64, WEB_PUBLIC_KEY_B64)
    with _lock:
        if _cache.get("trusted_sig") == sig:
            return _cache["trusted"]
    keys = [_public()] + ([Ed25519PublicKey.from_public_bytes(base64.b64decode(WEB_PUBLIC_KEY_B64))] if WEB_PUBLIC_KEY_B64 else [])
    with _lock:
        _cache.update(trusted=keys, trusted_sig=sig)
    return keys


def fingerprint() -> str:
    return hashlib.sha256(base64.b64decode(PUBLIC_KEY_B64)).hexdigest()[:16]


def _private() -> Optional[Ed25519PrivateKey]:
    """The signing key when this is the admin's machine (the file exists and matches the built-in public key)."""
    path = key_file()
    try:
        stat = path.stat()
    except OSError:
        return None
    sig = (str(path), stat.st_mtime_ns, PUBLIC_KEY_B64)
    with _lock:
        if _cache["key_sig"] == sig:
            return _cache["key"]
    key: Optional[Ed25519PrivateKey] = None
    try:
        line = next(l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#"))
        cand = Ed25519PrivateKey.from_private_bytes(base64.b64decode(line))
        pub = cand.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        if pub == base64.b64decode(PUBLIC_KEY_B64):
            key = cand
        else:
            logger.warning("licensing: %s is not the key this app checks against — ignored", path)
    except (OSError, StopIteration, ValueError) as exc:
        logger.warning("licensing: cannot read %s (%s)", path, exc)
    with _lock:
        _cache.update(key=key, key_sig=sig)
    return key


def can_sign() -> bool:
    return _private() is not None


def require_key() -> Ed25519PrivateKey:
    key = _private()
    if key is None:
        raise LicenseError(
            "🔒 Máy này không có khoá ký nên không đổi được quyền tài khoản (tạo tài khoản, đổi gói / hạn, khoá, lưu bảng gói / "
            f"thanh toán, duyệt nâng cấp). Làm việc đó trên máy có khoá ({key_file()}).")
    return key


def guard() -> None:
    """Before anything that changes what an account may do: on a licensed store only the admin's machine may."""
    if active():
        require_key()


# ── signing primitives ──────────────────────────────────────────────────────

def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _ok(data: bytes, sig: bytes) -> bool:
    for key in _trusted():
        try:
            key.verify(sig, data)
            return True
        except (InvalidSignature, ValueError):
            continue
    return False


def seal(payload: dict) -> str:
    """payload → "<b64 json>.<b64 signature>" (admin's machine only)."""
    body = canonical(payload)
    return _b64(body) + "." + _b64(require_key().sign(_LICENCE_TAG + body))


def unseal(token: Optional[str]) -> Optional[dict]:
    """The payload of a sealed token when the signature is good, else None (cached: rows are read often)."""
    if not token or "." not in token:
        return None
    with _lock:
        hit = _cache["verified"].get(token)
    if hit is not None:
        return hit or None
    payload: Optional[dict] = None
    try:
        b, s = token.split(".", 1)
        body = _unb64(b)
        if _ok(_LICENCE_TAG + body, _unb64(s)):
            data = json.loads(body)
            payload = data if isinstance(data, dict) and data.get("v") == FORMAT else None
    except (ValueError, TypeError):
        payload = None
    with _lock:
        if len(_cache["verified"]) > 2000:
            _cache["verified"].clear()
        _cache["verified"][token] = payload or {}
    return payload


# ── signed documents ────────────────────────────────────────────────────────

def _doc_bytes(key: str, doc: Any) -> bytes:
    return _DOC_TAG + key.encode() + b":" + canonical(doc)


def sign_doc(key: str, doc: Any) -> None:
    """Store ``doc`` under ``key`` exactly as signed, next to its signature (admin's machine only)."""
    from flowboard import accounts

    sig = _b64(require_key().sign(_doc_bytes(key, doc)))
    accounts.set_setting(key, doc)
    accounts.set_setting(f"{key}:sig", {"sig": sig, "at": _iso(_now())})


def doc_state(key: str) -> str:
    """"ok" (what is stored is what the admin signed) | "missing" (never signed) | "invalid" (changed after signing).
    Checks the stored document itself, not the copy the code normalises from it: a later change to that code (a new
    field, another default) must not void the admin's signatures."""
    from flowboard import accounts

    raw = accounts.get_setting(f"{key}:sig")
    if not isinstance(raw, dict) or not raw.get("sig"):
        return "missing"
    doc = accounts.get_setting(key)
    if doc is None:
        return "invalid"
    try:
        return "ok" if _ok(_doc_bytes(key, doc), _unb64(str(raw["sig"]))) else "invalid"
    except (ValueError, TypeError):
        return "invalid"


def doc_trusted(key: str) -> bool:
    """May customers be shown this document (prices, bank account)? Signed — or nobody signs this store yet."""
    state = doc_state(key)
    return state == "ok" or (state == "missing" and not active())


# ── the store ───────────────────────────────────────────────────────────────

def _store_id() -> str:
    from flowboard import accounts

    url = accounts.central_engine().url.render_as_string(hide_password=True)
    return hashlib.sha256(url.encode()).hexdigest()[:24]


def store_licensed() -> bool:
    """The admin's machine has signed this store (positive answers are kept; negative ones re-checked each minute)."""
    from flowboard import accounts

    sid = _store_id()
    with _lock:
        hit = _cache["licensed"].get(sid)
    if hit is True or (hit and time.time() - hit < 60):
        return True if hit is True else False
    yes = accounts.get_setting(EPOCH_KEY) is not None
    with _lock:
        _cache["licensed"][sid] = True if yes else time.time()
    return yes


def active() -> bool:
    """Licences decide (no licence = no login): the installed app always, elsewhere once the store is signed."""
    return strict() or store_licensed()


# ── account licences ────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.replace(microsecond=0).isoformat() if dt else None


def _parse(text: Any) -> Optional[datetime]:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text)).replace(tzinfo=None)
    except ValueError:
        return None


def _secs(dt: Optional[datetime]) -> Optional[int]:
    return int(dt.replace(tzinfo=timezone.utc).timestamp()) if dt else None


def read(token: Optional[str], username: str, user_id: Any) -> Optional[dict]:
    """The licence of this account when it is signed by the admin and made for this very account."""
    data = unseal(token)
    if not data or data.get("u") != username or data.get("id") != user_id:
        return None
    return data


def apply(user: dict, token: Optional[str]) -> None:
    """Lay the licence over a row read from the store (accounts._row_to_user). ``user["db"]`` keeps the row's own values."""
    from flowboard import accounts

    db = {"role": user["role"], "plan": user["plan"], "plan_expires": user["plan_expires"], "disabled": user["disabled"]}
    user["db"] = db
    lic = read(token, user["username"], user["id"])
    if lic is not None:
        end = _parse(lic.get("e"))
        user.update(role=accounts.ROLE_ADMIN if lic.get("r") == accounts.ROLE_ADMIN else accounts.ROLE_USER,
                    plan=lic.get("p") or None, plan_expires=end, plan_name=lic.get("n") or "",
                    features=[str(f) for f in lic.get("f") or []], disabled=bool(db["disabled"] or lic.get("x")),
                    license="ok", license_issued=lic.get("t"), license_lh=str(lic.get("lh") or ""))
        user["tampered"] = (db["plan"] or None) != (lic.get("p") or None) or _secs(db["plan_expires"]) != _secs(end) \
            or bool(db["disabled"]) != bool(lic.get("x")) or (db["role"] == accounts.ROLE_ADMIN) != (lic.get("r") == accounts.ROLE_ADMIN)
        return
    user["license"] = "invalid" if token else "missing"
    user["tampered"] = False
    if active():
        user.update(role=accounts.ROLE_USER, unlicensed=True, features=[])


def legacy_fp(stored_hash: str) -> str:
    """Pins an old-format password hash (made before the pepper) in the licence: anyone can make such a hash, so one that
    is not the hash the licence was signed with means the row was edited — accounts.authenticate refuses it."""
    return hashlib.sha256(("dflow-legacy:" + (stored_hash or "")).encode("utf-8")).hexdigest()[:20]


def unlicensed_message() -> str:
    return ("Tài khoản này chưa được người quản lý cấp quyền trên app (thiếu chữ ký số hoặc chữ ký không khớp). "
            "Liên hệ người quản lý DFlow.")


def _plans_for_signing() -> dict:
    from flowboard import plans

    doc = plans.load(fresh=True)
    if active() and doc_state(plans.SETTING_KEY) != "ok":
        raise LicenseError("Bảng gói trong cơ sở dữ liệu không khớp chữ ký (có thể đã bị sửa tay). Mở 📦 Gói & tính năng, "
                           "kiểm tra lại rồi bấm 💾 Lưu gói — rồi làm lại việc này.")
    return doc


def issue(username: str, *, plan: Any = _UNSET, expires: Any = _UNSET, disabled: Any = _UNSET,
          _doc: Optional[dict] = None, _trust_row: bool = False) -> dict:
    """Sign a licence for an account the admin just decided on, and write the row to match it. What the admin did not
    choose this time comes from the account's current valid licence — never from the row (it may be hand-edited);
    ``_trust_row`` is only for the very first signing of a store (:func:`ensure_epoch`)."""
    from flowboard import accounts, plans

    require_key()
    user = accounts.get_user(username)
    if user is None:
        raise LicenseError("Không có tài khoản này.")
    cur = read(_raw_licence(username), user["username"], user["id"])
    db = user["db"]
    if cur is None and not _trust_row and (plan is _UNSET or expires is _UNSET):
        raise LicenseError(f"Tài khoản {username} chưa có chữ ký hợp lệ — mở “Gói & thời hạn” của tài khoản này, chọn gói và "
                           "thời hạn rồi lưu (máy sẽ ký lại).")
    base_plan = (cur.get("p") or None) if cur is not None else db["plan"]
    base_end = _parse(cur.get("e")) if cur is not None else db["plan_expires"]
    base_off = bool(cur.get("x")) if cur is not None else bool(db["disabled"])
    plan_id = base_plan if plan is _UNSET else (plan or None)
    end = base_end if expires is _UNSET else expires
    off = base_off if disabled is _UNSET else bool(disabled)
    doc = _doc or _plans_for_signing()
    admin = username == accounts.SEED_USER and db["role"] == accounts.ROLE_ADMIN
    if admin:
        plan_id, end, name, feats = None, None, "Toàn quyền", list(plans.FEATURE_KEYS)
    else:
        row = next((p for p in doc["plans"] if p["id"] == plan_id), None)
        if row is None:  # unknown / deleted plan → the trial, from today
            row = next(p for p in doc["plans"] if p["id"] == plans.TRIAL_ID)
            plan_id, end = row["id"], plans.trial_end()
        name, feats = row["name"], list(row["features"])
    end = end.replace(microsecond=0) if end else None
    # an old-format password hash: pinned at the first signing, then carried over (never re-read from the row)
    if cur is not None:
        lh = str(cur.get("lh") or "")
    elif _trust_row and accounts.needs_rehash(user["password_hash"]):
        lh = legacy_fp(user["password_hash"])
    else:
        lh = ""
    payload = {"v": FORMAT, "u": user["username"], "id": user["id"], "r": accounts.ROLE_ADMIN if admin else accounts.ROLE_USER,
               "p": plan_id or "", "n": name, "f": feats, "e": _iso(end), "x": 1 if off else 0, "lh": lh, "t": int(time.time())}
    token = seal(payload)
    with accounts.central_engine().begin() as c:
        c.execute(accounts.users.update().where(accounts.users.c.username == user["username"])
                  .values(license=token, plan=plan_id, plan_expires=end, disabled=1 if off else 0))
    accounts._refresh_cached(user["username"])
    return payload


def _raw_licence(username: str) -> Optional[str]:
    from flowboard import accounts
    from sqlalchemy import select

    with accounts.central_engine().connect() as c:
        row = c.execute(select(accounts.users.c.license).where(accounts.users.c.username == username)).first()
    return row.license if row else None


def resign_after_plans(doc: dict) -> int:
    """The plans were just saved (and signed): accounts whose plan was renamed, got other features or was deleted get a
    new licence — plan and end date from their current licence (a deleted plan → the trial, from today)."""
    from flowboard import accounts

    n = 0
    by_id = {p["id"]: p for p in doc["plans"]}
    for u in accounts.list_users():
        if u.get("license") != "ok" or u["role"] == accounts.ROLE_ADMIN:
            continue
        p = by_id.get(u.get("plan") or "")
        if p is not None and p["name"] == u.get("plan_name") and list(p["features"]) == list(u.get("features") or []):
            continue
        issue(u["username"], _doc=doc)
        n += 1
    return n


# ── the first signing of a store ────────────────────────────────────────────

def _local_state() -> dict:
    try:
        data = json.loads(_state_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _remember(sid: str, info: dict) -> None:
    state = _local_state()
    state.setdefault("stores", {})[sid] = info
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def ensure_epoch() -> Optional[int]:
    """On the admin's machine: sign a store nobody signed yet — once ("trust on first use": the accounts, plans and bank
    settings as they are now). Returns how many accounts were signed, or None when nothing was done."""
    from flowboard import accounts, billing, plans
    from flowboard import __version__

    if not can_sign():
        return None
    sid = _store_id()
    marker = accounts.get_setting(EPOCH_KEY)
    known = sid in (_local_state().get("stores") or {})
    if marker is not None:
        if not known:
            _remember(sid, {"at": _iso(_now()), "accounts": None, "adopted": True})
        return None
    users = accounts.list_users()
    any_signed = any(u.get("license") == "ok" for u in users)
    if known or any_signed:
        # signed before (by this machine, or with this key elsewhere): the marker was removed — put it back, sign nothing
        logger.warning("licensing: the store's %s marker was missing — restored, nothing re-signed", EPOCH_KEY)
        accounts.set_setting(EPOCH_KEY, {"at": _iso(_now()), "host": socket.gethostname(), "key": fingerprint(), "restored": True})
        _remember(sid, {"at": _iso(_now()), "accounts": None, "restored": True})
        with _lock:
            _cache["licensed"].pop(sid, None)
        return None
    doc = plans.load(fresh=True)
    sign_doc(plans.SETTING_KEY, doc)  # (sign_doc stores each document exactly as signed)
    sign_doc(billing.SETTING_KEY, billing.load())
    sign_doc("min_app", {"v": __version__})
    n = 0
    # the admin first: if the store drops the connection halfway, the admin can still log in and assign the rest by hand
    for u in sorted(users, key=lambda u: u["username"] != accounts.SEED_USER):
        issue(u["username"], _doc=doc, _trust_row=True)
        n += 1
    accounts.set_setting(EPOCH_KEY, {"at": _iso(_now()), "host": socket.gethostname(), "key": fingerprint(), "accounts": n})
    _remember(sid, {"at": _iso(_now()), "accounts": n})
    with _lock:
        _cache["licensed"].pop(sid, None)
    logger.info("licensing: store signed for the first time — %d accounts", n)
    return n


# ── the oldest app build allowed ────────────────────────────────────────────

def _ver(text: str) -> tuple[int, ...]:
    out = []
    for part in str(text).split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits or 0))
    return tuple(out)


def outdated() -> Optional[str]:
    """Why this build may not be used with this store (older than the signed minimum), or None."""
    from flowboard import accounts
    from flowboard import __version__

    if not active():
        return None
    raw = accounts.get_setting("min_app")
    if raw is None:
        return None if not strict() or not store_licensed() else "Thiếu thông tin phiên bản tối thiểu trên cơ sở dữ liệu — liên hệ người quản lý."
    if doc_state("min_app") != "ok":
        return "Thông tin phiên bản tối thiểu trên cơ sở dữ liệu không khớp chữ ký — liên hệ người quản lý."
    need = str((raw or {}).get("v") or "0")
    if _ver(__version__) < _ver(need):
        return f"Bản DFlow trên máy này ({__version__}) đã cũ — cài bản {need} trở lên rồi đăng nhập lại."
    return None


def session_key(token: str) -> str:
    """What the store keeps for a session cookie (accounts.py): keyed with the pepper, so neither the cookie can be read
    back from it nor a session be added by hand."""
    return hmac.new(PEPPER, token.encode("utf-8"), hashlib.sha256).hexdigest()


def status() -> dict:
    """For the admin page."""
    return {"active": active(), "strict": strict(), "can_sign": can_sign(), "key_path": str(key_file()),
            "fingerprint": fingerprint(),
            "web_fingerprint": hashlib.sha256(base64.b64decode(WEB_PUBLIC_KEY_B64)).hexdigest()[:16] if WEB_PUBLIC_KEY_B64 else ""}
