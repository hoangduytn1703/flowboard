"""Several Google accounts, one Chrome: switch Flow accounts when credits run out.

A Flow Pro plan carries 100 credits a month (~4 Omni Flash clips), so the
user keeps several Google accounts signed in to the same Chrome and picks
one on the Flow tab. Each account owns its own Flow project (media ids are
scoped to it), so switching means: pin that account's project, ask the
user to put the Flow tab on that account, and only then dispatch.

The pool lives in one ``AppSetting`` row (JSON). The worker calls
:func:`ensure_credits` before every Flow video job; when the active account
cannot pay it marks it exhausted, moves the pin to the next account, opens
a Flow tab for it (best effort, ``authuser=<email>``) and waits — polling
the account panel on the Flow tab — until that account is the one signed
in. Jobs wait instead of failing, so an auto-run keeps going after the
user switches. ``note_result`` keeps a running credit estimate between
reads and catches Flow's own "out of credits" errors.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Optional

from flowboard.db import get_session
from flowboard.db.models import AppSetting
from flowboard.services.flow_client import flow_client
from flowboard.services.flow_project import effective_project_id, normalize_project_id, set_override

logger = logging.getLogger(__name__)

POOL_KEY = "flow_account_pool"
#: How long a gated job waits for the user to switch the Flow tab.
SWITCH_WAIT_S = 15 * 60
#: Seconds between reads of the Flow account panel while waiting.
SWITCH_POLL_S = 12.0
#: Credits per Veo clip by quality (same table as routes/history.py).
VEO_CREDITS = {"lite": 10, "fast": 20, "quality": 100, "lite_relaxed": 0, "fast_relaxed": 0}
OMNI_CREDITS = {4: 15, 6: 20, 8: 25, 10: 30}
_CREDIT_ERROR = re.compile(r"credit|quota|paygate|insufficient|resource_exhausted|không đủ", re.I)


def job_cost(params: dict) -> int:
    """Credits a Flow video job will take, from its params; 0 for anything else."""
    if not isinstance(params, dict):
        return 0
    d = params.get("duration_s")
    if isinstance(d, int) and d in OMNI_CREDITS:
        n = params.get("variant_count")
        return OMNI_CREDITS[d] * (n if isinstance(n, int) and n > 0 else 1)
    if "video_quality" in params or "start_media_id" in params or "start_media_ids" in params:
        q = params.get("video_quality")
        n = params.get("variant_count")
        return VEO_CREDITS.get(q if isinstance(q, str) else "fast", 20) * (n if isinstance(n, int) and n > 0 else 1)
    return 0


def _load() -> dict:
    with get_session() as s:
        row = s.get(AppSetting, POOL_KEY)
    if row is None or not row.value:
        return {"auto": True, "accounts": []}
    try:
        data = json.loads(row.value)
    except ValueError:
        return {"auto": True, "accounts": []}
    data.setdefault("auto", True)
    data.setdefault("accounts", [])
    return data


def _save(data: dict) -> None:
    raw = json.dumps(data, ensure_ascii=False)
    with get_session() as s:
        row = s.get(AppSetting, POOL_KEY)
        if row is None:
            s.add(AppSetting(key=POOL_KEY, value=raw))
        else:
            row.value = raw
        s.commit()


def _norm_email(email: Any) -> Optional[str]:
    if not isinstance(email, str) or "@" not in email:
        return None
    return email.strip().lower()


class AccountPool:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        # {from_email, to_email, project_id, cost, since, reason}
        self.pending: Optional[dict] = None
        self.last_switch: Optional[dict] = None

    job_cost = staticmethod(job_cost)

    # ── storage ────────────────────────────────────────────────────────────
    def list(self) -> dict:
        return _load()

    def accounts(self) -> list[dict]:
        return list(_load()["accounts"])

    def auto(self) -> bool:
        return bool(_load().get("auto", True))

    def set_auto(self, value: bool) -> None:
        data = _load()
        data["auto"] = bool(value)
        _save(data)

    def get(self, email: Optional[str]) -> Optional[dict]:
        email = _norm_email(email)
        if not email:
            return None
        for a in _load()["accounts"]:
            if a.get("email") == email:
                return a
        return None

    def upsert(self, email: str, *, project_id: Optional[str] = None, label: Optional[str] = None,
               credits: Optional[int] = None, enabled: Optional[bool] = None,
               tier: Optional[str] = None) -> dict:
        """Add or update an account. ``project_id`` may be a pasted Flow URL."""
        norm = _norm_email(email)
        if not norm:
            raise ValueError("email không hợp lệ")
        pid = None
        if project_id is not None and str(project_id).strip():
            pid = normalize_project_id(str(project_id))
            if pid is None:
                raise ValueError("project id không hợp lệ — dán uuid hoặc link project Flow")
        data = _load()
        acc = next((a for a in data["accounts"] if a.get("email") == norm), None)
        if acc is None:
            acc = {"email": norm, "project_id": None, "label": "", "credits": None, "credits_at": None,
                   "exhausted_at": None, "enabled": True, "tier": None, "added_at": time.time()}
            data["accounts"].append(acc)
        if pid is not None:
            acc["project_id"] = pid
        if label is not None:
            acc["label"] = label.strip()[:80]
        if credits is not None:
            acc["credits"] = int(credits)
            acc["credits_at"] = time.time()
        if enabled is not None:
            acc["enabled"] = bool(enabled)
        if tier:
            acc["tier"] = tier
        _save(data)
        return acc

    def remove(self, email: str) -> bool:
        norm = _norm_email(email)
        data = _load()
        before = len(data["accounts"])
        data["accounts"] = [a for a in data["accounts"] if a.get("email") != norm]
        _save(data)
        return len(data["accounts"]) < before

    # ── identity ───────────────────────────────────────────────────────────
    def current_email(self) -> Optional[str]:
        conn = flow_client.active_conn
        return _norm_email(conn.email) if conn and conn.email else None

    def on_account_read(self, info: dict) -> None:
        """flow_client calls this after every successful ``read_account``:
        the signed-in account joins the pool (with the pinned project when
        it has none yet) and its credits are refreshed."""
        from flowboard.db import has_engine

        email = _norm_email(info.get("email"))
        if not email or not has_engine():  # nobody logged in yet: nothing to record into
            return
        acc = self.get(email)
        pid = None
        if acc is None or not acc.get("project_id"):
            try:
                pid = effective_project_id()
            except Exception:  # noqa: BLE001
                pid = None
        try:
            self.upsert(email, project_id=pid, credits=info.get("credits"), tier=info.get("tier"))
        except ValueError:
            return
        if self.pending and self.pending.get("to_email") == email:
            # The user put the Flow tab on the account we asked for.
            self.pending["seen_at"] = time.time()

    # ── the switch ─────────────────────────────────────────────────────────
    def next_account(self, cost: int, exclude: Optional[str]) -> Optional[dict]:
        for a in _load()["accounts"]:
            if not a.get("enabled", True) or a.get("email") == exclude or not a.get("project_id"):
                continue
            c = a.get("credits")
            # A known balance decides on its own; an unknown one is worth a
            # try unless the account was already found dry.
            if c is not None:
                if c >= cost:
                    return a
            elif not a.get("exhausted_at"):
                return a
        return None

    def mark_exhausted(self, email: Optional[str], credits: Optional[int] = None) -> None:
        norm = _norm_email(email)
        if not norm:
            return
        data = _load()
        for a in data["accounts"]:
            if a.get("email") == norm:
                a["exhausted_at"] = time.time()
                if credits is not None:
                    a["credits"] = int(credits)
                    a["credits_at"] = time.time()
        _save(data)

    async def begin_switch(self, to: dict, *, cost: int, reason: str, from_email: Optional[str]) -> dict:
        """Pin the account's project and ask the user to put the Flow tab on it."""
        pid = to["project_id"]
        try:
            if pid != effective_project_id():
                set_override(pid)
        except ValueError as exc:
            logger.warning("account_pool: cannot pin %s: %s", pid, exc)
        self.pending = {"from_email": from_email, "to_email": to["email"], "project_id": pid, "cost": cost,
                        "since": time.time(), "reason": reason, "seen_at": None, "tab_opened": False}
        self.last_switch = dict(self.pending)
        logger.info("account_pool: switching %s → %s (%s)", from_email, to["email"], reason)
        await self.open_flow_tab(to["email"])
        return self.pending

    async def open_flow_tab(self, email: str) -> bool:
        """Best effort: the extension opens flow.google.com for that account."""
        if not flow_client.connected:
            return False
        resp = await flow_client._send("open_flow_tab", {"email": email}, timeout=15.0)
        ok = not resp.get("error")
        if self.pending and self.pending.get("to_email") == _norm_email(email):
            self.pending["tab_opened"] = ok
        return ok

    async def check(self) -> dict:
        """Read the Flow tab's account now; resolves a pending switch when
        the expected account is signed in with enough credits."""
        info = await flow_client.read_account()
        if info.get("error"):
            return {"ok": False, "error": info["error"], "pending": self.pending}
        email = _norm_email(info.get("email"))
        credits = info.get("credits")
        if self.pending and email == self.pending.get("to_email"):
            if credits is None or credits >= int(self.pending.get("cost") or 0):
                self.pending = None
                return {"ok": True, "switched": True, "email": email, "credits": credits, "pending": None}
            self.mark_exhausted(email, credits)
            return {"ok": True, "switched": False, "email": email, "credits": credits, "pending": self.pending,
                    "error": "account_also_exhausted"}
        return {"ok": True, "switched": False, "email": email, "credits": credits, "pending": self.pending}

    async def ensure_credits(self, cost: int) -> tuple[Optional[str], Optional[str]]:
        """Gate for a Flow video job. Returns ``(error, project_id)``: error is
        a user-facing reason not to run; project_id is set when the job must
        target a different project than it was dispatched with."""
        if cost <= 0 or not self.auto():
            return None, None
        async with self._lock:
            switched_pid: Optional[str] = None
            deadline = time.time() + SWITCH_WAIT_S
            while True:
                if self.pending is None:
                    email = self.current_email()
                    acc = self.get(email) if email else None
                    if acc is None:
                        # Unknown account (no read yet, or not in the pool): do not block.
                        return None, switched_pid
                    credits = acc.get("credits")
                    if credits is None or credits >= cost:
                        return None, switched_pid
                    nxt = self.next_account(cost, exclude=email)
                    self.mark_exhausted(email, credits)
                    if nxt is None:
                        return (f"Hết credit Flow: tài khoản {email} còn {credits}, cần {cost}, và không còn tài khoản "
                                "nào khác trong danh sách (Cài đặt → Tài khoản Flow)."), switched_pid
                    await self.begin_switch(nxt, cost=cost, reason=f"còn {credits} credit, cần {cost}", from_email=email)
                    switched_pid = nxt["project_id"]
                # Waiting for the user to switch the Flow tab.
                if time.time() > deadline:
                    to = self.pending.get("to_email") if self.pending else "?"
                    return (f"Đang chờ bạn mở tab Flow với tài khoản {to} (đã chờ {SWITCH_WAIT_S // 60} phút). "
                            "Mở tab rồi bấm Tạo lại."), switched_pid
                res = await self.check()
                if res.get("switched"):
                    switched_pid = self.pending["project_id"] if self.pending else switched_pid or effective_project_id()
                    return None, switched_pid
                if res.get("error") == "account_also_exhausted":
                    nxt = self.next_account(cost, exclude=res.get("email"))
                    if nxt is None:
                        self.pending = None
                        return "Hết credit Flow trên mọi tài khoản trong danh sách.", switched_pid
                    await self.begin_switch(nxt, cost=cost, reason="tài khoản kế cũng hết credit", from_email=res.get("email"))
                    switched_pid = nxt["project_id"]
                await asyncio.sleep(SWITCH_POLL_S)

    # ── bookkeeping after jobs ─────────────────────────────────────────────
    def note_result(self, params: dict, error: Optional[str]) -> None:
        cost = job_cost(params)
        if cost <= 0:
            return
        email = self.current_email()
        if error and _CREDIT_ERROR.search(error):
            # Flow said no: whatever we thought, this account is dry.
            self.mark_exhausted(email, 0)
            return
        if error:
            return
        acc = self.get(email)
        if acc and isinstance(acc.get("credits"), int):
            self.upsert(email, credits=max(acc["credits"] - cost, 0))

    def status(self) -> dict:
        data = _load()
        active = self.current_email()
        return {
            "auto": bool(data.get("auto", True)),
            "accounts": data["accounts"],
            "active_email": active,
            "pinned_project_id": effective_project_id(),
            "pending": self.pending,
            "last_switch": self.last_switch,
        }


account_pool = AccountPool()
flow_client.account_listeners.append(account_pool.on_account_read)
