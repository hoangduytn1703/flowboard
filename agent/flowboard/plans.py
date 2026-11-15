"""Service plans ("gói"): which features an account may use.

The admin (accounts.ROLE_ADMIN) edits the plans on "👥 Quản lý tài khoản": add / rename / delete plans, tick
the features each one has, pick the default plan for new accounts, and give every account a plan
(``account_user.plan`` holds the plan id). The admin itself always has everything.

Plans live in the central store (``account_setting`` key ``plans``) so every machine logged in to the same
cloud sees the same plans. Gating happens twice: the UI hides what the plan lacks (``/api/account/me``
returns ``features``), and the login middleware refuses the matching API routes (:func:`feature_for`).
Core clip making (clips, products, models, prompts, history, settings) is never gated.

The **trial** plan ("Dùng thử", id ``trial``) is built in: always first, cannot be deleted or bought, and is the
plan every new account starts on. Its only setting besides the features is how long it lasts (3 / 7 / 14 / 30 days);
an account whose trial ended cannot log in (``accounts.expired``) until the admin extends it or moves it to a plan.

Every paid plan lists the **terms** it is sold for (``terms``: ``TERM_MONTHS`` = 1 / 3 / 6 months, 1 / 2 years, or 0 =
forever), each with a price and an optional list price shown struck through — e.g. VIP 1 month 49k, 1 year 490k, forever
980k. An account on a paid plan has an end date (``plan_expires``, from the term it bought; the admin can change it)
unless it bought it forever, and a paid plan that ran out locks the account the same way an ended trial does.
"""
from __future__ import annotations

import calendar
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

#: The features a plan can switch on or off — keys are what the UI and the routes check.
FEATURES: list[dict[str, str]] = [
    {"key": "auto_clip", "icon": "⚡", "label": "Tạo video tự động",
     "desc": "Nút ⚡ Tạo video tự động trong clip, chạy hàng loạt nhiều clip một lần"},
    {"key": "dub", "icon": "🎙", "label": "Lồng tiếng video",
     "desc": "Lồng tiếng / chèn phụ đề video từ link, thư viện link, cắt thành nhiều clip"},
    {"key": "cut", "icon": "✂️", "label": "Cắt video",
     "desc": "Dán link / file → AI cắt thành nhiều video ngắn theo yêu cầu, chỉnh từng video hoặc cả loạt"},
    {"key": "grab", "icon": "📡", "label": "Cào video kênh",
     "desc": "Lấy danh sách video của kênh YouTube / TikTok (lượt xem, ngày đăng), AI chọn theo yêu cầu, tải về để cắt / lồng tiếng"},
    {"key": "capcut", "icon": "🎞", "label": "Edit auto CapCut",
     "desc": "Tạo dự án CapCut có phụ đề, chữ nhấn, hiệu ứng"},
    {"key": "clean", "icon": "🧽", "label": "Xoá chữ / logo",
     "desc": "Xoá logo, watermark, phụ đề cứng khỏi video có sẵn"},
    {"key": "posts", "icon": "✍️", "label": "Bài viết Facebook",
     "desc": "AI viết bài, loạt truyện, kênh của tôi, gói nội dung 1 chạm"},
    {"key": "facebook", "icon": "📅", "label": "Đăng & lên lịch Facebook",
     "desc": "Lịch đăng, đăng ngay / tự đăng lên Page (bài, Reel, tin), số liệu Facebook"},
    {"key": "autopilot", "icon": "🤖", "label": "Tự động đăng theo lịch",
     "desc": "Tự soạn bài và tự đăng lên Page theo giờ cố định"},
    {"key": "swipes", "icon": "🔥", "label": "Mẫu đang hot",
     "desc": "Phân tích bài / video đang hot rồi viết theo cấu trúc đó"},
    {"key": "assistant", "icon": "💬", "label": "Trợ lý AI",
     "desc": "Nút chat góc dưới phải: gõ một câu, trợ lý làm giúp"},
]
FEATURE_KEYS = [f["key"] for f in FEATURES]
#: Features taken out of sight for now: no menu, not listed in the plans table or the upgrade screen. Their keys
#: stay valid (signed plans may carry them) and their routes keep working. "capcut": to come back inside the video
#: editor instead of as a page of its own.
#: "assistant" (15/11): parked until it is tested through again — the chat button is gone for every account.
HIDDEN_FEATURES = {"capcut", "assistant"}


def shown_features() -> list[dict[str, str]]:
    return [f for f in FEATURES if f["key"] not in HIDDEN_FEATURES]

TRIAL_ID = "trial"
TRIAL_DAYS = [3, 7, 14, 30]
DEFAULT_TRIAL_DAYS = 7

#: First start (no plans saved yet). Ids never change; names do. The trial is always first.
DEFAULT_PLANS: list[dict[str, Any]] = [
    {"id": TRIAL_ID, "name": "Dùng thử", "features": list(FEATURE_KEYS), "days": DEFAULT_TRIAL_DAYS},
    {"id": "vip", "name": "VIP", "features": [k for k in FEATURE_KEYS if k != "dub"]},
    {"id": "pro", "name": "Pro", "features": [k for k in FEATURE_KEYS if k not in ("facebook", "autopilot")]},
    {"id": "premium", "name": "Premium", "features": list(FEATURE_KEYS)},
]
#: New accounts start on the trial (accounts made before it existed keep the plan they had).
DEFAULT_PLAN_ID = TRIAL_ID
SETTING_KEY = "plans"
MAX_PLANS = 12
NAME_MAX = 40

# Route → feature. First match wins; ``None`` = not gated (a shared helper other pages call too).
# A tuple of features = any of them is enough. Methods limit a rule to those verbs.
_RULES: list[tuple[re.Pattern[str], Optional[frozenset[str]], Any]] = []


def _rule(pattern: str, features: Any, methods: Optional[str] = None) -> None:
    feats = None if features is None else (features if isinstance(features, tuple) else (features,))
    _RULES.append((re.compile(pattern), frozenset(methods.split()) if methods else None, feats))


_rule(r"^/api/dub/status$", None)                       # Bước 4 asks whether Remotion runs here
_rule(r"^/api/dub/addon(/|$)", None)                    # machine setup: dubbing, cutting by the words, VieNeu voices
_rule(r"^/api/dub/remotion-addon(/|$)", None)           # machine setup: the Remotion subtitle engine
# "✂️ Cắt video" edits its parts in the dubbing editor: the editor's own routes serve both tools
_rule(r"^/api/dub/jobs/[0-9a-f]+(/(render|subtitles|highlights/pick|names|stop|nosub|voice|bgm|filmstrip\.jpg|wave\.png))?$", ("dub", "cut"))
_rule(r"^/api/dub/(mascot|background|decor)(/|$)", ("dub", "cut"))
_rule(r"^/api/dub(/|$)", "dub")
_rule(r"^/api/cut/clips$", ("cut", "dub"))               # the dubbing page picks videos from "Clip của tôi"
_rule(r"^/api/cut(/|$)", "cut")
_rule(r"^/api/edit(/|$)", ("dub", "cut"))                 # "🎞 Chỉnh sửa video": whoever can dub or cut can edit
_rule(r"^/api/grab/media$", ("grab", "cut", "dub"))      # the cut / dubbing pages take the videos picked there
_rule(r"^/api/grab/dub(/|$)", "dub")                     # "🎙 Lồng tiếng ngay" on the grab list starts dub jobs
_rule(r"^/api/grab(/|$)", "grab")
_rule(r"^/api/capcut(/|$)", "capcut")
_rule(r"^/api/clean/[^/]+/detect$", ("clean", "dub", "cut"))   # the editor's "find the old captions" (OCR)
_rule(r"^/api/clean(/|$)", "clean")
_rule(r"^/api/posts/clip-hooks$", None)                 # Bước 2 "5 câu mở đầu khác" of a clip
_rule(r"^/api/posts(/|$)", ("posts", "facebook"), "GET")  # Lịch đăng lists the saved posts too
_rule(r"^/api/posts(/|$)", "posts")
_rule(r"^/api/bundles(/|$)", "posts")
_rule(r"^/api/swipes(/|$)", "swipes")
_rule(r"^/api/channels/[^/]+/(brainstorm|review)$", "posts")
_rule(r"^/api/channels/(facebook/inspect|[^/]+/facebook)$", "facebook")
_rule(r"^/api/schedule(/|$)", "facebook")
_rule(r"^/api/autopilot(/|$)", "autopilot")
_rule(r"^/api/assistant(/|$)", "assistant")


def feature_for(method: str, path: str) -> Optional[tuple[str, ...]]:
    """The feature(s) a request needs (any one of them), None when the route is not gated."""
    for pattern, methods, feats in _RULES:
        if methods is not None and method.upper() not in methods:
            continue
        if pattern.search(path):
            return feats
    return None


def feature_label(key: str) -> str:
    return next((f"{f['icon']} {f['label']}" for f in FEATURES if f["key"] == key), key)


# ── stored plans ────────────────────────────────────────────────────────────

_cache: dict[str, Any] = {"at": 0.0, "value": None}
_lock = threading.Lock()
CACHE_S = 30.0


def _slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] or "goi"
    pid, n = base, 2
    while pid in taken:
        pid, n = f"{base}-{n}", n + 1
    return pid


PRICE_MAX = 1_000_000_000


def _money(value: Any) -> int:
    try:
        return int(float(str(value).replace(".", "").replace(",", "").replace("đ", "").strip() or 0))
    except ValueError:
        return 0


def clean_terms(items: Any) -> list[dict[str, int]]:
    """[{months, price, list_price}]: known lengths only, one of each, priced, the list price only when it is higher than
    the price, shortest first and "forever" last."""
    seen: set[int] = set()
    out: list[dict[str, int]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            months = int(item.get("months") or 0)
        except (TypeError, ValueError):
            continue
        price = _money(item.get("price"))
        if months not in TERM_MONTHS or months in seen or not 0 < price <= PRICE_MAX:
            continue
        listed = _money(item.get("list_price"))
        seen.add(months)
        out.append({"months": months, "price": price, "list_price": listed if price < listed <= PRICE_MAX else 0})
    out.sort(key=lambda t: t["months"] or 10_000)
    return out


def normalize_terms(raw: Any) -> dict[str, list[dict[str, int]]]:
    """{plan_id: terms} → cleaned, plans with no term left out."""
    out = {str(pid): clean_terms(items) for pid, items in (raw.items() if isinstance(raw, dict) else [])}
    return {pid: terms for pid, terms in out.items() if terms}


def normalize(raw: Any) -> dict[str, Any]:
    """{plans: [{id, name, features, terms}], default} with unknown features dropped, unique ids / names, the trial
    first (added when missing, ``days`` one of TRIAL_DAYS, never sold so no terms) and the trial as the default."""
    items = raw.get("plans") if isinstance(raw, dict) else None
    items = items if isinstance(items, list) and items else [dict(p, features=list(p["features"])) for p in DEFAULT_PLANS]
    trial_in = next((i for i in items if isinstance(i, dict) and str(i.get("id") or "") == TRIAL_ID), None)
    trial_src = trial_in or DEFAULT_PLANS[0]
    days = trial_src.get("days")
    days = days if isinstance(days, int) and days in TRIAL_DAYS else DEFAULT_TRIAL_DAYS
    trial_name = " ".join(str(trial_src.get("name") or "").split())[:NAME_MAX] or DEFAULT_PLANS[0]["name"]
    feats = trial_src.get("features")
    plans: list[dict[str, Any]] = [{"id": TRIAL_ID, "name": trial_name, "features": [k for k in FEATURE_KEYS if isinstance(feats, list) and k in feats],
                                    "days": days}]
    ids: set[str] = {TRIAL_ID}
    names: set[str] = {trial_name.lower()}
    for item in items:
        if isinstance(item, dict) and str(item.get("id") or "") == TRIAL_ID:
            continue
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name") or "").split())[:NAME_MAX]
        if not name or name.lower() in names:
            continue
        pid = str(item.get("id") or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", pid) or pid in ids or pid == "admin":
            pid = _slug(name, ids | {"admin", TRIAL_ID})
        feats = item.get("features")
        features = [k for k in FEATURE_KEYS if isinstance(feats, list) and k in feats]
        plans.append({"id": pid, "name": name, "features": features, "terms": clean_terms(item.get("terms"))})
        ids.add(pid)
        names.add(name.lower())
        if len(plans) >= MAX_PLANS:
            break
    return {"plans": plans, "default": TRIAL_ID}


def trial_days() -> int:
    return int(load()["plans"][0].get("days") or DEFAULT_TRIAL_DAYS)


def trial_end(start: Optional[datetime] = None) -> datetime:
    """When a trial started now (naive UTC, like the central store) ends."""
    start = start or datetime.now(timezone.utc).replace(tzinfo=None)
    return start + timedelta(days=trial_days())


def expires_for(plan_id: str) -> Optional[datetime]:
    """The end date an account gets when moved to ``plan_id`` with no term picked: the trial runs out, paid plans do not."""
    return trial_end() if plan_id == TRIAL_ID else None


#: Terms a paid plan can be sold / given for, in months; 0 = forever ("vĩnh viễn").
TERM_MONTHS = [1, 3, 6, 12, 24, 0]


def term_label(months: Optional[int]) -> str:
    if not months:
        return "Vĩnh viễn"
    return f"{months // 12} năm" if months % 12 == 0 else f"{months} tháng"


def add_months(start: datetime, months: int) -> datetime:
    """Same day `months` later (the 31st becomes the last day of a shorter month)."""
    m = start.month - 1 + months
    year, month = start.year + m // 12, m % 12 + 1
    return start.replace(year=year, month=month, day=min(start.day, calendar.monthrange(year, month)[1]))


def plan_end(plan_id: str, months: Optional[int] = None, days: Optional[int] = None,
             base: Optional[datetime] = None) -> Optional[datetime]:
    """When an account moved to `plan_id` for this term runs out. `base` = the current end when renewing the same plan
    (time left is kept); a past or missing base counts from now. Paid plan with no months (0 / None) = forever."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    start = base if base and base > now else now
    if plan_id == TRIAL_ID:
        return start + timedelta(days=days or trial_days())
    if not months:
        return None
    return add_months(start, months)


def load(fresh: bool = False) -> dict[str, Any]:
    """The plans (saved once with the defaults on first use)."""
    from flowboard import accounts

    with _lock:
        if not fresh and _cache["value"] is not None and time.time() - _cache["at"] < CACHE_S:
            return _cache["value"]
    raw = accounts.get_setting(SETTING_KEY)
    raw = raw if isinstance(raw, dict) else None
    if raw is not None and not any(isinstance(p, dict) and p.get("id") == TRIAL_ID for p in raw.get("plans") or []):
        # plans saved before the trial existed: accounts "on the default" keep the plan they had (not the new trial)
        old_default = raw.get("default")
        if old_default and any(isinstance(p, dict) and p.get("id") == old_default for p in raw.get("plans") or []):
            accounts.fill_null_plans(old_default)
    elif raw is None:
        accounts.fill_null_plans("premium")  # accounts made before plans existed kept every feature
    if raw is not None and not any(isinstance(p, dict) and "terms" in p for p in raw.get("plans") or []):
        # prices were first kept with the bank settings (one price per plan, then terms): bring them into the plans
        old = accounts.get_setting("billing")
        old = old if isinstance(old, dict) else {}
        moved = normalize_terms(old["terms"]) if "terms" in old else normalize_terms(
            {pid: [{"months": 0, "price": v}] for pid, v in (old.get("prices") or {}).items()} if isinstance(old.get("prices"), dict) else {})
        raw = {**raw, "plans": [dict(p, terms=moved.get(str(p.get("id")), [])) if isinstance(p, dict) else p for p in raw.get("plans") or []]}
    value = normalize(raw or {})
    from flowboard import licensing

    if raw != value and not licensing.store_licensed():
        # a signed store is never rewritten here: what is stored is what the admin signed (licensing.doc_state)
        accounts.set_setting(SETTING_KEY, value)
    with _lock:
        _cache.update(at=time.time(), value=value)
    return value


def save(raw: Any) -> dict[str, Any]:
    """Replace every plan. Accounts on a plan that disappeared move to the default plan."""
    from flowboard import accounts

    from flowboard import licensing

    licensing.guard()
    value = normalize(raw)
    accounts.set_setting(SETTING_KEY, value)
    with _lock:
        _cache.update(at=time.time(), value=value)
    if licensing.store_licensed():
        licensing.sign_doc(SETTING_KEY, value)
        licensing.resign_after_plans(value)  # renamed / changed / deleted plans → new licences
    else:
        accounts.reassign_missing_plans({p["id"] for p in value["plans"]}, TRIAL_ID, trial_end())
    return value


def forget() -> None:
    """Tests: drop the cached plans (the central store changed)."""
    with _lock:
        _cache.update(at=0.0, value=None)


def plan_of(user: Optional[dict]) -> dict[str, Any]:
    """The plan an account is on (its own, else the default). The admin is on no plan: everything."""
    from flowboard import accounts

    if accounts.is_admin(user):
        return {"id": "admin", "name": "Toàn quyền", "features": list(FEATURE_KEYS)}
    if user is not None and "features" in user:  # a signed store: the licence lists the features (licensing.apply)
        if user.get("unlicensed"):
            return {"id": "", "name": "Chưa được cấp quyền", "features": []}
        return {"id": user.get("plan") or "", "name": user.get("plan_name") or (user.get("plan") or ""),
                "features": [k for k in FEATURE_KEYS if k in user["features"]]}
    data = load()
    pid = (user or {}).get("plan") or data["default"]
    plan = next((p for p in data["plans"] if p["id"] == pid), None)
    if plan is None:
        plan = next(p for p in data["plans"] if p["id"] == data["default"])
    return plan


def features_of(user: Optional[dict]) -> list[str]:
    from flowboard import accounts

    if not accounts.auth_enabled():
        return list(FEATURE_KEYS)
    return list(plan_of(user)["features"])


def allows(user: Optional[dict], feature: str) -> bool:
    return feature in features_of(user)


def active_allows(feature: str) -> bool:
    """For background loops (auto-posting): may the account the agent serves now use this?"""
    from flowboard import accounts

    if not accounts.auth_enabled():
        return True
    user = accounts.active_user()
    if user is None:
        return False
    full = accounts.get_user(user["username"]) or user  # the cached copy may predate a plan change
    from flowboard import cloud_api

    cloud_api.maybe_refresh(full)  # an app left in the tray: the loops keep asking the website too (lock, plan change)
    return allows(full, feature)


def refusal(user: Optional[dict], feats: tuple[str, ...]) -> str:
    plan = plan_of(user)
    names = " / ".join(feature_label(k) for k in feats)
    return f"Gói {plan['name']} của bạn chưa có tính năng {names}. Liên hệ người quản lý DFlow để nâng gói."
