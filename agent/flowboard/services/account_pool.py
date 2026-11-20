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
from flowboard.services.flow_sdk import OMNI_FLASH_CREDIT_COST
from flowboard.services.flow_project import effective_project_id, normalize_project_id, set_override

logger = logging.getLogger(__name__)

POOL_KEY = "flow_account_pool"
#: How long a gated job waits for the user to switch the Flow tab.
SWITCH_WAIT_S = 15 * 60
#: Seconds between reads of the Flow account panel while waiting.
SWITCH_POLL_S = 12.0
#: Credits per Veo clip by quality (same table as routes/history.py).
VEO_CREDITS = {"lite": 10, "fast": 20, "quality": 100, "lite_relaxed": 0, "fast_relaxed": 0}
OMNI_CREDITS = OMNI_FLASH_CREDIT_COST  # one table: flow_sdk
# Flow saying the account is out of credits. Deliberately narrow: a bare
# "credit" also matches FLOW_DROPPED_JOB ("… refunded the credits") and
# "paygate" matches paygate_tier_unknown — both once flagged a full account
# as dry and pinned another Google account's project (2026-10-22).
_CREDIT_ERROR = re.compile(
    r"insufficient|not enough credit|out of credit|no credits? (?:left|remaining)|credits? (?:exhausted|depleted)"
    r"|quota (?:exceeded|exhausted)|resource_exhausted|không đủ credit|hết credit",
    re.I,
)
_NOT_A_CREDIT_ERROR = re.compile(r"FLOW_DROPPED_JOB|refund|timeout_waiting_video|paygate_tier", re.I)


#: A balance at or above this clears a stale "exhausted" flag (a few clips).
REVIVE_CREDITS = 50


def is_credit_error(error: Optional[str]) -> bool:
    return bool(error) and bool(_CREDIT_ERROR.search(error)) and not _NOT_A_CREDIT_ERROR.search(error)


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


#: AppSetting key prefix of the project pinned while an account was active (routes/auth.py writes it).
PROJECT_FOR = "flow_project_for:"


def _remembered_projects() -> dict[str, str]:
    """email → the Flow project pinned while that account was the one on the Flow tab."""
    from sqlmodel import select

    with get_session() as s:
        rows = s.exec(select(AppSetting).where(AppSetting.key.startswith(PROJECT_FOR))).all()
    return {r.key[len(PROJECT_FOR):].lower(): r.value for r in rows if r.value}


def wrong_account_message(m: dict) -> str:
    """The reason a video is not sent while the Flow tab and the pinned project belong to different accounts."""
    owner = " / ".join(m["owners"])
    return (f"{WRONG_ACCOUNT}: Tab Flow đang đăng nhập {m['email']}, nhưng dự án Flow đang chọn là của {owner}. "
            f"Flow nhận lệnh rồi bỏ mọi video gửi kiểu này (ảnh vẫn ra) nên DFlow không gửi. Trên tab Flow chuyển về "
            f"tài khoản {owner}, hoặc mở Thiết lập (chấm ở góc dưới sidebar) để dùng dự án của {m['email']}.")


#: Prefix of the error a video job gets when the Flow tab and the pinned project belong to different Google accounts.
WRONG_ACCOUNT = "FLOW_WRONG_ACCOUNT"


class AccountPool:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        # {from_email, to_email, project_id, cost, since, reason}
        self.pending: Optional[dict] = None
        self.last_switch: Optional[dict] = None
        # Latest Flow-tab reading (email, credits, tier), kept for after_login().
        self.last_read: Optional[dict] = None

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

    # ── whose project is pinned ────────────────────────────────────────────
    def project_owners(self, project_id: Optional[str]) -> set[str]:
        """Google accounts the Flow project is known to belong to: the one it was pinned under, pool entries naming
        it, and accounts the seller said share it (``keep_project``)."""
        if not project_id:
            return set()
        data = _load()
        owners = {a["email"] for a in data["accounts"] if a.get("project_id") == project_id and a.get("email")}
        owners |= {e for e, pid in _remembered_projects().items() if pid == project_id}
        owners |= set((data.get("shared") or {}).get(project_id) or [])
        return owners

    def mismatch(self) -> Optional[dict]:
        """The Flow tab is signed in to one Google account while the pinned project is another's (18/11: every video
        of clip #155 dropped for four days — the tab was akiragosho2000, the project hoangduytn1703's; pictures still
        came back). None when it fits, or when nobody is known to own the project."""
        email = self.current_email()
        if not email:
            return None
        try:
            pid = effective_project_id()
        except Exception:  # noqa: BLE001 - nobody signed in yet
            return None
        owners = self.project_owners(pid)
        if not pid or not owners or email in owners:
            return None
        conn = flow_client.active_conn
        tab = conn.tab_project if conn else None
        suggest = None
        for cand in (tab, _remembered_projects().get(email)):
            if cand and cand != pid and not (self.project_owners(cand) - {email}):
                suggest = cand
                break
        return {"email": email, "project_id": pid, "owners": sorted(owners), "suggest_project": suggest,
                "tab_project": tab}

    def share_project(self, project_id: str, email: str) -> None:
        """The seller says this account may use the project too (the mismatch was a false alarm)."""
        norm = _norm_email(email)
        if not norm or not project_id:
            return
        data = _load()
        shared = data.setdefault("shared", {})
        if norm not in shared.setdefault(project_id, []):
            shared[project_id].append(norm)
        _save(data)

    def on_account_read(self, info: dict) -> None:
        """flow_client calls this after every successful ``read_account``:
        the signed-in account joins the pool (with the pinned project when
        it has none yet) and its credits are refreshed."""
        from flowboard.db import has_engine

        email = _norm_email(info.get("email"))
        if email:
            self.last_read = dict(info)
        if not email or not has_engine():  # nobody logged in yet: replayed by after_login()
            return
        acc = self.get(email)
        pid = None
        if acc is None or not acc.get("project_id"):
            try:
                pid = effective_project_id()
            except Exception:  # noqa: BLE001
                pid = None
            # a new account on the tab does not own the project another account pinned — recording it as its own made
            # the wrong project look right; the project the tab has open is a better guess, else none
            if pid and self.project_owners(pid) - {email}:
                tab = flow_client.active_conn.tab_project if flow_client.active_conn else None
                pid = tab if tab and not (self.project_owners(tab) - {email}) else None
        try:
            self.upsert(email, project_id=pid, credits=info.get("credits"), tier=info.get("tier"))
        except ValueError:
            return
        credits = info.get("credits")
        if isinstance(credits, int) and credits >= REVIVE_CREDITS:
            # Flow itself shows a healthy balance: whatever flagged it dry was
            # wrong or is over (it used to stay "exhausted" forever). A low
            # balance (below a few clips) keeps the flag.
            data = _load()
            for a in data["accounts"]:
                if a.get("email") == email and a.get("exhausted_at"):
                    a["exhausted_at"] = None
                    _save(data)
                    break
        if self.pending and self.pending.get("to_email") == email:
            # The user put the Flow tab on the account we asked for.
            self.pending["seen_at"] = time.time()

    def after_login(self) -> None:
        """Replay the last Flow-tab reading once an account's data is open:
        the extension usually connects (and reports real credits) before
        anyone has logged in, when there is nowhere to write it."""
        info = self.last_read
        if info:
            self.on_account_read(info)

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
        if self.pending is None:
            wrong = self.mismatch()
            if wrong:
                # sent anyway, Flow takes it and drops it ~2–4 minutes later (twice with the retry)
                return wrong_account_message(wrong), None
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
        if is_credit_error(error):
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
