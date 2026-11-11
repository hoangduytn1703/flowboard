"""Is this install ready to make a clip? — one answer for the first-run guide and for the check before a generation.

A seller who has just installed DFlow has nothing wired yet: no extension in Chrome, no Flow tab, no Flow project, no
AI key. Each of those used to surface as its own cryptic failure ("502 Bad Gateway") at the moment of the first click.
``status()`` names what is missing, in order, with what to do about it; ``check()`` also asks the extension to look at
the Flow tab again and settles what it can on its own: the project the tab has open becomes the pinned project when
none is pinned, and the plan chip (Pro / Ultra) of the signed-in account becomes the plan DFlow sends.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from flowboard.services import app_env
from flowboard.services.flow_client import _version_tuple, flow_client

logger = logging.getLogger(__name__)

#: Older builds lack read_channel / read_tab and report no version at all.
EXTENSION_MIN = (0, 6, 0)
FLOW_URL = "https://flow.google.com/"

#: account_error values of the extension → what the seller should do.
ACCOUNT_HINTS = {
    "NO_FLOW_TAB": "Chưa có tab flow.google.com nào đang mở trong Chrome.",
    "NO_ACCOUNT_BUTTON": "Tab Flow chưa đăng nhập (hoặc chưa tải xong) — đăng nhập tài khoản Google có gói Flow rồi bấm Kiểm tra lại.",
    "ACCOUNT_PANEL_NOT_FOUND": "Chưa đọc được tài khoản trên tab Flow — tải lại tab (F5) rồi bấm Kiểm tra lại.",
    "extension_outdated": "Extension DFlow Bridge là bản cũ — bấm nút tải lại (↻) ở chrome://extensions.",
}

_ai_cache: dict[str, Any] = {"ok": None, "label": ""}


def plan_of(chip: Optional[str]) -> Optional[str]:
    """The paygate tier behind Flow's plan chip ("ULTRA", "PRO", "AI Pro"…), or None when it says neither."""
    text = (chip or "").upper()
    if "ULTRA" in text:
        return "PAYGATE_TIER_TWO"
    if "PRO" in text:
        return "PAYGATE_TIER_ONE"
    return None


def _project() -> Optional[str]:
    from flowboard.services.flow_project import effective_project_id

    try:
        return effective_project_id() or None
    except Exception:  # noqa: BLE001 - nobody signed in yet / no engine
        return None


def _gemini_keys() -> int:
    from flowboard.services.llm import secrets

    try:
        return len(secrets.get_gemini_keys())
    except Exception:  # noqa: BLE001
        return 0


async def _refresh_ai() -> None:
    """Which AI writes scripts and posts: the picked provider when it runs on this machine, else the Gemini keys."""
    from flowboard.services.llm import registry, secrets

    keys = _gemini_keys()
    label, ok = "", False
    try:
        entry = (secrets.read_feature_config() or {}).get("auto_prompt") or {}
        name = entry.get("provider") or ""
        provider = registry.get_provider(name) if name else None
        if provider is not None and await provider.is_available():
            ok, label = True, {"claude": "Claude", "gemini": "Gemini CLI", "openai": "Codex"}.get(name, name)
    except Exception:  # noqa: BLE001
        logger.debug("setup: provider check failed", exc_info=True)
    if not ok and keys:
        ok, label = True, f"Gemini ({keys} key)"
    _ai_cache.update(ok=ok, label=label)


def _counts() -> dict[str, int]:
    from sqlalchemy import func
    from sqlmodel import select

    from flowboard.db import get_session, has_engine
    from flowboard.db.models import Board, Channel, Product

    out = {"products": 0, "clips": 0, "channels": 0}
    if not has_engine():
        return out
    try:
        with get_session() as s:
            for key, model in (("products", Product), ("clips", Board), ("channels", Channel)):
                out[key] = int(s.exec(select(func.count()).select_from(model)).one())
    except Exception:  # noqa: BLE001
        logger.debug("setup: counts failed", exc_info=True)
    return out


def status() -> dict:
    """What is ready and what is not. Cheap: nothing is asked of the extension (``check`` does that)."""
    conn = flow_client.active_conn if flow_client.connected else None
    version = conn.version if conn else None
    outdated = bool(conn) and _version_tuple(version) < EXTENSION_MIN
    email = conn.email if conn else None
    project = _project()
    tab_project = conn.tab_project if conn else None
    keys = _gemini_keys()
    ai_ok = bool(_ai_cache["ok"]) if _ai_cache["ok"] is not None else keys > 0
    counts = _counts()
    ext_dir = app_env.extension_dir()
    credits = conn.credits if conn and isinstance(conn.credits, int) else None

    if conn and not outdated:
        ext_detail = f"Đã kết nối (bản {version or '?'})."
    elif outdated:
        ext_detail = "Extension là bản cũ — vào chrome://extensions bấm nút tải lại (↻) ở ô DFlow Bridge."
    else:
        ext_detail = ("Chrome chưa có extension DFlow Bridge, hoặc Chrome đang đóng. Extension là cầu nối để DFlow nhờ "
                      "Google Flow vẽ ảnh và video.")
    if email:
        flow_detail = f"Đang dùng {email}" + (f" · còn {credits:,} credit".replace(",", ".") if credits is not None else "") + "."
    else:
        flow_detail = ACCOUNT_HINTS.get((conn.account_error if conn else "") or "", "") or (
            "Mở flow.google.com trong Chrome đó, đăng nhập tài khoản Google có gói AI Pro hoặc Ultra, rồi để tab mở.")
    if project:
        project_detail = "Đã chọn dự án."
    elif tab_project:
        project_detail = "Tab Flow đang mở một dự án — bấm “Dùng dự án đang mở”."
    else:
        project_detail = "Trên tab Flow bấm “+ Dự án mới” để mở một dự án, rồi bấm Kiểm tra lại — DFlow tự lấy dự án đó."
    if ai_ok:
        ai_detail = f"Đang dùng {_ai_cache['label'] or f'Gemini ({keys} key)'}."
    else:
        ai_detail = "Thêm một Gemini API key (miễn phí, lấy ở aistudio.google.com) — AI dùng nó để viết kịch bản và bài đăng."

    steps = [
        {"id": "extension", "required": True, "ok": bool(conn) and not outdated,
         "title": "Cài extension DFlow Bridge vào Chrome", "detail": ext_detail},
        {"id": "flow", "required": True, "ok": bool(email),
         "title": "Mở Google Flow và đăng nhập", "detail": flow_detail},
        {"id": "project", "required": True, "ok": bool(project),
         "title": "Chọn dự án Flow để chứa ảnh và video", "detail": project_detail},
        {"id": "ai", "required": True, "ok": ai_ok,
         "title": "AI viết kịch bản và bài đăng", "detail": ai_detail},
        {"id": "product", "required": False, "ok": counts["products"] > 0,
         "title": "Thêm sản phẩm đầu tiên",
         "detail": (f"Đã có {counts['products']} sản phẩm." if counts["products"]
                    else "Dán link Shopee / TikTok Shop — DFlow lấy tên, ảnh, giá, điểm bán.")},
        {"id": "clip", "required": False, "ok": counts["clips"] > 0,
         "title": "Tạo clip đầu tiên",
         "detail": (f"Đã có {counts['clips']} clip." if counts["clips"]
                    else "Chọn sản phẩm, chọn kiểu clip, bấm ⚡ Tạo video tự động.")},
    ]
    return {
        "ready": all(s["ok"] for s in steps if s["required"]),
        # what a generation cannot do without; the account read (step "flow") is not in it — it reads the page of
        # the Flow tab and must not block work the day Flow moves a button
        "can_generate": bool(conn) and not outdated and bool(project),
        "steps": steps,
        "flow": {
            "connected": bool(conn), "version": version, "email": email, "credits": credits,
            "tier": conn.tier if conn else None, "project_id": project, "tab_project": tab_project,
            "plan": app_env.TIERS.get(app_env.current_tier(), ""),
        },
        "counts": counts,
        "extension_dir": str(ext_dir) if ext_dir else "",
        "flow_url": FLOW_URL,
    }


async def check(use_tab_project: bool = False) -> dict:
    """Look again (ask the extension to read the Flow tab), settle what can be settled, and answer ``status()``.

    ``changed`` lists what was set on the seller's behalf, in words, for a toast.
    """
    changed: list[str] = []
    if flow_client.connected:
        try:
            await flow_client.read_account()
        except Exception:  # noqa: BLE001
            logger.debug("setup: read_account failed", exc_info=True)
        conn = flow_client.active_conn
        if conn is not None:
            # the plan chip of the signed-in account is the truth; a wrong plan makes Flow refuse or pick a weaker model
            tier = plan_of(conn.tier)
            if tier and tier != app_env.current_tier():
                try:
                    app_env.write_values({"FLOWBOARD_PAYGATE_TIER": tier})
                except OSError:
                    logger.warning("setup: could not write the plan to .env", exc_info=True)
                app_env.apply_tier(tier)
                changed.append(f"gói Flow {app_env.TIERS[tier]}")
            # nothing pinned and the tab is inside a project → that is the one (or the seller asked for it by name)
            current = _project()
            if conn.tab_project and conn.tab_project != current and (use_tab_project or not current):
                from flowboard.routes.auth import remember_project_for_active
                from flowboard.services.flow_project import effective_project_id, set_override

                try:
                    set_override(conn.tab_project)
                    remember_project_for_active(effective_project_id())
                    changed.append("dự án Flow đang mở")
                except Exception:  # noqa: BLE001
                    logger.warning("setup: could not pin the open project", exc_info=True)
    await _refresh_ai()
    return {**status(), "changed": changed}


async def open_flow() -> bool:
    """Bring the Flow tab forward (or open one) in the Chrome that has the extension."""
    if not flow_client.connected:
        return False
    try:
        resp = await flow_client._send("open_flow_tab", {"focus_only": True}, timeout=15.0)  # noqa: SLF001 - the call account_pool makes
    except Exception:  # noqa: BLE001
        return False
    return not resp.get("error")
