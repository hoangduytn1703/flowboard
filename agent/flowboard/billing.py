"""Plan upgrades paid by bank transfer, checked by hand.

The admin sets the bank account and the transfer text template (default ``"{username} - {plan}"``, ``{term}`` = the
term bought) on "👥 Quản lý tài khoản"; the terms each plan is sold for (1 / 3 / 6 months, 1 / 2 years, forever — a price
and an optional list price shown struck through) are part of the plan (plans.py ``terms``, edited on "📦 Gói & tính
năng"). An account picks a plan + term on
"⬆ Nâng cấp", sees a VietQR code (amount + transfer text filled in) and its new end date, pays from its bank app, then
presses "Tôi đã chuyển khoản": that files an upgrade request. The admin checks the bank statement and approves (the
account moves to that plan until the end of the term — time left on the same plan is kept) or rejects. No payment is
verified automatically.

The QR is a NAPAS VietQR payload (EMVCo merchant-presented, "QRIBFTTA" = transfer to an account) built here and
drawn by the browser — no third-party QR service sees the account number. Settings live in the central store
(``account_setting`` key ``billing``), requests in the central table ``account_upgrade``.

Phase C (8/11): an app that logs in through the DFlow website (cloud_api.py) still works out the prices and the QR from
its local copy of the signed documents, but the requests live on the website (``/api/app/upgrade*``), which works the
price out again from its own signed plans before filing one.
"""
from __future__ import annotations

import re
import unicodedata
import weakref
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Column, DateTime, Integer, String, Table, Text, inspect, select

from flowboard import accounts, licensing, plans

SETTING_KEY = "billing"
DEFAULT_TEMPLATE = "{username} - {plan}"
TEXT_MAX = 50  # bank apps cut longer transfer texts

#: Common Vietnamese banks and their NAPAS BIN (the admin can also type another BIN).
BANKS: list[dict[str, str]] = [
    {"bin": "970436", "code": "VCB", "name": "Vietcombank"},
    {"bin": "970415", "code": "ICB", "name": "VietinBank"},
    {"bin": "970418", "code": "BIDV", "name": "BIDV"},
    {"bin": "970405", "code": "VBA", "name": "Agribank"},
    {"bin": "970407", "code": "TCB", "name": "Techcombank"},
    {"bin": "970422", "code": "MB", "name": "MB Bank"},
    {"bin": "970416", "code": "ACB", "name": "ACB"},
    {"bin": "970432", "code": "VPB", "name": "VPBank"},
    {"bin": "970423", "code": "TPB", "name": "TPBank"},
    {"bin": "970403", "code": "STB", "name": "Sacombank"},
    {"bin": "970441", "code": "VIB", "name": "VIB"},
    {"bin": "970443", "code": "SHB", "name": "SHB"},
    {"bin": "970437", "code": "HDB", "name": "HDBank"},
    {"bin": "970448", "code": "OCB", "name": "OCB"},
    {"bin": "970426", "code": "MSB", "name": "MSB"},
    {"bin": "970440", "code": "SEAB", "name": "SeABank"},
    {"bin": "970431", "code": "EIB", "name": "Eximbank"},
    {"bin": "970449", "code": "LPB", "name": "LPBank"},
    {"bin": "970428", "code": "NAB", "name": "Nam A Bank"},
    {"bin": "970412", "code": "PVCB", "name": "PVcomBank"},
]

upgrades = Table(
    "account_upgrade", accounts.central_md,
    Column("id", Integer, primary_key=True),
    Column("username", String(64), nullable=False),
    Column("plan_id", String(32), nullable=False),
    Column("plan_name", String(64), nullable=False),
    Column("amount", Integer, nullable=False, default=0),
    Column("content", String(128), nullable=False, default=""),
    Column("status", String(16), nullable=False, default="pending"),  # pending | approved | rejected | cancelled
    Column("created_at", DateTime, nullable=False),
    Column("decided_at", DateTime),
    Column("note", Text),
    Column("months", Integer),  # the term bought (plans.TERM_MONTHS); 0 / NULL = forever
)
_made: "weakref.WeakSet[Any]" = weakref.WeakSet()  # engines that already have the table


class BillingError(RuntimeError):
    """A request that cannot go through (no price, nothing set up…), in words for the user."""


def _engine():
    eng = accounts.central_engine()
    if eng not in _made:  # the table came after the first central stores: create it on first use
        upgrades.create(eng, checkfirst=True)
        have = {c["name"] for c in inspect(eng).get_columns("account_upgrade")}
        if "months" not in have:  # made by the first build of this feature (no terms yet)
            with eng.begin() as c:
                c.exec_driver_sql("ALTER TABLE account_upgrade ADD COLUMN months INTEGER")
        _made.add(eng)
    return eng


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── settings ────────────────────────────────────────────────────────────────

def normalize(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    bank_bin = re.sub(r"\D", "", str(raw.get("bank_bin") or ""))[:8]
    template = " ".join(str(raw.get("template") or "").split())[:80] or DEFAULT_TEMPLATE
    return {
        "bank_bin": bank_bin,
        "account_no": re.sub(r"[^0-9A-Za-z]", "", str(raw.get("account_no") or ""))[:19],
        "account_name": _ascii(str(raw.get("account_name") or "")).upper()[:50],
        "template": template,
        "note": str(raw.get("note") or "").strip()[:300],
    }


def load() -> dict[str, Any]:
    return normalize(accounts.get_setting(SETTING_KEY))


def save(raw: Any) -> dict[str, Any]:
    licensing.guard()
    value = normalize(raw)
    accounts.set_setting(SETTING_KEY, value)
    if licensing.store_licensed():  # the bank account customers pay to is signed: nobody can swap in their own
        licensing.sign_doc(SETTING_KEY, value)
    return value


def trusted() -> bool:
    """May customers be shown the bank account and the prices? Both signed by the admin (licensing.doc_trusted)."""
    return licensing.doc_trusted(SETTING_KEY) and licensing.doc_trusted(plans.SETTING_KEY)


UNTRUSTED = ("Bảng giá / thông tin chuyển khoản trên cơ sở dữ liệu không khớp chữ ký của người quản lý (có thể đã bị sửa) — "
             "đừng chuyển tiền, liên hệ người quản lý DFlow.")


def ready(settings: Optional[dict] = None) -> bool:
    s = settings or load()
    return bool(s["bank_bin"] and s["account_no"])


def bank_name(bin_: str) -> str:
    return next((b["name"] for b in BANKS if b["bin"] == bin_), f"Ngân hàng (BIN {bin_})" if bin_ else "")


# ── transfer text + VietQR ──────────────────────────────────────────────────

def _ascii(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^0-9A-Za-z .\-_]", " ", text).split())


def transfer_text(template: str, username: str, plan_name: str, term: str = "") -> str:
    """The transfer text: the template filled in, without accents (bank apps drop them), at most 50 characters."""
    text = ((template or DEFAULT_TEMPLATE).replace("{username}", username).replace("{plan}", plan_name)
            .replace("{term}", term))
    return _ascii(text)[:TEXT_MAX].strip()


def terms_of(plan_id: str) -> list[dict[str, int]]:
    """The terms a plan is sold for (part of the plan, plans.py)."""
    return next((p.get("terms") or [] for p in plans.load()["plans"] if p["id"] == plan_id), [])


def _tlv(tag: str, value: str) -> str:
    return f"{tag}{len(value):02d}{value}"


def crc16(data: str) -> str:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) — the EMVCo QR checksum."""
    crc = 0xFFFF
    for byte in data.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def vietqr_payload(bank_bin: str, account_no: str, amount: int, text: str) -> str:
    """A NAPAS VietQR string any Vietnamese bank app scans: transfer `amount` VND to the account, with `text`."""
    beneficiary = _tlv("00", bank_bin) + _tlv("01", account_no)
    merchant = _tlv("00", "A000000727") + _tlv("01", beneficiary) + _tlv("02", "QRIBFTTA")
    body = (_tlv("00", "01") + _tlv("01", "12" if amount else "11") + _tlv("38", merchant) + _tlv("53", "704")
            + (_tlv("54", str(int(amount))) if amount else "") + _tlv("58", "VN")
            + (_tlv("62", _tlv("08", text)) if text else "") + "6304")
    return body + crc16(body)


# ── what an account sees ────────────────────────────────────────────────────

def offer(user: dict) -> dict[str, Any]:
    """The plans an account can move to, with their terms + prices; its current plan; a pending request if any."""
    settings = load()
    data = plans.load()
    current = plans.plan_of(user)
    end = user.get("plan_expires")
    ok = trusted()
    return {
        "current": {"id": current["id"], "name": current["name"], "trial": current["id"] == plans.TRIAL_ID,
                    "expires_at": end.isoformat() if end else None},
        # the trial is never bought: only the plans after it are offered
        "plans": [{**p, "terms": p.get("terms") or [], "current": p["id"] == current["id"]}
                  for p in data["plans"] if p["id"] != plans.TRIAL_ID],
        "features": plans.shown_features(),
        "ready": ready(settings) and ok,
        "note": settings["note"] if ok else UNTRUSTED,
        "pending": pending_for(user["username"]),
    }


def _renewal_base(user: dict, plan_id: str) -> Optional[datetime]:
    """Buying more of the plan the account is on keeps the time it has left."""
    return user.get("plan_expires") if (user.get("plan") or "") == plan_id else None


def quote(user: dict, plan_id: str, months: int = 0) -> dict[str, Any]:
    """The QR and transfer details for moving to `plan_id` for `months` (0 = forever), and the end date that buys."""
    settings = load()
    plan = next((p for p in plans.load()["plans"] if p["id"] == plan_id), None)
    if plan is None or plan["id"] == plans.TRIAL_ID:
        raise BillingError("Không có gói này (có thể vừa bị đổi) — tải lại trang.")
    same = plan["id"] == plans.plan_of(user)["id"]
    if same and not user.get("plan_expires"):
        raise BillingError(f"Bạn đang dùng gói {plan['name']} vĩnh viễn rồi.")
    if not ready(settings):
        raise BillingError("Người quản lý chưa cài đặt tài khoản nhận tiền — liên hệ người quản lý DFlow.")
    if not trusted():
        raise BillingError(UNTRUSTED)
    terms = plan.get("terms") or []
    if not terms:
        raise BillingError(f"Gói {plan['name']} chưa có giá — liên hệ người quản lý DFlow.")
    term = next((t for t in terms if t["months"] == (months or 0)), None)
    if term is None:
        raise BillingError(f"Gói {plan['name']} không bán thời hạn {plans.term_label(months)} — chọn thời hạn khác.")
    label = plans.term_label(term["months"])
    text = transfer_text(settings["template"], user["username"], plan["name"], label)
    end = plans.plan_end(plan["id"], term["months"], base=_renewal_base(user, plan["id"]))
    return {
        "plan_id": plan["id"], "plan_name": plan["name"], "months": term["months"], "term": label,
        "amount": term["price"], "list_price": term["list_price"], "renew": same,
        "ends_at": end.isoformat() if end else None, "content": text,
        "bank_name": bank_name(settings["bank_bin"]), "account_no": settings["account_no"],
        "account_name": settings["account_name"], "note": settings["note"],
        "qr": vietqr_payload(settings["bank_bin"], settings["account_no"], term["price"], text),
    }


def _row(r: Any) -> dict[str, Any]:
    months = int(getattr(r, "months", None) or 0)
    return {"id": r.id, "username": r.username, "plan_id": r.plan_id, "plan_name": r.plan_name, "amount": r.amount,
            "months": months, "term": plans.term_label(months), "content": r.content, "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "decided_at": r.decided_at.isoformat() if r.decided_at else None}


def _via_api() -> bool:
    return accounts.via_api()


def _api(username: str, method: str, path: str, body: Optional[dict] = None) -> dict:
    from flowboard import cloud_api

    try:
        return cloud_api.account_call(username, method, path, body=body)
    except cloud_api.ApiError as exc:
        raise BillingError(exc.detail) from exc


def pending_for(username: str) -> Optional[dict[str, Any]]:
    if _via_api():
        return _api(username, "GET", "/api/app/upgrade").get("pending")
    with _engine().connect() as c:
        r = c.execute(select(upgrades).where(upgrades.c.username == username, upgrades.c.status == "pending")
                      .order_by(upgrades.c.id.desc())).first()
    return _row(r) if r else None


def file_request(user: dict, plan_id: str, months: int = 0) -> dict[str, Any]:
    """"Tôi đã chuyển khoản": one pending request per account (a newer one replaces it)."""
    q = quote(user, plan_id, months)
    if _via_api():
        return _api(user["username"], "POST", "/api/app/upgrade/request", {"plan_id": q["plan_id"], "months": q["months"]}).get("request") or {}
    with _engine().begin() as c:
        c.execute(upgrades.update().where(upgrades.c.username == user["username"], upgrades.c.status == "pending")
                  .values(status="cancelled", decided_at=_now()))
        c.execute(upgrades.insert().values(username=user["username"], plan_id=q["plan_id"], plan_name=q["plan_name"],
                                           amount=q["amount"], months=q["months"], content=q["content"],
                                           status="pending", created_at=_now()))
    return pending_for(user["username"]) or {}


def cancel_request(username: str) -> None:
    if _via_api():
        _api(username, "POST", "/api/app/upgrade/cancel")
        return
    with _engine().begin() as c:
        c.execute(upgrades.update().where(upgrades.c.username == username, upgrades.c.status == "pending")
                  .values(status="cancelled", decided_at=_now()))


def list_requests(limit: int = 100, username: Optional[str] = None) -> list[dict[str, Any]]:
    if _via_api():
        return (_api(username, "GET", "/api/app/upgrade").get("requests") or [])[:limit] if username else []
    q = select(upgrades).order_by(upgrades.c.id.desc()).limit(limit)
    if username:
        q = q.where(upgrades.c.username == username)
    with _engine().connect() as c:
        rows = c.execute(q).all()
    return [_row(r) for r in rows]


def decide(request_id: int, approve: bool) -> dict[str, Any]:
    """The admin's answer. Approving moves the account to the plan it paid for, until the end of the term bought."""
    with _engine().begin() as c:
        r = c.execute(select(upgrades).where(upgrades.c.id == request_id)).first()
        if r is None:
            raise BillingError("Không có yêu cầu này.")
        if r.status != "pending":
            raise BillingError("Yêu cầu này đã xử lý rồi.")
        if approve:
            plan = next((p for p in plans.load()["plans"] if p["id"] == r.plan_id), None)
            if plan is None:
                raise BillingError(f"Gói {r.plan_name} không còn — đổi gói cho tài khoản bằng tay ở bảng tài khoản.")
            if accounts.get_user(r.username) is None:
                raise BillingError("Tài khoản này không còn.")
            # the request row can be edited by hand (a longer term for the same money): the amount must be today's price
            months = int(getattr(r, "months", None) or 0)
            price = next((t["price"] for t in plan.get("terms") or [] if t["months"] == months), None)
            if price is None or int(r.amount) != int(price):
                want = f"{price:,}đ".replace(",", ".") if price else "không bán"
                raise BillingError(f"Số tiền của yêu cầu ({int(r.amount):,}đ) không khớp giá hiện tại của gói {plan['name']} · "
                                   f"{plans.term_label(months)} ({want}) — có thể yêu cầu đã bị sửa hoặc giá vừa đổi. Kiểm tra sao kê "
                                   "rồi gán gói bằng tay ở bảng tài khoản.".replace(",", "."))
        c.execute(upgrades.update().where(upgrades.c.id == request_id)
                  .values(status="approved" if approve else "rejected", decided_at=_now()))
    if approve:
        user = accounts.get_user(r.username) or {}
        months = int(getattr(r, "months", None) or 0)
        accounts.set_plan(r.username, r.plan_id, plans.plan_end(r.plan_id, months, base=_renewal_base(user, r.plan_id)))
    with _engine().connect() as c:
        return _row(c.execute(select(upgrades).where(upgrades.c.id == request_id)).first())
