"""🤖 Trợ lý AI (Phase A): the person types what they want in a chat, the LLM
answers and, when it is work the assistant can do, plans one or more **steps
that run in the background** — the chat (and the "việc đang chạy" badge)
follows them; leaving the page or restarting the agent does not lose them.

Skills (one plan may chain several, a step can use what the step before made):
- ``create_model``  draw an AI model with Flow → "Người mẫu đã lưu"
- ``add_product``   read a product link (Shopee / TikTok / a shop) → "Sản phẩm" (+ its photo on Flow)
- ``write_post``    write 1–5 Facebook posts for a channel (a product optional) — or the next episodes of a
                    story series, written like its last episode — with their AI pictures, saved in "Bài đã lưu"
- ``schedule_post`` put the posts just written (or a saved one) on "Lịch đăng", auto-published on the Page
- ``create_clip``   a new ad clip for a product with its script written for it (making the pictures and
                    videos in the background is milestone A1)
- ``auto_post``     a fixed posting schedule for a Page ("🤖 Tự động đăng", services/autopilot): on given days / times a
                    post is written ahead, pictured and auto-posted — nobody has to do anything (waits for a go-ahead)

The LLM gets the catalog (channels, series, products, clip kinds, models — with
ids) so names typed with typos or without accents still land on the right
thing ("chú ta hay tò mò" → "Chúng ta hay tò mò"); the plan is checked here and
names are matched again on our side. A plan that posts publicly by itself (an
auto-publish slot) waits for "✅ Làm luôn" (or "ok") before anything runs.

A real person's face is never copied: asked for someone "giống <người nổi
tiếng>", the assistant makes an original person in that general style and says
why (no real faces in ads; Flow drops videos of celebrity-like faces).
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, Optional

from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import AppSetting, AssistantMessage, AssistantTask, Channel, Post, Product, Reference, Request
from flowboard.services.llm import run_llm
from flowboard.services.llm.base import LLMError
from flowboard.timestamps import utc_iso

logger = logging.getLogger(__name__)

HISTORY_TURNS = 12
MAX_MESSAGE = 2000
IMAGE_TIMEOUT_S = 4 * 60
POLL_S = 2.5
MAX_POSTS = 5
VN = timezone(timedelta(hours=7))

GENDERS = {"female": "female", "male": "male"}
COUNTRIES = {"vn": "Vietnamese", "kr": "Korean", "jp": "Japanese", "cn": "Chinese", "th": "Thai", "us": "American", "fr": "French"}
COUNTRY_VI = {"vn": "Việt Nam", "kr": "Hàn Quốc", "jp": "Nhật Bản", "cn": "Trung Quốc", "th": "Thái Lan", "us": "Mỹ", "fr": "Pháp"}
POST_KINDS = ("discussion", "review", "story", "tips", "compare", "sale", "minigame")
# Same pool as frontend lib/characterPrompt.ts: two small traits of its own keep a face from matching anyone famous.
OWN_TRAITS = (
    "a small beauty mark on one cheek", "slightly uneven natural eyebrows", "a soft rounded jawline",
    "a few light freckles across the nose", "a slightly wider nose bridge", "a small dimple on one side when smiling",
    "naturally fuller cheeks", "a faint mole above the lip", "slightly hooded eyes", "a gently asymmetrical smile",
)
TOOLS = ("create_model", "add_product", "write_post", "schedule_post", "create_clip", "auto_post", "cut_video", "grab_channel")

_SYSTEM = """You are "Trợ lý DFlow", the AI assistant inside DFlow — a tool that makes ad clips, Facebook posts and posting
schedules for a Vietnamese TikTok Shop / Shopee affiliate seller. Answer in natural, short, friendly Vietnamese (xưng "mình",
gọi "bạn"). You turn what the seller asks into a PLAN of actions that DFlow runs in the background.

TOOLS (args are JSON; use ids from the CATALOG — names there may be typed with typos or without accents by the seller:
match them to the closest catalog entry, e.g. "chú ta hay tò mò" = "Chúng ta hay tò mò"):
1. create_model {name, gender: "female"|"male", country: "vn"|"kr"|"jp"|"cn"|"th"|"us"|"fr", look, summary}
   draw an AI model portrait (~30 s) and save it in "Người mẫu đã lưu". look = ENGLISH 25-70 words (age range, general face
   features, hair, makeup, outfit, expression, light, backdrop); summary = one VIETNAMESE line. Invent a Vietnamese-style
   first name when none is given.
2. add_product {url} — read a product page link (Shopee, TikTok Shop, a shop's site) and save it in "Sản phẩm" with its photo.
   Later steps can use it as product_id "previous".
3. write_post {channel_id, product_id?, series?, kind?, topic?, images?, count?}
   write Facebook posts and save them in "Bài đã lưu". channel_id is REQUIRED (a post is always for a page: if the catalog has
   one channel use it, else ask which). series = the EXACT catalog series name of THAT channel to write its next episode(s)
   (the series' own settings are reused — leave kind / images out unless the seller asks), or a new series name to start one.
   kind ∈ discussion|review|story|tips|compare|sale|minigame (default discussion; for a series leave it out). topic = the idea
   in Vietnamese (optional). images 0-4 (AI pictures, default 0, a series keeps its own). count 1-5 posts (default 1).
   product_id = a catalog product id, or "previous" (from add_product).
4. schedule_post {post: "previous" | <post id>, at: "YYYY-MM-DDTHH:MM" (VIETNAM local time, absolute), auto?: bool,
   format?: "post"|"reel", story?: bool} — put the post(s) on "Lịch đăng". story = also put it on the Page's Story
   ("thêm vào tin", "đăng tin", "lên story": true; default false) — its video, picture, or for words only a picture of the opening. "previous" = the posts written in the step before (several →
   one per day from `at`). auto = publish by itself on the channel's Facebook Page (only when the catalog says the channel is
   connected; default true then, false otherwise). Work out `at` from NOW: "12h hôm nay" = today 12:00, "tối nay" = today
   20:00, "sáng mai" = tomorrow 08:00. If that time has already passed, ask instead of planning.
5. create_clip {product_id, template_id?, channel_id?, voiceless?: bool} — a new ad clip for a product (catalog id or
   "previous") with its script written for the product, filmed like a real buyer on a phone. template_id from the catalog's
   clip kinds (pick one fitting the product's category). voiceless = true when the seller wants no voice / no talking /
   only the product being worn or used ("không lời", "không cần lời thoại", "chỉ quay mặc thử", "kiểu ASMR"): no voice-over,
   no subtitles, the real sounds of the clip.
   Making its pictures and videos in the background is coming soon: say the seller opens the clip and presses
   "⚡ Tạo video tự động".
6. auto_post {channel_id, days: [0-6, 0 = Monday … 6 = Sunday], times: ["HH:MM" Vietnam time], kind?, topic?, series?,
   images?, product_id?, ai?: "claude"|"gemini", story?: bool} — a FIXED posting schedule ("🤖 Tự động đăng"): from now on, on
   those days at those times DFlow writes a post by itself a few hours ahead (with its AI pictures) and posts it on the
   channel's Facebook Page, no one has to do anything. Use it for "tự động đăng / đăng đều / mỗi ngày / T2-T6 … giờ … cho kênh …".
   Only for a channel the catalog says is connected (fb_connected) — else say it must be connected on the Kênh page first.
   "mỗi ngày" = all 7 days, "ngày thường" / "T2-T6" = [0,1,2,3,4], "cuối tuần" = [5,6]. series = a catalog series of that
   channel (each slot = its next episode) or a new name. images default 1. ai default "claude" (the seller's Claude CLI).
7. cut_video {urls: [video links], prompt?, how?: "ai"|"prompt"|"even", min_s?, max_s?, max_parts?, channel_id?} — "✂️ Cắt
   video": download long videos (TikTok / Douyin / YouTube / Facebook / Instagram / X, up to 10 links) and cut each into
   short videos, NO dubbing. prompt = what to keep in Vietnamese ("mỗi đoạn một mẹo", "những đoạn hài nhất") → how "prompt";
   no request → how "ai" (the AI picks the moments worth a short video); "chia đều" → how "even". min_s / max_s = seconds of
   one short video (default 30 / 60; "khoảng 1 phút" = 45 / 75); max_parts = at most that many per video. Every part lands
   in "Clip của tôi" and can be edited (subtitles, format, blur…) on the "✂️ Cắt video" page; dubbing is a separate step.
8. grab_channel {urls: [channel links], tags?: [labels], limit?: 30|60|100|200} — "📡 Cào video kênh": keep source
   CHANNELS (a YouTube channel "youtube.com/@name" or playlist, a TikTok account "tiktok.com/@name", a Douyin account
   "douyin.com/user/…", a Bilibili space "space.bilibili.com/<number>"; not single videos, not Facebook / Instagram —
   Douyin and Bilibili are read through the seller's own Chrome, logged in there) and list their newest videos with
   views, likes, length and date — nothing is downloaded
   yet: the seller then filters / lets the AI pick on that page, downloads the ones wanted and sends them to cutting or
   dubbing. Use it for "cào / quét / lấy video của kênh …", "theo dõi kênh …". limit = how many of the newest (default 60).

Chain steps in order in "actions" (e.g. write_post then schedule_post with post "previous"; add_product then write_post
with product_id "previous"). Ask back (actions []) only when something essential is missing or ambiguous (which channel,
which product, a time already passed). "Tập N" of a series: write the series' next episode (DFlow numbers it).

OFF-TOPIC: you only help with work in DFlow. For anything else (math, chit-chat, general knowledge, news, coding, homework,
poems, advice…) do NOT answer or solve it — reply with ONE short sentence that you only help with DFlow work; actions [].

REAL PEOPLE: never copy a real person's face. Asked for a model that looks like a real or famous person (celebrity, KOL,
singer, actress — e.g. "giống Ngọc Trinh"), make an ORIGINAL person sharing only the general style (body type, hair,
makeup, fashion, vibe) and say in one short sentence why: DFlow không dùng gương mặt người thật, và Flow chặn video có mặt
giống người nổi tiếng. Never put the real person's name or words like lookalike / resembling / celebrity / idol / famous
in args.

Output ONLY one JSON object, no prose, no code fences:
{"reply": str, "actions": [{"tool": str, "args": {...}}, ...]}
"reply" = 1-3 short sentences: what you are going to do (name the channel / series / time you understood), or your question."""


class AssistantError(RuntimeError):
    """Said to the person in front of the screen."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── what the pages read ─────────────────────────────────────────────────────

def _msg_row(m: AssistantMessage) -> dict[str, Any]:
    return {"id": m.id, "role": m.role, "text": m.text, "data": m.data or {}, "task_id": m.task_id,
            "at": utc_iso(m.created_at)}


def _task_row(t: AssistantTask) -> dict[str, Any]:
    st = t.state or {}
    return {"id": t.id, "kind": t.kind, "status": t.status, "title": t.title, "step": st.get("step") or "",
            "media_id": st.get("media_id"), "reference_id": st.get("reference_id"), "error": t.error,
            "link": st.get("link") or "/today", "started_at": utc_iso(t.created_at), "updated_at": utc_iso(t.updated_at)}


def state(limit: int = 120) -> dict[str, Any]:
    """The chat so far and the tasks it started (running ones carry on in the background)."""
    resume()
    with get_session() as s:
        msgs = s.exec(select(AssistantMessage).order_by(AssistantMessage.id.desc()).limit(limit)).all()
        task_ids = {m.task_id for m in msgs if m.task_id}
        open_ = s.exec(select(AssistantTask).where(AssistantTask.status.in_(("running", "pending")))).all()  # type: ignore[union-attr]
        task_ids |= {t.id for t in open_}
        tasks = s.exec(select(AssistantTask).where(AssistantTask.id.in_(task_ids))).all() if task_ids else []  # type: ignore[union-attr]
    return {"messages": [_msg_row(m) for m in reversed(msgs)], "tasks": [_task_row(t) for t in tasks]}


def running_tasks() -> list[dict[str, Any]]:
    with get_session() as s:
        return [_task_row(t) for t in s.exec(select(AssistantTask).where(AssistantTask.status == "running")).all()]


def task_outcome(task_id: int) -> Optional[dict[str, Any]]:
    with get_session() as s:
        t = s.get(AssistantTask, task_id)
        return _task_row(t) if t else None


def clear() -> int:
    """Forget the conversation (tasks and what they made stay; plans still waiting are dropped)."""
    with get_session() as s:
        rows = s.exec(select(AssistantMessage)).all()
        for r in rows:
            s.delete(r)
        for t in s.exec(select(AssistantTask).where(AssistantTask.status == "pending")).all():
            t.status, t.error = "canceled", "Đã xoá cuộc trò chuyện"
            s.add(t)
        s.commit()
    return len(rows)


def _add_message(role: str, text: str, *, data: Optional[dict] = None, task_id: Optional[int] = None) -> dict[str, Any]:
    with get_session() as s:
        m = AssistantMessage(role=role, text=text[:MAX_MESSAGE * 2], data=data or None, task_id=task_id)
        s.add(m)
        s.commit()
        s.refresh(m)
        return _msg_row(m)


# ── off-topic gate: no LLM call (no tokens) for a message that has nothing to do with DFlow ──

#: words of DFlow work, matched as whole words. Ambiguous once the accents go (tạo/tao, ảnh/anh, mẫu/màu,
#: bài/bai…) → only with their accents; unambiguous ones also without ("nguoi mau", "clip", "long tieng").
_WORK_ACCENTED = {"tạo", "làm", "vẽ", "lưu", "mẫu", "ảnh", "hình", "bài", "đăng", "lịch", "kênh", "giọng", "đổi", "sửa",
                  "xoá", "xóa", "huỷ", "hủy", "giúp", "dựng", "ghép", "quay", "tập", "viết", "cắt", "cào", "quét"}
_WORK_PLAIN = ("model", "nguoi mau", "nhan vat", "kol", "clip", "video", "san pham", "sp", "link", "http", "https", "shopee",
               "tiktok", "lazada", "post", "fanpage", "facebook", "fb", "reel", "long tieng", "dub", "capcut", "phu de",
               "kich ban", "quang cao", "affiliate", "huong dan", "chuc nang", "tinh nang", "lam duoc", "lam gi", "credit",
               "flow", "dflow", "tro ly", "tao mau", "ve mau", "luu mau", "tao clip", "lam clip", "viet bai", "dang bai",
               "series", "loat", "len lich", "hen gio", "kenh", "tu dong", "dang deu", "moi ngay", "hang ngay", "cat video", "cat clip",
               "cat thanh", "youtube", "douyin", "cao video", "cao kenh", "quet kenh", "lay video",
               # how people ask for a model in everyday talk
               "co gai", "con gai", "con nho", "em gai", "chang trai", "anh chang", "co nang", "hot girl", "hotgirl", "hot boy",
               "gai xinh", "trai dep", "mau nu", "mau nam")
#: wanting something — with a describing word below it is a model request even out of a conversation ("tao cần 1 em tóc ngắn")
_WANT = ("muon", "can", "kiem", "tim")
#: describing a model — work only in a running conversation ("tóc ngắn hơn", "nam nhé")
_FOLLOW_UP = ("toc", "ao", "vay", "dam", "trang phuc", "phong cach", "sang chanh", "nam", "nu", "viet", "han", "nhat", "trung",
              "thai", "my", "phap", "tre", "tuoi", "gay", "ngan", "dai", "xoan", "thang", "mat", "da", "trang", "den", "ten")
_GREETING = {"hi", "hello", "hey", "chao", "alo", "xin chao", "chao ban", "chao em", "hi ban", "chao tro ly"}
_THANKS = {"ok", "oke", "okay", "uh", "u", "um", "vang", "da", "cam on", "thanks", "thank you", "tks", "ok cam on", "good", "hay"}
#: answers to "làm luôn chứ?" — a plan waiting for a go-ahead
_YES = {"ok", "oke", "okay", "uh", "u", "um", "vang", "da", "yes", "co", "dong y", "lam di", "lam luon", "chay di", "chay luon",
        "ok lam di", "ok lam luon", "duoc", "dc", "dung roi", "chuan", "go", "xac nhan"}
_NO = {"khong", "ko", "k", "thoi", "huy", "dung", "stop", "no", "khong can", "thoi khoi", "huy di", "bo di"}
SKILLS_VI = ("tạo người mẫu AI, thêm sản phẩm từ link, viết bài Facebook (cả tập tiếp của loạt truyện) kèm ảnh, lên lịch "
             "đăng / tự đăng lên Page, đặt lịch tự động đăng đều (VD T2–T6 20h), tạo clip quảng cáo có kịch bản theo sản phẩm, "
             "cắt video dài thành nhiều video ngắn, cào danh sách video của kênh YouTube / TikTok / Douyin / Bilibili")
GREETING_REPLY = (f"Chào bạn 👋 Mình là trợ lý của DFlow. Mình làm được: **{SKILLS_VI}**. Cứ nói việc cần làm, ví dụ “viết tập tiếp "
                  "của loạt … cho kênh … rồi lên lịch 20h tối nay”.")
THANKS_REPLY = "Dạ 👍 Cần gì trong DFlow cứ nhắn mình nha."
OFF_TOPIC_REPLY = (f"Mình là trợ lý của DFlow nên chỉ giúp việc trong app thôi nha 😅 — mình làm được: **{SKILLS_VI}**. "
                   "Bạn cần làm gì trong DFlow?")


def _plain(text: str) -> str:
    t = unicodedata.normalize("NFD", (text or "").lower()).replace("đ", "d")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _has(plain: str, phrases) -> bool:
    padded = f" {plain} "
    return any(f" {p} " in padded for p in phrases)


def quick_reply(text: str, last_reply: str = "", in_conversation: bool = False) -> Optional[str]:
    """A canned answer when ``text`` needs no AI (greeting, thanks, plainly off-topic) — no LLM call, no tokens.
    ``None`` = send it to the AI. Loose on purpose: anything that might be work goes to the AI (which turns the
    rest down in one sentence); an answer to a question the assistant just asked always goes through."""
    if last_reply.strip().endswith("?"):
        return None
    plain = _plain(text)
    if plain in _GREETING:
        return GREETING_REPLY
    if plain in _THANKS:
        return THANKS_REPLY
    words = set(re.findall(r"\w+", unicodedata.normalize("NFC", text.lower())))
    if words & _WORK_ACCENTED or _has(plain, _WORK_PLAIN):
        return None
    if _has(plain, _FOLLOW_UP) and (in_conversation or _has(plain, _WANT)):
        return None
    return OFF_TOPIC_REPLY


# ── the catalog the AI picks from (and we match names against) ─────────────

def similarity(a: str, b: str) -> float:
    """How alike two names are, accents / case / spacing aside (0–1)."""
    pa, pb = _plain(a), _plain(b)
    if not pa or not pb:
        return 0.0
    if pa == pb:
        return 1.0
    return SequenceMatcher(None, pa, pb).ratio()


def best_match(name: str, candidates: list[tuple[Any, str]], floor: float = 0.72) -> Optional[Any]:
    """The candidate key whose name is closest to ``name`` (typos, no accents), if close enough."""
    scored = sorted(((similarity(name, n), k) for k, n in candidates), key=lambda x: -x[0])
    return scored[0][1] if scored and scored[0][0] >= floor else None


def catalog() -> dict[str, Any]:
    """Channels (+ their series), products, clip kinds and models — what the plan may point at."""
    from flowboard.routes.posts import list_series
    from flowboard.services.scheduler import can_auto
    from flowboard.services.templates import list_templates

    with get_session() as s:
        channels = [{"id": c.id, "name": c.name, "platforms": list(c.platforms or [])} for c in s.exec(select(Channel)).all()]
        products = [{"id": p.id, "name": p.name, "category": p.category, "has_photo": bool(p.media_ids)}
                    for p in s.exec(select(Product).order_by(Product.updated_at.desc()).limit(40)).all()]
        models = [m.label for m in s.exec(select(Reference).where(Reference.kind == "character").order_by(Reference.id.desc()).limit(8)).all()]
    for c in channels:
        c["fb_connected"] = can_auto(c["id"])
    series = [{"name": x["name"], "channel_id": x.get("channel_id"), "episodes": x.get("episodes"),
               "last_episode": x.get("last_episode")} for x in list_series(None)]
    templates = [{"id": t["id"], "title": t.get("title"), "category": t.get("category")} for t in list_templates()]
    return {"channels": channels, "series": series, "products": products, "templates": templates, "models": models}


#: what each skill needs in the account's plan — the features the pages behind it ask for (plans._rule); None = never
#: locked (clips, products, models). The skills call the services directly, past the API's own plan check, so the
#: assistant checks here: before planning (chat) and before every step (_run).
TOOL_FEATURE: dict[str, Optional[str]] = {
    "create_model": None, "add_product": None, "create_clip": None, "write_post": "posts", "schedule_post": "facebook",
    "auto_post": "autopilot", "cut_video": "cut", "grab_channel": "grab"}


def locked_tools() -> dict[str, str]:
    """The skills the account the agent serves now may not use: ``{tool: feature}`` ({} with no login, or for the admin)."""
    from flowboard import accounts, plans

    if not accounts.auth_enabled():
        return {}
    user = accounts.active_user()
    full = (accounts.get_user(user["username"]) or user) if user else None  # the cached copy may predate a plan change
    if full is None:
        return {t: f for t, f in TOOL_FEATURE.items() if f}
    return {t: f for t, f in TOOL_FEATURE.items() if f and not plans.allows(full, f)}


def plan_refusal(actions: list[dict[str, Any]], locked: Optional[dict[str, str]] = None) -> Optional[str]:
    """Why a plan cannot run on this account's plan ("" = it can) — the features it needs and the plan lacks."""
    locked = locked_tools() if locked is None else locked
    feats: list[str] = []
    for a in actions:
        f = locked.get(a.get("tool", ""))
        if f and f not in feats:
            feats.append(f)
    if not feats:
        return None
    from flowboard import accounts, plans

    user = accounts.active_user()
    plan = plans.plan_of(user)["name"] if user else "hiện tại"
    names = ", ".join(f"“{plans.feature_label(k)}”" for k in feats)
    return (f"Việc này cần tính năng {names} — gói {plan} của bạn chưa có nên mình không làm được. "
            "Muốn dùng thì bấm “⬆ Nâng cấp gói” ở trang Tài khoản của tôi.")


def _context(cat: dict[str, Any], locked: Optional[dict[str, str]] = None) -> str:
    from flowboard import plans
    from flowboard.services.flow_client import flow_client
    from flowboard.services.flow_project import effective_project_id

    now = datetime.now(VN)
    weekday = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"][now.weekday()]
    flow = "connected" if flow_client.connected else "NOT connected (extension / Flow tab not open)"
    project = "pinned" if effective_project_id() else "NOT pinned (Cài đặt → Google Flow)"
    extra = []
    if locked:
        extra.append("NOT IN THIS ACCOUNT'S PLAN (never plan these tools; if asked, say in Vietnamese that the plan lacks the "
                     "feature and \"⬆ Nâng cấp gói\" unlocks it): "
                     + ", ".join(f"{t} ({plans.feature_label(f)})" for t, f in locked.items()))
    return "\n".join([
        f"NOW (Vietnam): {weekday} {now.strftime('%Y-%m-%d %H:%M')}",
        f"FLOW: extension {flow}; project {project}",
        *extra,
        "CATALOG:",
        "channels = " + json.dumps(cat["channels"], ensure_ascii=False),
        "series = " + json.dumps(cat["series"], ensure_ascii=False),
        "products = " + json.dumps(cat["products"], ensure_ascii=False),
        "clip_kinds = " + json.dumps(cat["templates"], ensure_ascii=False),
        "saved_models = " + json.dumps(cat["models"], ensure_ascii=False),
    ])


def _history() -> str:
    with get_session() as s:
        rows = s.exec(select(AssistantMessage).order_by(AssistantMessage.id.desc()).limit(HISTORY_TURNS)).all()
    lines = [f"{'SELLER' if m.role == 'user' else 'YOU'}: {m.text[:600]}" for m in reversed(rows)]
    return "\n".join(lines)


def _last_assistant_text() -> str:
    with get_session() as s:
        m = s.exec(select(AssistantMessage).where(AssistantMessage.role == "assistant").order_by(AssistantMessage.id.desc())).first()
    return m.text if m else ""


# ── reading the AI's plan ──────────────────────────────────────────────────

def _int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _channel_id(v: Any, cat: dict[str, Any]) -> Optional[int]:
    ids = {c["id"] for c in cat["channels"]}
    if _int(v) in ids:
        return _int(v)
    if isinstance(v, str):
        return best_match(v, [(c["id"], c["name"]) for c in cat["channels"]])
    return None


def _product_id(v: Any, cat: dict[str, Any]) -> Any:
    if v in (None, "", 0):
        return None
    if v == "previous":
        return "previous"
    ids = {p["id"] for p in cat["products"]}
    if _int(v) in ids:
        return _int(v)
    if isinstance(v, str):
        return best_match(v, [(p["id"], p["name"]) for p in cat["products"]], floor=0.6)
    return None


def _series_name(v: Any, channel_id: Optional[int], cat: dict[str, Any]) -> str:
    """The catalog's spelling of a series (of that channel, or never tied to one); a new name stays as typed."""
    name = re.sub(r"\s+", " ", str(v or "")).strip()[:80]
    if not name:
        return ""
    own = [(x["name"], x["name"]) for x in cat["series"] if x.get("channel_id") in (channel_id, None)]
    return best_match(name, own, floor=0.7) or name


def _clean_args(tool: str, a: dict[str, Any], cat: dict[str, Any]) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Checked, normalised args — or a question for the seller when something essential is missing."""
    if tool == "create_model":
        gender = str(a.get("gender") or "").lower()
        if gender not in GENDERS:
            return None, "Bạn muốn người mẫu nam hay nữ?"
        country = str(a.get("country") or "vn").lower()
        return {"name": str(a.get("name") or "").strip()[:40] or ("Bảo Ngọc" if gender == "female" else "Minh Khang"),
                "gender": gender, "country": country if country in COUNTRIES else "vn",
                "look": re.sub(r"\s+", " ", str(a.get("look") or "")).strip()[:700],
                "summary": str(a.get("summary") or "").strip()[:200]}, None
    if tool == "add_product":
        url = str(a.get("url") or "").strip()
        if not re.match(r"https?://", url):
            return None, "Bạn gửi mình link sản phẩm (Shopee / TikTok Shop…) nhé?"
        return {"url": url[:1000]}, None
    if tool == "write_post":
        cid = _channel_id(a.get("channel_id") or a.get("channel"), cat)
        if cid is None:
            if len(cat["channels"]) == 1:
                cid = cat["channels"][0]["id"]
            else:
                names = ", ".join(c["name"] for c in cat["channels"]) or "chưa có kênh nào"
                return None, f"Bài này cho kênh nào bạn? ({names})"
        kind = str(a.get("kind") or "").lower()
        out: dict[str, Any] = {"channel_id": cid, "series": _series_name(a.get("series"), cid, cat),
                               "kind": kind if kind in POST_KINDS else "",
                               "topic": str(a.get("topic") or "").strip()[:600],
                               "count": max(1, min(MAX_POSTS, _int(a.get("count")) or 1)),
                               "product_id": _product_id(a.get("product_id") or a.get("product"), cat)}
        if a.get("images") is not None:
            out["images"] = max(0, min(4, _int(a.get("images")) or 0))
        return out, None
    if tool == "schedule_post":
        from flowboard.services.scheduler import ScheduleError, parse_when

        try:
            when = parse_when(str(a.get("at") or ""))
        except ScheduleError:
            return None, "Bạn muốn đăng lúc mấy giờ, ngày nào?"
        if when < _now() + timedelta(minutes=2):
            local = when.astimezone(VN).strftime("%H:%M %d/%m")
            return None, f"{local} đã qua rồi — bạn muốn đăng lúc nào khác?"
        post = a.get("post", "previous")
        fmt = str(a.get("format") or "post").lower()
        return {"post": "previous" if post in (None, "", "previous") else _int(post), "at": utc_iso(when),
                "auto": a.get("auto"), "format": fmt if fmt in ("post", "reel") else "post", "story": bool(a.get("story"))}, None
    if tool == "auto_post":
        cid = _channel_id(a.get("channel_id") or a.get("channel"), cat)
        if cid is None:
            if len(cat["channels"]) == 1:
                cid = cat["channels"][0]["id"]
            else:
                names = ", ".join(c["name"] for c in cat["channels"]) or "chưa có kênh nào"
                return None, f"Tự động đăng cho kênh nào bạn? ({names})"
        ch = next((c for c in cat["channels"] if c["id"] == cid), None)
        if ch is not None and not ch.get("fb_connected"):
            return None, f"Kênh “{ch['name']}” chưa kết nối Facebook Page nên chưa tự đăng được — kết nối ở trang Kênh rồi nhờ mình lại nhé."
        days = sorted({d for d in (_int(x) for x in a.get("days") or []) if d is not None and 0 <= d <= 6})
        times = sorted({f"{int(m.group(1)):02d}:{m.group(2)}" for x in a.get("times") or []
                        if (m := re.match(r"^\s*([01]?\d|2[0-3]):([0-5]\d)\s*$", str(x)))})
        if not days or not times:
            return None, "Bạn muốn đăng vào những ngày nào, mấy giờ? (VD: T2–T6 lúc 20:00)"
        kind = str(a.get("kind") or "").lower()
        images = _int(a.get("images")) if a.get("images") is not None else 1
        out = {"channel_id": cid, "days": days, "times": times[:6], "kind": kind if kind in POST_KINDS else "",
               "topic": str(a.get("topic") or "").strip()[:600], "series": _series_name(a.get("series"), cid, cat),
               "images": max(0, min(4, images or 0)),
               "product_id": _product_id(a.get("product_id") or a.get("product"), cat),
               "ai": a.get("ai") if a.get("ai") in ("claude", "gemini") else "claude", "story": bool(a.get("story"))}
        return out, None
    if tool == "cut_video":
        raw = a.get("urls") if isinstance(a.get("urls"), list) else [a.get("url") or a.get("urls") or ""]
        urls = [u for u in (str(x or "").strip() for x in raw) if re.match(r"https?://", u)][:10]
        if not urls:
            return None, "Bạn gửi mình link video cần cắt nhé (TikTok / Douyin / YouTube / Facebook…)."
        prompt = re.sub(r"\s+", " ", str(a.get("prompt") or "")).strip()[:600]
        how = str(a.get("how") or "").lower()
        how = how if how in ("ai", "prompt", "even") else ("prompt" if prompt else "ai")
        if how == "prompt" and not prompt:
            how = "ai"
        lo, hi = _int(a.get("min_s")) or 30, _int(a.get("max_s")) or 60
        return {"urls": urls, "prompt": prompt, "how": how, "min_s": lo, "max_s": max(hi, lo + 5),
                "max_parts": max(0, min(30, _int(a.get("max_parts")) or 0)),
                "channel_id": _channel_id(a.get("channel_id") or a.get("channel"), cat)}, None
    if tool == "grab_channel":
        from flowboard.services import channel_grab

        raw = a.get("urls") if isinstance(a.get("urls"), list) else [a.get("url") or a.get("urls") or ""]
        urls, why = [], ""
        for x in raw[:10]:
            try:
                urls.append(channel_grab.parse_channel(str(x or ""))["url"])
            except channel_grab.GrabError as exc:
                why = str(exc)
        if not urls:
            return None, why or "Bạn gửi mình link kênh nhé (YouTube, TikTok, Douyin hoặc Bilibili — vd. youtube.com/@tenkenh)."
        return {"urls": list(dict.fromkeys(urls)), "tags": channel_grab.normalize_tags(a.get("tags")),
                "limit": channel_grab.normalize_limit(a.get("limit"))}, None
    if tool == "create_clip":
        pid = _product_id(a.get("product_id") or a.get("product"), cat)
        if pid is None:
            return None, "Clip cho sản phẩm nào bạn? (gửi link hoặc tên sản phẩm đã lưu)"
        tids = {t["id"] for t in cat["templates"]}
        tid = str(a.get("template_id") or "")
        return {"product_id": pid, "template_id": tid if tid in tids else "",
                "channel_id": _channel_id(a.get("channel_id") or a.get("channel"), cat),
                "voiceless": a.get("voiceless") is True or str(a.get("voiceless")).lower() == "true"}, None
    return None, None


def parse_answer(raw: str, cat: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """The LLM's JSON (tolerating prose / fences around it) → ``{reply, actions}``; each action checked against the catalog.
    An action that cannot run turns into a question and nothing is planned."""
    cat = cat or {"channels": [], "series": [], "products": [], "templates": [], "models": []}
    text = (raw or "").strip()
    start, end = text.find("{"), text.rfind("}")
    fallback = "Mình chưa hiểu ý bạn, bạn nói rõ hơn được không?"
    if start < 0 or end <= start:
        return {"reply": text[:800] or fallback, "actions": []}
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return {"reply": fallback, "actions": []}
    reply = str(data.get("reply") or "").strip()[:1200]
    raw_actions = data.get("actions")
    if raw_actions is None and isinstance(data.get("action"), dict):  # the older single-action shape
        raw_actions = [data["action"]]
    actions = []
    for act in raw_actions if isinstance(raw_actions, list) else []:
        if not isinstance(act, dict) or act.get("tool") not in TOOLS or not isinstance(act.get("args"), dict):
            continue
        args, question = _clean_args(act["tool"], act["args"], cat)
        if question:
            return {"reply": question, "actions": []}
        actions.append({"tool": act["tool"], "args": args})
    return {"reply": reply or ("Ok, mình làm ngay nhé." if actions else fallback), "actions": actions[:6]}


def needs_go_ahead(actions: list[dict[str, Any]], cat: dict[str, Any]) -> bool:
    """A plan that publishes on a Page by itself waits for the seller's "✅ Làm luôn"."""
    connected = {c["id"] for c in cat["channels"] if c.get("fb_connected")}
    channel = None
    for act in actions:
        if act["tool"] == "write_post":
            channel = act["args"]["channel_id"]
        if act["tool"] == "schedule_post" and act["args"].get("auto") is not False and (channel in connected or act["args"].get("auto")):
            return True
        if act["tool"] == "auto_post":
            return True
    return False


def _plan_summary(actions: list[dict[str, Any]], cat: dict[str, Any]) -> list[str]:
    names = {c["id"]: c["name"] for c in cat["channels"]}
    products = {p["id"]: p["name"] for p in cat["products"]}
    lines = []
    channel = None
    for i, a in enumerate(actions, 1):
        g = a["args"]
        if a["tool"] == "create_model":
            lines.append(f"{i}. Tạo người mẫu “{g['name']}”")
        elif a["tool"] == "add_product":
            lines.append(f"{i}. Thêm sản phẩm từ link")
        elif a["tool"] == "write_post":
            channel = g["channel_id"]
            what = f"tập tiếp của loạt “{g['series']}”" if g.get("series") else (f"{g['count']} bài" if g["count"] > 1 else "1 bài")
            prod = products.get(g.get("product_id")) if isinstance(g.get("product_id"), int) else None
            lines.append(f"{i}. Viết {what} cho kênh “{names.get(channel, '?')}”" + (f" về “{prod}”" if prod else ""))
        elif a["tool"] == "schedule_post":
            local = datetime.fromisoformat(g["at"].replace("Z", "+00:00")).astimezone(VN).strftime("%H:%M %d/%m")
            auto = g.get("auto") is not False and channel in {c["id"] for c in cat["channels"] if c.get("fb_connected")}
            lines.append(f"{i}. Lên lịch {local}" + (" — ⚡ tự đăng lên Facebook Page" if auto else " — nhắc đăng tay")
                         + (" + 📲 thêm vào tin" if g.get("story") and auto else ""))
        elif a["tool"] == "auto_post":
            from flowboard.services.autopilot import describe_when

            what = f"tập tiếp của loạt “{g['series']}”" if g.get("series") else "một bài mới"
            lines.append(f"{i}. 🤖 Tự động đăng lên Page “{names.get(g['channel_id'], '?')}” — {describe_when(g['days'], g['times'])}: "
                         f"mỗi khung AI ({'Claude CLI' if g['ai'] == 'claude' else 'Gemini'}) viết {what}"
                         + (f" kèm {g['images']} ảnh" if g.get("images") else "") + " rồi tự đăng"
                         + (" + 📲 thêm vào tin" if g.get("story") else ""))
        elif a["tool"] == "cut_video":
            how = {"prompt": f"theo yêu cầu “{g['prompt'][:80]}”", "even": "chia đều", "ai": "AI tự chọn đoạn hay"}[g["how"]]
            lines.append(f"{i}. ✂️ Cắt {len(g['urls'])} video thành nhiều video ngắn {g['min_s']}–{g['max_s']} giây ({how})"
                         + (f", tối đa {g['max_parts']} video mỗi link" if g.get("max_parts") else ""))
        elif a["tool"] == "grab_channel":
            lines.append(f"{i}. 📡 Đọc danh sách {g['limit']} video mới nhất của {len(g['urls'])} kênh "
                         f"({', '.join(u.split('/')[-1] for u in g['urls'])[:80]}) — chưa tải gì về")
        elif a["tool"] == "create_clip":
            prod = products.get(g["product_id"]) if isinstance(g["product_id"], int) else "sản phẩm vừa thêm"
            lines.append(f"{i}. Tạo clip quảng cáo cho “{prod}” (kịch bản theo sản phẩm"
                         + (", 🔇 không lời — chỉ hình + tiếng thật)" if g.get("voiceless") else ")"))
    return lines


# ── one chat turn ──────────────────────────────────────────────────────────

def _pending_task() -> Optional[AssistantTask]:
    with get_session() as s:
        return s.exec(select(AssistantTask).where(AssistantTask.status == "pending").order_by(AssistantTask.id.desc())).first()


async def chat(message: str) -> dict[str, Any]:
    """Save the person's message, ask the LLM, maybe plan work. Returns the new messages (+ the task)."""
    text = (message or "").strip()
    if not text:
        raise AssistantError("Bạn chưa gõ gì.")
    # a plan waiting for a go-ahead: "ok" / "thôi" answer it without the AI
    pending = _pending_task()
    if pending is not None:
        plain = _plain(text)
        if plain in _YES:
            mine = _add_message("user", text[:MAX_MESSAGE])
            task = confirm(pending.id)
            return {"messages": [mine], "task": task}
        if plain in _NO:
            mine = _add_message("user", text[:MAX_MESSAGE])
            cancel(pending.id)
            reply = _add_message("assistant", "Ok, mình huỷ kế hoạch đó rồi.", task_id=pending.id)
            return {"messages": [mine, reply], "task": None}
    last = _last_assistant_text()
    canned = quick_reply(text, last, in_conversation=bool(last))
    mine = _add_message("user", text[:MAX_MESSAGE])
    if canned:
        reply = _add_message("assistant", canned, data={"canned": True})
        return {"messages": [mine, reply], "task": None}
    if pending is not None:  # a new ask replaces a plan nobody confirmed
        cancel(pending.id)
    cat = catalog()
    locked = locked_tools()
    prompt = f"{_context(cat, locked)}\n\nCHAT SO FAR:\n{_history()}\n\nAnswer the SELLER's last message now."
    try:
        raw = await run_llm("auto_prompt", prompt, system_prompt=_SYSTEM, timeout=120)
    except LLMError as exc:
        reply = _add_message("assistant", f"⚠ AI đang lỗi, thử lại sau nhé: {exc}", data={"error": True})
        return {"messages": [mine, reply], "task": None}
    answer = parse_answer(raw, cat)
    refused = plan_refusal(answer["actions"], locked) if answer["actions"] else None
    if refused:  # the AI planned a skill the plan lacks anyway: nothing runs, the seller hears why
        reply = _add_message("assistant", refused, data={"locked": True})
        return {"messages": [mine, reply], "task": None}
    if not answer["actions"]:
        reply = _add_message("assistant", answer["reply"])
        return {"messages": [mine, reply], "task": None}
    wait = needs_go_ahead(answer["actions"], cat)
    task = start_task(answer["actions"], plan=_plan_summary(answer["actions"], cat), pending=wait)
    text_out = answer["reply"]
    if wait:
        text_out += "\n\n" + "\n".join(_plan_summary(answer["actions"], cat)) + "\n\nBài sẽ **tự đăng công khai** lên Page — bấm **✅ Làm luôn** (hoặc gõ “ok”) để mình chạy."
    reply = _add_message("assistant", text_out, task_id=task["id"], data={"confirm": task["id"]} if wait else None)
    return {"messages": [mine, reply], "task": task}


def confirm(task_id: int) -> Optional[dict[str, Any]]:
    """Run a plan that was waiting for the go-ahead."""
    with get_session() as s:
        t = s.get(AssistantTask, task_id)
        if t is None or t.status != "pending":
            return None
        t.status, t.updated_at = "running", _now()
        t.state = {**(t.state or {}), "step": "Đang bắt đầu…"}
        s.add(t)
        s.commit()
        s.refresh(t)
        row = _task_row(t)
    _add_message("assistant", "Ok, mình bắt đầu nhé — xong mình báo.", task_id=task_id)
    _spawn(task_id)
    return row


def cancel(task_id: int) -> bool:
    with get_session() as s:
        t = s.get(AssistantTask, task_id)
        if t is None or t.status != "pending":
            return False
        t.status, t.error, t.updated_at = "canceled", "Đã huỷ", _now()
        s.add(t)
        s.commit()
    return True


# ── background tasks ───────────────────────────────────────────────────────

_RUNNING: set[int] = set()
_TITLES = {"create_model": "Tạo người mẫu", "add_product": "Thêm sản phẩm", "write_post": "Viết bài",
           "schedule_post": "Lên lịch đăng", "create_clip": "Tạo clip", "auto_post": "Đặt lịch tự động đăng",
           "cut_video": "Cắt video", "grab_channel": "Cào video kênh"}


def start_task(actions: list[dict[str, Any]], *, plan: Optional[list[str]] = None, pending: bool = False) -> dict[str, Any]:
    first = actions[0]
    title = (f"Tạo người mẫu “{first['args'].get('name') or ''}”" if len(actions) == 1 and first["tool"] == "create_model"
             else " → ".join(_TITLES.get(a["tool"], a["tool"]) for a in actions))
    with get_session() as s:
        t = AssistantTask(kind="plan", title=title, args={"actions": actions, "plan": plan or []},
                          status="pending" if pending else "running",
                          state={"step": "Chờ bạn xác nhận" if pending else "Đang chuẩn bị…", "done": 0, "ctx": {}, "results": []})
        s.add(t)
        s.commit()
        s.refresh(t)
        row = _task_row(t)
    if not pending:
        _spawn(row["id"])
    return row


def _spawn(task_id: int) -> None:
    if task_id in _RUNNING:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # no loop (a sync caller): resume() picks it up on the next read
    _RUNNING.add(task_id)
    loop.create_task(_run(task_id))


def resume() -> None:
    """Carry on the tasks that were running when the agent stopped (or were started without a loop)."""
    with get_session() as s:
        ids = [t.id for t in s.exec(select(AssistantTask).where(AssistantTask.status == "running")).all()]
    for tid in ids:
        _spawn(tid)


def _state(task_id: int) -> dict[str, Any]:
    with get_session() as s:
        t = s.get(AssistantTask, task_id)
        return dict(t.state or {}) if t else {}


def _save(task_id: int, *, status: Optional[str] = None, error: Optional[str] = None, **state: Any) -> None:
    with get_session() as s:
        t = s.get(AssistantTask, task_id)
        if t is None:
            return
        t.state = {**(t.state or {}), **state}
        if status:
            t.status = status
        if error is not None:
            t.error = error
        t.updated_at = _now()
        s.add(t)
        s.commit()


def _actions_of(t: AssistantTask) -> list[dict[str, Any]]:
    if t.kind == "create_model":  # a task from before plans
        return [{"tool": "create_model", "args": dict(t.args or {})}]
    return list((t.args or {}).get("actions") or [])


async def _run(task_id: int) -> None:
    try:
        with get_session() as s:
            t = s.get(AssistantTask, task_id)
            actions = _actions_of(t) if t else []
        st = _state(task_id)
        done, ctx, results = int(st.get("done") or 0), dict(st.get("ctx") or {}), list(st.get("results") or [])
        locked = locked_tools()  # the plan may have changed since the task was planned (a confirm later, a restart)
        for i in range(done, len(actions)):
            act = actions[i]
            prefix = f"Bước {i + 1}/{len(actions)} · " if len(actions) > 1 else ""
            refused = plan_refusal([act], locked)
            if refused:
                raise AssistantError(refused)
            handler = _HANDLERS[act["tool"]]
            out = await handler(task_id, i, act["args"], ctx, prefix)
            ctx.update(out.get("ctx") or {})
            results.append(out)
            _save(task_id, done=i + 1, ctx=ctx, results=results, link=out.get("link") or _state(task_id).get("link"))
        _finish(task_id, results)
    except AssistantError as exc:
        _fail(task_id, str(exc))
    except Exception as exc:  # noqa: BLE001 — a task never takes the agent down
        logger.exception("assistant: task %s failed", task_id)
        _fail(task_id, f"Lỗi không mong muốn: {exc}")
    finally:
        _RUNNING.discard(task_id)


def _finish(task_id: int, results: list[dict[str, Any]]) -> None:
    lines = [r["line"] for r in results if r.get("line")]
    links = [lk for r in results for lk in (r.get("links") or [])]
    media = [m for r in results for m in (r.get("media") or [])]
    _save(task_id, status="done", step="Xong", media_id=media[0] if media else None,
          reference_id=next((r["ctx"].get("reference_id") for r in results if (r.get("ctx") or {}).get("reference_id")), None))
    text = "Xong rồi! " + ("\n".join(lines) if len(lines) > 1 else (lines[0] if lines else ""))
    _add_message("assistant", text.strip(), task_id=task_id,
                 data={"media_ids": media[:6], "media_id": media[0] if media else None, "links": links,
                       **({"link": links[0]["href"], "link_label": links[0]["label"]} if links else {})})


def _fail(task_id: int, message: str) -> None:
    st = _state(task_id)
    done_lines = [r["line"] for r in (st.get("results") or []) if r.get("line")]
    _save(task_id, status="error", error=message, step="Lỗi")
    text = (("Đã làm xong:\n" + "\n".join(done_lines) + "\n\n") if done_lines else "") + f"⚠ {message}"
    _add_message("assistant", text, data={"error": True}, task_id=task_id)


# ── Flow pictures (shared by the skills; resumable) ────────────────────────

def _image_model() -> Optional[str]:
    """The image model picked in the app (account's UI prefs), else the worker's default."""
    with get_session() as s:
        row = s.get(AppSetting, "ui_prefs")
    try:
        v = json.loads(row.value).get("imageModel") if row else None
    except ValueError:
        v = None
    return v if isinstance(v, str) and v else None


async def _flow_image(task_id: int, key: str, prompt: str, *, aspect: str, refs: Optional[list[str]] = None) -> str:
    """One Flow picture for this task (the request id is kept under ``key`` so a restart picks it up). → media id."""
    from flowboard.services.flow_project import effective_project_id
    from flowboard.worker.processor import get_worker

    st = _state(task_id)
    request_id = st.get(f"{key}_request")
    started_iso = st.get(f"{key}_started")
    if not request_id:
        project = effective_project_id()
        if not project:
            raise AssistantError("Chưa ghim Flow project — vào Cài đặt → Google Flow chọn project rồi nhờ mình lại nhé.")
        params: dict[str, Any] = {"prompt": prompt, "media_provider": "flow", "project_id": project, "aspect_ratio": aspect,
                                  "variant_count": 1, "origin": "assistant", "assistant_task": task_id}
        if refs:
            params["ref_media_ids"] = refs
        if (im := _image_model()):
            params["image_model"] = im
        with get_session() as s:
            req = Request(type="gen_image", params=params, status="queued")
            s.add(req)
            s.commit()
            s.refresh(req)
            request_id = req.id
        get_worker().enqueue(request_id)
        started_iso = utc_iso(_now())
        _save(task_id, **{f"{key}_request": request_id, f"{key}_started": started_iso})
    started = datetime.fromisoformat(str(started_iso).replace("Z", "+00:00"))
    while (_now() - started).total_seconds() < IMAGE_TIMEOUT_S + 60:
        with get_session() as s:
            r = s.get(Request, request_id)
            status, result, err = (r.status, r.result or {}, r.error) if r else ("failed", {}, "request missing")
        if status == "done":
            ids = result.get("media_ids") or []
            if not ids:
                raise AssistantError("Flow trả kết quả nhưng không có ảnh — thường là bộ lọc nội dung, thử tả khác đi nhé.")
            media_id = ids[0]
            try:  # "done" comes a moment before the file is cached; the chat shows it right away
                from flowboard.services import media as media_service

                if media_service.cached_path(media_id) is None:
                    await media_service.fetch_and_cache(media_id)
            except Exception as exc:  # noqa: BLE001 — the picture loads later anyway
                logger.info("assistant: pre-fetch of %s failed: %s", media_id, exc)
            return media_id
        if status in ("failed", "canceled", "timeout", "error"):
            hint = " (thường do bộ lọc nội dung của Flow — thử tả kiểu khác)" if "no media" in str(err or "").lower() else ""
            raise AssistantError(f"Flow không vẽ được ảnh: {err or status}{hint}")
        await asyncio.sleep(POLL_S)
    raise AssistantError("Flow vẽ quá 5 phút chưa xong — xem tab Flow / extension rồi nhờ mình lại.")


# ── the skills ─────────────────────────────────────────────────────────────

def model_prompt(args: dict[str, Any], traits: Optional[str] = None) -> str:
    """The portrait prompt — the same framing as a model made on the "Người mẫu" page."""
    subject = f"{COUNTRIES.get(args.get('country') or 'vn', 'Vietnamese')} {GENDERS.get(args.get('gender') or '', 'person')}"
    if traits is None:
        a, b = random.sample(OWN_TRAITS, 2)
        traits = f"{a} and {b}"
    return ", ".join(x for x in [
        f"Natural daylight head-and-shoulders portrait photo of a {subject} character",
        "subject directly faces the camera, head perfectly straight with zero tilt and zero turn",
        "shoulders square to camera, axially symmetric pose, nose centered, both eyes equally visible at the same height",
        f"an ordinary, non-famous everyday person with their own distinctive face ({traits}), natural skin texture with visible pores, "
        "not resembling any celebrity, idol, actor or influencer",
        args.get("look") or None,
        "head and shoulders framing, centered composition, sharp focus on face",
        "strictly front-on orientation, no head tilt, no head turn, no profile angle, no three-quarter view, no over-the-shoulder pose",
        "no glasses, no hat, no mask, no occlusion, nothing covering the face",
        "photorealistic, natural candid quality, consistent character reference",
    ] if x)


async def _do_create_model(task_id: int, i: int, args: dict[str, Any], ctx: dict[str, Any], prefix: str) -> dict[str, Any]:
    from flowboard.routes.references import ReferenceCreate, create_reference

    st = _state(task_id)
    prompt = st.get(f"s{i}_prompt") or model_prompt(args)
    _save(task_id, step=f"{prefix}Flow đang vẽ ảnh người mẫu…", **{f"s{i}_prompt": prompt}, link="/models")
    media_id = await _flow_image(task_id, f"s{i}", prompt, aspect="IMAGE_ASPECT_RATIO_PORTRAIT")
    _save(task_id, step=f"{prefix}Đang lưu vào Người mẫu đã lưu…", media_id=media_id)
    ref = create_reference(ReferenceCreate(
        media_id=media_id, kind="character", label=args.get("name") or "Người mẫu AI", aspect_ratio="IMAGE_ASPECT_RATIO_PORTRAIT",
        meta={"gender": args.get("gender"), "country": args.get("country"), "extras": args.get("summary") or args.get("look"),
              "prompt": prompt[:2000], "by": "assistant"},
    ))
    who = f"{'nữ' if args.get('gender') == 'female' else 'nam'} {COUNTRY_VI.get(args.get('country') or 'vn', '')}".strip()
    return {"line": f"🧑 Người mẫu “{args.get('name')}” ({who}) đã nằm trong **Người mẫu đã lưu** — dùng được cho clip ngay.",
            "links": [{"label": "Mở Người mẫu đã lưu", "href": "/models"}], "media": [media_id], "link": "/models",
            "ctx": {"reference_id": ref.get("id"), "media_id": media_id}}


async def _do_add_product(task_id: int, i: int, args: dict[str, Any], ctx: dict[str, Any], prefix: str) -> dict[str, Any]:
    from flowboard.services import product_link, tiktok_import

    _save(task_id, step=f"{prefix}Đang đọc trang sản phẩm…", link="/products")
    try:
        read = await product_link.extract_product(args["url"])
    except product_link.ProductLinkError as exc:
        raise AssistantError(f"Không đọc được link sản phẩm: {exc}")
    draft, image_url = read["draft"], read.get("image_url") or ""
    created, _skipped = tiktok_import.save_draft(draft, image_url, args["url"], source="link (Trợ lý AI)")
    if created:
        pid = created[0]["id"]
        if image_url:
            _save(task_id, step=f"{prefix}Đang tải ảnh sản phẩm lên Flow…")
            await tiktok_import.attach_photos(created)
    else:  # already saved under this link
        with get_session() as s:
            row = s.exec(select(Product).where(Product.link == str(draft.get("link") or ""))).first()
        if row is None:
            raise AssistantError("Không lưu được sản phẩm từ link này.")
        pid = row.id
    with get_session() as s:
        p = s.get(Product, pid)
        name, media = (p.name, list(p.media_ids or [])) if p else (draft.get("name") or "", [])
    return {"line": f"🛍 Sản phẩm “{name}” đã có trong **Sản phẩm**{'' if created else ' (đã lưu từ trước)'}.",
            "links": [{"label": "Mở Sản phẩm", "href": "/products"}], "link": "/products",
            "media": media[:1], "ctx": {"product_id": pid}}


def _series_last_brief(name: str, channel_id: int) -> dict[str, Any]:
    """The settings the series' last episode was written with (the frontend's ``seriesBrief``)."""
    with get_session() as s:
        rows = s.exec(select(Post).where(Post.series == name, (Post.channel_id == channel_id) | (Post.channel_id == None))  # noqa: E711
                      .order_by(Post.episode.desc(), Post.id.desc())).all()  # type: ignore[union-attr]
    if not rows:
        return {}
    b = dict(rows[0].brief or {})
    if b.get("kind") == "serial":
        b["kind"] = "story"
    b.pop("series", None)
    return b


async def _do_write_post(task_id: int, i: int, args: dict[str, Any], ctx: dict[str, Any], prefix: str) -> dict[str, Any]:
    from flowboard.routes.channels import get_channel
    from flowboard.routes.posts import _save_written, _series_context
    from flowboard.services import post_writer
    from flowboard.services.products import get_product

    st = _state(task_id)
    channel = get_channel(args["channel_id"])
    if channel is None:
        raise AssistantError("Kênh đó không còn nữa.")
    pid = ctx.get("product_id") if args.get("product_id") == "previous" else args.get("product_id")
    product = get_product(pid) if pid else None
    series = args.get("series") or ""
    brief: dict[str, Any] = {"kind": "discussion", "tone": "friendly", "length": "medium", "cta": "none", "hook": "auto",
                             "format": "auto", "emoji": "some", "boosts": [], "images": 0}
    if series:
        brief.update(_series_last_brief(series, channel["id"]))
    for k in ("kind", "topic"):
        if args.get(k):
            brief[k] = args[k]
    if "images" in args:
        brief["images"] = args["images"]
    if product and product.get("aff_link") and brief.get("cta") == "none":
        brief["cta"] = "link"
    saved: list[dict[str, Any]] = list(st.get(f"s{i}_posts") or [])
    count = args.get("count") or 1
    ctx_series = _series_context(series, channel["id"]) if series else None
    if series and ctx_series is None:
        ctx_series = {"name": series, "episode": 1, "previous": []}
    while len(saved) < count:
        n = len(saved) + 1
        label = f"tập {ctx_series['episode']}" if ctx_series else (f"bài {n}/{count}" if count > 1 else "bài")
        _save(task_id, step=f"{prefix}AI đang viết {label}…", link="/posts")
        extra = (f"BATCH: post {n} of {count} for the same page — a clearly different angle and opening from the others."
                 if count > 1 and not ctx_series else None)
        try:
            post = await post_writer.write_post(brief, product=product, clip=None, channel=channel, series=ctx_series, extra=extra)
        except post_writer.PostWriterError as exc:
            raise AssistantError(f"AI chưa viết được bài: {exc}")
        row = _save_written(post, brief=brief, product_id=pid, channel_id=channel["id"], board_id=None,
                            series=series, episode=ctx_series["episode"] if ctx_series else 0)
        saved.append({"id": row["id"], "title": row.get("title") or post.get("title") or "", "episode": row.get("episode") or 0,
                      "prompts": list(post.get("image_prompts") or [])})
        _save(task_id, **{f"s{i}_posts": saved})
        if ctx_series:
            ctx_series = {**ctx_series, "episode": ctx_series["episode"] + 1,
                          "previous": [*ctx_series["previous"], {"episode": ctx_series["episode"], "title": post.get("title"), "body": post["body"]}]}
    # the posts' AI pictures, like the Bài viết page makes them (square, the product photo as reference)
    media: list[str] = []
    n_images = int(brief.get("images") or 0)
    refs = list((product or {}).get("media_ids") or [])[:1]
    for j, p in enumerate(saved):
        images = list(p.get("images") or [])
        for k, prompt in enumerate(p["prompts"][:n_images]):
            if k < len(images):
                continue
            _save(task_id, step=f"{prefix}Flow đang vẽ ảnh cho bài {j + 1}…" if len(saved) > 1 else f"{prefix}Flow đang vẽ ảnh cho bài…")
            images.append(await _flow_image(task_id, f"s{i}p{j}i{k}", prompt, aspect="IMAGE_ASPECT_RATIO_SQUARE", refs=refs))
            with get_session() as s:
                row = s.get(Post, p["id"])
                if row is not None:
                    row.images = list(images)
                    s.add(row)
                    s.commit()
            p["images"] = images
            _save(task_id, **{f"s{i}_posts": saved})
        media += images[:1]
    names = channel.get("name") or ""
    if len(saved) == 1:
        p = saved[0]
        what = f"**Tập {p['episode']}**" if p.get("episode") else "1 bài"
        line = f"✍️ Đã viết {what} “{p['title']}” cho kênh **{names}**" + (" (kèm ảnh)" if p.get("images") else "") + "."
        links = [{"label": "Mở bài viết", "href": f"/posts?post={p['id']}"}]
    else:
        eps = [f"Tập {p['episode']}" for p in saved if p.get("episode")]
        line = f"✍️ Đã viết {len(saved)} bài" + (f" ({', '.join(eps)})" if eps else "") + f" cho kênh **{names}**, đã lưu trong Bài đã lưu."
        links = [{"label": "Mở Bài viết", "href": "/posts"}]
    return {"line": line, "links": links, "media": media, "link": "/posts",
            "ctx": {"post_ids": [p["id"] for p in saved], "channel_id": channel["id"]}}


async def _do_schedule_post(task_id: int, i: int, args: dict[str, Any], ctx: dict[str, Any], prefix: str) -> dict[str, Any]:
    from flowboard.services import scheduler

    _save(task_id, step=f"{prefix}Đang lên lịch đăng…", link="/schedule")
    post_ids = list(ctx.get("post_ids") or []) if args.get("post") == "previous" else [args["post"]]
    if not post_ids or post_ids == [None]:
        raise AssistantError("Không có bài nào để lên lịch.")
    first = datetime.fromisoformat(str(args["at"]).replace("Z", "+00:00"))
    with get_session() as s:
        post = s.get(Post, post_ids[0])
        channel_id = (post.channel_id if post else None) or ctx.get("channel_id")
    auto = scheduler.can_auto(channel_id) if args.get("auto") is None else bool(args.get("auto")) and scheduler.can_auto(channel_id)
    done = _state(task_id).get(f"s{i}_slots") or []
    for j, pid in enumerate(post_ids):
        if j < len(done):
            continue
        try:
            slot = scheduler.create("post", first + timedelta(days=j), post_id=pid, channel_id=channel_id, auto=auto,
                                    note="Trợ lý AI lên lịch", fb_format=args.get("format") or "post",
                                    fb_story=bool(args.get("story")) and auto)
        except scheduler.ScheduleError as exc:
            raise AssistantError(f"Không lên lịch được: {exc}")
        done.append(slot["id"])
        _save(task_id, **{f"s{i}_slots": done})
    local = first.astimezone(VN).strftime("%H:%M %d/%m")
    how = ("⚡ tự đăng lên Facebook Page" + (" + 📲 thêm vào tin" if args.get("story") else "")) if auto else "tool nhắc ở Hôm nay để bạn đăng tay"
    many = f" ({len(post_ids)} bài, mỗi ngày 1 bài)" if len(post_ids) > 1 else ""
    return {"line": f"📅 Đã lên lịch **{local}**{many} — {how}.", "links": [{"label": "Mở Lịch đăng", "href": "/schedule"}],
            "link": "/schedule", "ctx": {"slot_ids": done}}


async def _do_create_clip(task_id: int, i: int, args: dict[str, Any], ctx: dict[str, Any], prefix: str) -> dict[str, Any]:
    from fastapi import HTTPException

    from flowboard.routes.templates import FromTemplateBody, create_board_from_template
    from flowboard.services.products import get_product
    from flowboard.services.templates import templates_for_category

    pid = ctx.get("product_id") if args.get("product_id") == "previous" else args.get("product_id")
    product = get_product(pid) if pid else None
    if product is None:
        raise AssistantError("Không thấy sản phẩm cho clip này.")
    st = _state(task_id)
    board_id = st.get(f"s{i}_board")
    if not board_id:
        tid = args.get("template_id") or next((t["id"] for t in templates_for_category(product.get("category"))), "affiliate_reel")
        _save(task_id, step=f"{prefix}AI đang viết kịch bản clip theo sản phẩm…", link="/clips")
        try:
            board = await create_board_from_template(FromTemplateBody(
                template_id=tid, name=f"{product['name'][:60]}", inputs={}, product_id=int(product["id"]),
                channel_id=args.get("channel_id") or ctx.get("channel_id"), tailor=True,
                voiceless=bool(args.get("voiceless"))))
        except HTTPException as exc:
            raise AssistantError(f"Không tạo được clip: {exc.detail}")
        board_id = board["id"]
        _save(task_id, **{f"s{i}_board": board_id})
    silent = " (🔇 không lời)" if args.get("voiceless") else ""
    return {"line": f"🎬 Đã tạo clip “{product['name'][:60]}”{silent} với kịch bản viết theo sản phẩm — mở clip rồi bấm **⚡ Tạo video tự động** "
                    "để làm ảnh + video (chạy ngầm hoàn toàn sẽ có ở bản sau).",
            "links": [{"label": "Mở clip", "href": f"/clips/{board_id}/script"}], "link": f"/clips/{board_id}/script",
            "media": list(product.get("media_ids") or [])[:1], "ctx": {"board_id": board_id}}


async def _do_auto_post(task_id: int, i: int, args: dict[str, Any], ctx: dict[str, Any], prefix: str) -> dict[str, Any]:
    from flowboard.services import autopilot

    st = _state(task_id)
    plan_id = st.get(f"s{i}_plan")
    if not plan_id:
        _save(task_id, step=f"{prefix}Đang đặt lịch tự động đăng…", link="/posts?auto=1")
        pid = ctx.get("product_id") if args.get("product_id") == "previous" else args.get("product_id")
        brief: dict[str, Any] = {"images": args.get("images", 1)}
        if args.get("kind"):
            brief["kind"] = args["kind"]
        if args.get("topic"):
            brief["topic"] = args["topic"]
        try:
            plan = autopilot.create_plan({"channel_id": args["channel_id"], "days": args["days"], "times": args["times"],
                                          "brief": brief, "series": args.get("series") or "", "ai": args.get("ai") or "claude",
                                          "product_mode": "fixed" if pid else "none", "product_ids": [pid] if pid else [],
                                          "fb_story": bool(args.get("story")), "enabled": True})
        except autopilot.AutopilotError as exc:
            raise AssistantError(f"Không đặt được lịch tự động: {exc}")
        plan_id = plan["id"]
        _save(task_id, **{f"s{i}_plan": plan_id})
    plan = autopilot.get_plan(plan_id)
    nxt = plan["next"][0]["label"] if plan["next"] else "—"
    return {"line": f"🤖 Đã bật **tự động đăng** cho Page “{plan['channel']}” — {plan['when']}. Bài đầu tiên: **{nxt}** "
                    "(AI soạn trước vài tiếng, bài nằm trong Bài đã lưu, sửa được trước giờ đăng).",
            "links": [{"label": "Mở Tự động đăng", "href": "/posts?auto=1"}], "link": "/posts?auto=1",
            "ctx": {"plan_id": plan_id, "channel_id": plan["channel_id"]}}


async def _do_cut_video(task_id: int, i: int, args: dict[str, Any], ctx: dict[str, Any], prefix: str) -> dict[str, Any]:
    from flowboard.services import video_cut

    st = _state(task_id)
    run_id = st.get(f"s{i}_run")
    if not run_id:
        _save(task_id, step=f"{prefix}Đang đưa video vào hàng cắt…", link="/tools/cut")
        try:
            run_id, made = video_cut.start(links=args["urls"], media=[], how=args["how"], prompt=args.get("prompt") or "",
                                           min_s=args["min_s"], max_s=args["max_s"], max_parts=args.get("max_parts") or 0,
                                           channel_id=args.get("channel_id") or ctx.get("channel_id"))
        except video_cut.CutError as exc:
            raise AssistantError(f"Không cắt được: {exc}")
        _save(task_id, **{f"s{i}_run": run_id})
    n = len(args["urls"])
    return {"line": f"✂️ Đã đưa {n} video vào **Cắt video** — tool tải về, nghe lời, AI chọn đoạn rồi cắt (vài phút mỗi video). "
                    "Xong thì các video ngắn nằm trong Clip của tôi; chỉnh phụ đề / khung / vùng mờ cho từng video hoặc cả loạt ở trang Cắt video.",
            "links": [{"label": "Mở Cắt video", "href": f"/tools/cut?run={run_id}"}], "link": f"/tools/cut?run={run_id}",
            "ctx": {"cut_run": run_id}}


async def _do_grab_channel(task_id: int, i: int, args: dict[str, Any], ctx: dict[str, Any], prefix: str) -> dict[str, Any]:
    from flowboard.services import channel_grab

    st = _state(task_id)
    ids = st.get(f"s{i}_channels")
    if not ids:
        _save(task_id, step=f"{prefix}Đang lưu kênh và đọc danh sách video…", link="/tools/grab")
        ids, errors = [], []
        for url in args["urls"]:
            try:
                ids.append(channel_grab.add_channel(url, args.get("tags"), args.get("limit")))
            except channel_grab.GrabError as exc:
                errors.append(str(exc))
        if not ids:
            raise AssistantError(f"Không đọc được kênh: {errors[0] if errors else 'link không hợp lệ'}")
        _save(task_id, **{f"s{i}_channels": ids})
    href = f"/tools/grab?channel={ids[0]}" if len(ids) == 1 else "/tools/grab"
    return {"line": f"📡 Đã lưu {len(ids)} kênh và đang đọc danh sách video (vài giây mỗi kênh). Ở trang **Cào video kênh** bạn lọc theo "
                    "lượt xem / ngày đăng / độ dài hoặc nhờ AI chọn theo yêu cầu, rồi tải video về để cắt / lồng tiếng.",
            "links": [{"label": "Mở Cào video kênh", "href": href}], "link": href, "ctx": {"grab_channels": ids}}


_HANDLERS = {"create_model": _do_create_model, "add_product": _do_add_product, "write_post": _do_write_post,
             "schedule_post": _do_schedule_post, "create_clip": _do_create_clip, "auto_post": _do_auto_post,
             "cut_video": _do_cut_video, "grab_channel": _do_grab_channel}
