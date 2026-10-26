"""Chat with the AI about the frame and the dancing sticker of a dubbed video
("💬 Nhờ AI tạo khung / nhân vật" in the subtitle editor).

The assistant has one job here — frames and stickers — and that is its
whole "memory" for this place: the system prompt says so, it sees the
current frame / sticker, the video's shape and the presets the seller saved
(their taste), plus the chat so far. It answers with the parameter changes
and, when a picture is needed, an ENGLISH image prompt: a decorative
background for the frame, or a character on plain white for the sticker
(drawn by Flow in the browser, then cut out with ``dub_decor.cutout``).
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from flowboard.services.dub_decor import DEFAULT_FRAME, DEFAULT_MASCOT, normalize_frame
from flowboard.services.llm import run_llm
from flowboard.services.llm.base import LLMError

CORNERS = {"bottom_right": (0.83, 0.9), "bottom_left": (0.17, 0.9), "top_right": (0.83, 0.3), "top_left": (0.17, 0.3)}

_SYSTEM = (
    "You are the frame & sticker designer inside a Vietnamese seller's video tool. Your ONLY job here: design the FRAME around a "
    "dubbed short video and the STICKER character that bobs / dances in a corner of it. If the seller asks for anything else, say "
    "in one short Vietnamese sentence that here you only make frames and stickers, and change nothing.\n"
    "FRAME: the video is shrunk to `scale` (0.6-1) and centred on a background: 'blur' (the video itself, blurred), 'color' (one "
    "colour) or 'image' (a decorative artwork you describe in bg_prompt); optional border (`border` 0-0.03 of the height, "
    "`border_color`). A bg_prompt must be ENGLISH, describe a decorative background artwork in the video's orientation whose CENTRE is "
    "plain / empty (the video covers it) with the decoration around the edges, matching the seller's theme; no text, no letters, no "
    "logos, no watermark, no real or famous people.\n"
    "STICKER: one character that sits in a corner. An image_prompt must be ENGLISH: ONE cute character, full body, standing, facing the "
    "camera, centred, on a plain pure white background, no shadow, no text, no logo; 3D chibi / cartoon style unless the seller wants "
    "otherwise; never a real or famous person. shape 'plain' (cut out, stands freely — default for a new character) or 'circle' "
    "(round badge); motion 'dance' (nhún nhảy), 'bounce' (nhún), 'sway' (lắc lư) or 'none'; size 0.15-0.45; corner bottom_right | "
    "bottom_left | top_right | top_left.\n"
    "Change only what the seller asks; for the rest keep CURRENT. Use the SAVED presets to understand the seller's taste.\n"
    "Output ONLY one JSON object, no prose, no code fences:\n"
    "{\"reply\": str (Vietnamese, 1-2 short sentences: what you made), "
    "\"frame\": null (no change) | \"off\" (remove the frame) | {\"scale\": num, \"bg\": \"blur\"|\"color\"|\"image\", \"color\": \"#rrggbb\", "
    "\"border\": num, \"border_color\": \"#rrggbb\", \"bg_prompt\": str (only when a NEW background artwork is needed, else \"\")}, "
    "\"mascot\": null (no change) | \"off\" (remove it) | {\"image_prompt\": str (only when a NEW character picture is needed, else \"\"), "
    "\"shape\": \"plain\"|\"circle\", \"motion\": \"dance\"|\"bounce\"|\"sway\"|\"none\", \"size\": num, \"corner\": str}}"
)


class DecorAIError(RuntimeError):
    pass


def _parse(text: str) -> dict[str, Any]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.S).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise DecorAIError("AI không trả lời đúng dạng — thử nói lại.")
    try:
        data = json.loads(text[start:end + 1])
    except ValueError as exc:
        raise DecorAIError(f"AI trả về JSON hỏng: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _frame_out(raw: Any, current: Optional[dict]) -> tuple[Any, str]:
    """``(frame or "off" or None, bg_prompt)``."""
    if raw == "off":
        return "off", ""
    if not isinstance(raw, dict):
        return None, ""
    merged = {**DEFAULT_FRAME, **(current or {}), **{k: v for k, v in raw.items() if k != "bg_prompt"}}
    bg_prompt = str(raw.get("bg_prompt") or "").strip()[:900]
    frame = normalize_frame(merged)  # bg "image" without a picture falls back to "blur" here
    if frame and bg_prompt:
        # a new artwork: the browser draws it with Flow, then sets bg_image
        frame["bg"], frame["bg_image"] = "image", ""
    return frame, bg_prompt


def _mascot_out(raw: Any, current: Optional[dict]) -> tuple[Any, str]:
    """``(mascot fields or "off" or None, image_prompt)`` — media_id comes later
    from the browser when a new picture is drawn, else stays the current one."""
    if raw == "off":
        return "off", ""
    if not isinstance(raw, dict):
        return None, ""
    base = {**DEFAULT_MASCOT, **(current or {})}
    out = {
        "media_id": base.get("media_id") or "",
        "shape": raw.get("shape") if raw.get("shape") in ("plain", "circle") else base["shape"],
        "motion": raw.get("motion") if raw.get("motion") in ("dance", "bounce", "sway", "none") else base["motion"],
        "size": base["size"], "x": base["x"], "y": base["y"],
    }
    try:
        out["size"] = round(min(0.6, max(0.08, float(raw.get("size", base["size"])))), 3)
    except (TypeError, ValueError):
        pass
    corner = CORNERS.get(str(raw.get("corner") or ""))
    if corner:
        out["x"], out["y"] = corner
    prompt = str(raw.get("image_prompt") or "").strip()[:900]
    if prompt:
        out["media_id"] = ""
    return out, prompt


async def chat(message: str, *, history: Optional[list[dict]] = None, frame: Optional[dict] = None,
               mascot: Optional[dict] = None, orientation: str = "portrait",
               presets: Optional[list[dict]] = None, timeout: float = 90.0) -> dict[str, Any]:
    """``{reply, frame, bg_prompt, mascot, image_prompt}`` — frame / mascot are
    the new values, "off", or None (unchanged)."""
    message = (message or "").strip()
    if not message:
        raise DecorAIError("Bạn muốn khung / nhân vật thế nào?")
    parts = [f"VIDEO: {orientation} ({'9:16' if orientation == 'portrait' else '16:9' if orientation == 'landscape' else '1:1'})",
             "CURRENT FRAME: " + (json.dumps(frame, ensure_ascii=False) if frame else "none"),
             "CURRENT STICKER: " + (json.dumps({k: v for k, v in (mascot or {}).items() if k != "media_id"}, ensure_ascii=False)
                                    + (" (has a picture)" if (mascot or {}).get("media_id") else " (no picture yet)") if mascot else "none")]
    if presets:
        parts.append("SAVED (the seller's favourites): " + "; ".join(
            f"{p.get('kind')}: {p.get('name')} {json.dumps({k: v for k, v in (p.get('data') or {}).items() if k not in ('media_id', 'bg_image')}, ensure_ascii=False)}"
            for p in presets[:12]))
    if history:
        parts.append("CHAT SO FAR:\n" + "\n".join(
            f"{'SELLER' if h.get('role') == 'user' else 'YOU'}: {str(h.get('text') or '')[:400]}" for h in history[-8:]))
    parts.append(f"SELLER NOW: {message[:600]}")
    try:
        text = await run_llm("auto_prompt", "\n\n".join(parts), system_prompt=_SYSTEM, timeout=timeout)
    except LLMError as exc:
        raise DecorAIError(f"AI chưa trả lời được: {exc}") from exc
    data = _parse(text)
    new_frame, bg_prompt = _frame_out(data.get("frame"), frame)
    new_mascot, image_prompt = _mascot_out(data.get("mascot"), mascot)
    return {"reply": str(data.get("reply") or "").strip()[:400] or "Xong.", "frame": new_frame, "bg_prompt": bg_prompt,
            "mascot": new_mascot, "image_prompt": image_prompt}
