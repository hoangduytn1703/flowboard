"""Drama clips: a news / gossip story (an article link or pasted text) told
as a narrated slideshow — AI stills that dissolve into one another with a
Vietnamese voice-over and a headline per beat. The user can splice their
own footage (an interview, a screenshot recording) between beats on the
board afterwards; the export joins stills and clips in that order.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from flowboard.db import get_session
from flowboard.db.models import Board
from flowboard.services import product_link
from flowboard.services.board_builder import build_board as _build_board
from flowboard.services.llm import gemini_api

logger = logging.getLogger(__name__)

KIND = "drama"
MIN_BEATS, MAX_BEATS, DEFAULT_BEATS = 4, 12, 8
#: 3.8-flash took ~4 minutes on an 8-beat plan (thinking tokens); 3.5-flash
#: writes the same plan in well under a minute. Falls back through
#: gemini_api.MODEL_FALLBACKS when overloaded.
PLAN_MODEL = "gemini-3.5-flash"
MAX_SOURCE_CHARS = 24_000

_SYSTEM = (
    "You write Vietnamese 'drama' recap videos for TikTok: a story from an article or a "
    "pasted text, told as a sequence of still images with a voice-over. You get the source "
    "text. Write: title_vi (catchy, <= 12 words), summary_vi (3-4 sentences), hook_vi (the "
    "first spoken line, must make people stay), tone (e.g. 'tò mò, kịch tính'), and beats — "
    "one per still image, in story order. Each beat: title_vi (<= 6 words), caption_vi (an "
    "on-screen headline, <= 9 words, no emoji), narration_vi (natural spoken Vietnamese for "
    "this beat, 20-40 words, ngôi 'mình' or neutral reporter voice, attribute claims to the "
    "source — 'theo bài viết', 'theo chia sẻ' — never state unverified accusations as fact), "
    "image_prompt_en (English, <= 420 chars: a cinematic, photoreal illustrative still that "
    "conveys the beat — setting, mood, light, framing; vertical 9:16; NO text, logos or "
    "subtitles in the image; people only as anonymous or seen from behind / in silhouette — "
    "never the likeness of a real named person). Keep facts to what the source says; do not "
    "invent names, numbers or outcomes. The last beat closes with a question or call to "
    "comment. Use the requested number of beats. Output ONLY the JSON object."
)

_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title_vi": {"type": "STRING"},
        "summary_vi": {"type": "STRING"},
        "hook_vi": {"type": "STRING"},
        "tone": {"type": "STRING"},
        "beats": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title_vi": {"type": "STRING"},
                    "caption_vi": {"type": "STRING"},
                    "narration_vi": {"type": "STRING"},
                    "image_prompt_en": {"type": "STRING"},
                },
                "required": ["title_vi", "caption_vi", "narration_vi", "image_prompt_en"],
            },
        },
    },
    "required": ["title_vi", "summary_vi", "hook_vi", "beats"],
}


class DramaError(RuntimeError):
    pass


async def read_source(url: Optional[str], text: Optional[str]) -> dict[str, Any]:
    """``{title, text, url}`` from an article link or pasted text."""
    text = (text or "").strip()
    url = (url or "").strip()
    if url:
        try:
            page = await product_link.fetch_page(url)
        except product_link.ProductLinkError as exc:
            raise DramaError(str(exc)) from exc
        body = page["text"]
        if text:
            body = f"{text}\n\n--- Nội dung link ---\n{body}"
        return {"title": page["title"], "text": body[:MAX_SOURCE_CHARS], "url": page["url"]}
    if len(text) < 40:
        raise DramaError("Dán link bài viết hoặc gõ nội dung câu chuyện (ít nhất vài câu).")
    return {"title": "", "text": text[:MAX_SOURCE_CHARS], "url": None}


async def plan(source: dict[str, Any], *, beats: Optional[int] = None,
               model: str = PLAN_MODEL) -> dict[str, Any]:
    n = max(MIN_BEATS, min(MAX_BEATS, beats or DEFAULT_BEATS))
    ask = (
        f"SOURCE{(' — ' + source['title']) if source.get('title') else ''}:\n{source['text']}\n\n"
        f"Write exactly {n} beats."
    )
    try:
        text = await gemini_api.generate_text(ask, system=_SYSTEM, model=model,
                                              response_schema=_SCHEMA, timeout=240.0)
        data = gemini_api.parse_json(text)
    except gemini_api.GeminiAPIError as exc:
        raise DramaError(str(exc)) from exc
    except ValueError as exc:
        raise DramaError(f"Gemini returned invalid JSON: {exc}") from exc
    return normalize(data, source)


def normalize(data: dict[str, Any], source: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise DramaError("plan is not an object")
    beats = [b for b in (data.get("beats") or []) if isinstance(b, dict) and b.get("image_prompt_en")]
    if len(beats) < MIN_BEATS:
        raise DramaError(f"plan has {len(beats)} beat(s); need at least {MIN_BEATS}")
    beats = beats[:MAX_BEATS]
    for i, b in enumerate(beats, start=1):
        b["title_vi"] = str(b.get("title_vi") or f"Đoạn {i}").strip()
        b["caption_vi"] = str(b.get("caption_vi") or "").strip()[:80]
        b["narration_vi"] = " ".join(str(b.get("narration_vi") or "").split())
        b["image_prompt_en"] = str(b["image_prompt_en"]).strip()
    return {
        "title_vi": str(data.get("title_vi") or (source or {}).get("title") or "Drama").strip()[:120],
        "summary_vi": str(data.get("summary_vi") or "").strip(),
        "hook_vi": str(data.get("hook_vi") or "").strip(),
        "tone": str(data.get("tone") or "").strip(),
        "beats": beats,
        "source_url": (source or {}).get("url"),
    }


_IMAGE_RULE = (
    " Vertical 9:16 composition, cinematic photoreal still, moody natural light. No text, "
    "captions, logos or watermarks in the image. Any person anonymous (from behind, in "
    "silhouette or out of focus), never a real identifiable face."
)


def board_spec(p: dict[str, Any]) -> dict:
    """Script note + one image node per beat; no video nodes — the export
    animates the stills itself. Narration and headline ride on the image."""
    beats = p["beats"]
    script_lines = "\n".join(f"{i}. {b['title_vi']} — {b['narration_vi']}" for i, b in enumerate(beats, 1))
    script = (
        f"{p['title_vi']}\n\n{p.get('summary_vi') or ''}\n\n"
        f"Hook: {p.get('hook_vi') or ''}\nGiọng kể: {p.get('tone') or ''}\n"
        + (f"Nguồn: {p['source_url']}\n" if p.get("source_url") else "")
        + f"\n{len(beats)} đoạn (mỗi đoạn một ảnh + lời kể):\n{script_lines}\n\n"
        "Clip drama ghép ảnh chuyển cảnh + lời đọc; chèn thêm video phỏng vấn ở bước 4 nếu có."
    ).strip()
    nodes: list[dict] = [{"key": "script", "type": "note", "data": {"title": "Kịch bản", "prompt": script}}]
    for i, b in enumerate(beats, start=1):
        nodes.append({"key": f"s{i}", "type": "image", "data": {
            "title": f"Đoạn {i} - {b['title_vi']}"[:80],
            "prompt": (b["image_prompt_en"].rstrip(".") + "." + _IMAGE_RULE)[:900],
            "narration": b["narration_vi"],
            "caption": b["caption_vi"],
        }})
    return {"nodes": nodes, "edges": []}


def build_board(p: dict[str, Any], *, name: Optional[str]) -> dict[str, Any]:
    spec = board_spec(p)
    board_name = (name or "").strip() or f"Drama — {p['title_vi']}"[:80]
    with get_session() as s:
        board = Board(name=board_name, data={"quicktool": {
            "template_id": KIND, "step": 1, "source_url": p.get("source_url"),
            "drama": {"title": p["title_vi"], "hook": p.get("hook_vi"), "tone": p.get("tone")},
        }})
        s.add(board)
        s.commit()
        s.refresh(board)
        board_id, board_name = board.id, board.name
    created = _build_board(board_id, spec)
    # The play order lives on the board so clips spliced in later keep
    # their place; stills start in beat order.
    sequence = [{"node": created[f"s{i}"]} for i in range(1, len(p["beats"]) + 1)]
    with get_session() as s:
        board = s.get(Board, board_id)
        data = dict(board.data or {})
        data["quicktool"] = {**data.get("quicktool", {}), "sequence": sequence}
        board.data = data
        s.add(board)
        s.commit()
    return {"id": board_id, "name": board_name, "nodes": created, "sequence": sequence}
