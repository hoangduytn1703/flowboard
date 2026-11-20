"""Clip from a reference ad: Gemini watches an existing ad video, breaks
it into beats, checks that it sells the same kind of thing as the user's
product, and writes a scene plan (image prompt, motion prompt, Vietnamese
voice line per scene) adapted to that product. ``build_board`` turns the
plan into an ordinary board the Quicktool wizard can render.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional

from flowboard.db import get_session
from flowboard.db.models import Board
from flowboard.services import clip_style
from flowboard.services.board_builder import build_board as _build_board
from flowboard.services.llm import gemini_api
from flowboard.services.templates import apply_product, with_hands

logger = logging.getLogger(__name__)

from flowboard.services.templates import CATEGORIES  # fashion, cosmetics, food, grocery, home, other
#: Below this the product and the video are judged to sell different things.
MATCH_THRESHOLD = 0.45
MAX_SCENES = 6
MIN_SCENES = 2

_CATEGORY_VI = {"fashion": "thời trang", "cosmetics": "mỹ phẩm", "food": "đồ ăn / uống", "grocery": "tạp hoá / phụ kiện",
                "home": "gia dụng", "other": "khác"}

_SYSTEM_HEAD = (
    "You are a director for short TikTok Shop / affiliate product videos in Vietnam. "
    "You get an existing ad video and, optionally, the product the user actually sells. "
    "First analyse the video: what it sells, its hook, structure, camera work, pacing, "
    "on-screen text and voice-over. Then write a plan for a NEW video that keeps the same "
    "structure, hook and energy but sells the user's product (or the same kind of product "
    "if none is given), and looks like a real buyer filmed it on a phone. Every scene becomes "
    "one AI-generated still image (image_prompt_en, English, photoreal phone photo, <= 480 "
    "chars: where the phone is, framing, subject, action, the real place, light, texture; "
    "refer to 'the product from the reference photo' and 'the model' instead of describing "
    "their looks) animated into an 8-second clip (motion_prompt_en, English). Follow the "
    "video's camera work: a still shot becomes a propped phone, a moving one a handheld phone. "
    "Use between 2 and 6 scenes; merge beats that are too short. If the video shows a "
    "person, describe a character to generate (gender, country, vibe 'casual' unless the "
    "video's look clearly calls for another, extras_en with everyday hair and clothes); "
    "otherwise character is null. match: whether the user's product is the same kind of thing "
    "the video advertises — a food ad does not fit a t-shirt. score 1.0 = same kind, 0.0 = "
    "unrelated. Explain reason_vi in Vietnamese.\n"
)


def plan_rules(voiceless: bool) -> str:
    """The look / motion rules of a plan's scenes, and how narration_vi is written."""
    if voiceless:
        voice = clip_style.VOICELESS_RULES.replace("an empty voice", "an empty narration_vi")
    else:
        voice = clip_style.voice_rules(24).replace("VOICE (voice,", "VOICE (narration_vi,")
    return clip_style.LOOK_RULES + clip_style.MOTION_RULES.replace("(video_prompt;", "(motion_prompt_en;") + voice


def system_prompt(head: str, voiceless: bool) -> str:
    return head + plan_rules(voiceless) + "Output ONLY the JSON object."


_SYSTEM = system_prompt(_SYSTEM_HEAD, False)

_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "category": {"type": "STRING", "enum": list(CATEGORIES)},
        "product_seen": {"type": "STRING"},
        "hook": {"type": "STRING"},
        "style": {"type": "STRING"},
        "tone": {"type": "STRING"},
        "has_person": {"type": "BOOLEAN"},
        "voice_transcript_vi": {"type": "STRING"},
        "scenes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "start_s": {"type": "NUMBER"},
                    "end_s": {"type": "NUMBER"},
                    "shot": {"type": "STRING"},
                    "action": {"type": "STRING"},
                    "camera": {"type": "STRING"},
                    "on_screen_text": {"type": "STRING"},
                },
                "required": ["start_s", "end_s", "shot", "action"],
            },
        },
        "plan": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title_vi": {"type": "STRING"},
                    "image_prompt_en": {"type": "STRING"},
                    "motion_prompt_en": {"type": "STRING"},
                    "narration_vi": {"type": "STRING"},
                },
                "required": ["title_vi", "image_prompt_en", "motion_prompt_en", "narration_vi"],
            },
        },
        "script_vi": {"type": "STRING"},
        "character": {
            "type": "OBJECT",
            "nullable": True,
            "properties": {
                "gender": {"type": "STRING", "enum": ["female", "male"]},
                "country": {"type": "STRING", "enum": ["vn", "kr", "jp", "cn", "th", "us", "fr"]},
                "vibe": {"type": "STRING", "enum": ["clean", "douyin", "oldmoney", "coldgirl", "kpop", "casual"]},
                "extras_en": {"type": "STRING"},
            },
            "required": ["gender", "country", "vibe"],
        },
        "match": {
            "type": "OBJECT",
            "properties": {
                "relevant": {"type": "BOOLEAN"},
                "score": {"type": "NUMBER"},
                "reason_vi": {"type": "STRING"},
            },
            "required": ["relevant", "score", "reason_vi"],
        },
    },
    "required": ["category", "product_seen", "hook", "has_person", "scenes", "plan", "script_vi", "match"],
}


class ReferenceVideoError(RuntimeError):
    pass


def _product_brief(product: Optional[dict]) -> str:
    if not product:
        return ("No product given: plan for the same kind of product the video shows; the user "
                "will upload its photo later. match.score = 1.0, relevant = true.")
    lines = [f"USER'S PRODUCT: {product.get('name') or ''}",
             f"category: {product.get('category') or 'other'}"]
    if product.get("description"):
        lines.append(f"description: {product['description']}")
    if product.get("price"):
        lines.append(f"price: {product['price']}")
    if product.get("selling_points"):
        lines.append("selling points:\n" + product["selling_points"])
    return "\n".join(lines)


async def analyze(video_path: Path, product: Optional[dict], *, scenes: Optional[int] = None,
                  model: Optional[str] = None, voiceless: bool = False) -> dict[str, Any]:
    """The analysis + adapted plan for ``video_path`` — Gemini models race,
    the AI picked in Cài đặt → 🤖 AI viết steps in when Google is overloaded
    (``services/plan_ai``). Adds ``blocked`` when the product does not fit
    the video, ``by`` = which AI wrote it."""
    from flowboard.services import plan_ai
    from flowboard.services.video_export import probe_clip

    if not video_path.is_file():
        raise ReferenceVideoError("video file not found")
    ask = [
        "Analyse this ad video and write the plan as described.",
        _product_brief(product),
    ]
    if scenes:
        ask.append(f"Use exactly {max(MIN_SCENES, min(MAX_SCENES, scenes))} scenes in the plan.")
    info = await asyncio.to_thread(probe_clip, video_path)

    def accept(text: str) -> dict[str, Any]:
        try:
            return normalize(gemini_api.parse_json(text), product, voiceless=voiceless)
        except ReferenceVideoError as exc:
            raise ValueError(str(exc)) from exc

    try:
        return await plan_ai.plan_from_video(
            video_path, "\n\n".join(ask), system=system_prompt(_SYSTEM_HEAD, voiceless), schema=_SCHEMA,
            accept=accept, duration=info.duration if info else 0.0, model=model,
        )
    except plan_ai.PlanError as exc:
        raise ReferenceVideoError(str(exc)) from exc


def normalize(data: dict[str, Any], product: Optional[dict], *, voiceless: bool = False) -> dict[str, Any]:
    """Defensive shaping of the model's answer: scene count bounds, the
    match verdict, category label — and the block decision. ``voiceless``
    drops every voice line ("🔇 Không lời")."""
    if not isinstance(data, dict):
        raise ReferenceVideoError("analysis is not an object")
    plan = [p for p in (data.get("plan") or []) if isinstance(p, dict) and p.get("image_prompt_en")]
    if len(plan) < MIN_SCENES:
        raise ReferenceVideoError(f"analysis produced {len(plan)} scene(s); need at least {MIN_SCENES}")
    plan = plan[:MAX_SCENES]
    for i, p in enumerate(plan, start=1):
        p.setdefault("title_vi", f"Cảnh {i}")
        p["narration_vi"] = "" if voiceless else str(p.get("narration_vi") or "").strip()
        p["motion_prompt_en"] = str(p.get("motion_prompt_en") or "").strip()
    category = data.get("category") if data.get("category") in CATEGORIES else "other"
    match = data.get("match") if isinstance(data.get("match"), dict) else {}
    try:
        score = max(0.0, min(1.0, float(match.get("score", 1.0 if not product else 0.0))))
    except (TypeError, ValueError):
        score = 0.0
    relevant = bool(match.get("relevant", score >= MATCH_THRESHOLD))
    blocked = product is not None and (score < MATCH_THRESHOLD or not relevant)
    character = data.get("character") if isinstance(data.get("character"), dict) else None
    if character and character.get("gender") not in ("female", "male"):
        character = None
    out = {
        **data,
        "category": category,
        "category_vi": _CATEGORY_VI[category],
        "plan": plan,
        "character": character,
        "match": {
            "relevant": relevant,
            "score": round(score, 2),
            "reason_vi": str(match.get("reason_vi") or ""),
        },
        "blocked": blocked,
        "voiceless": voiceless,
    }
    if blocked:
        out["block_reason"] = (
            f"Video mẫu quảng cáo {_CATEGORY_VI[category]} ({data.get('product_seen') or '?'}), "
            f"còn sản phẩm của bạn là \"{product.get('name') if product else ''}\" "
            f"({_CATEGORY_VI.get(product.get('category') if product else 'other', 'khác')}). "
            + (out["match"]["reason_vi"] or "Hai thứ không liên quan nhau.")
        )
    return out


#: ``character`` override from the review screen. ``gender`` is what the
#: user picked over the AI's suggestion: female / male, hands_female /
#: hands_male (no person, only hands), or "none" (no person at all).
CharacterPick = Optional[dict]


def _character_for(analysis: dict[str, Any], product: Optional[dict], pick: CharacterPick) -> tuple[Optional[dict], Optional[dict]]:
    """``(character node data or None, hands {gender, country, look} or None)``."""
    suggested = analysis.get("character") or None
    pick = pick or {}
    gender = str(pick.get("gender") or "")
    country = str(pick.get("country") or (suggested or {}).get("country") or "vn")
    if not gender and suggested and product:
        # The AI's suggestion is only a default: a men's / women's product moves it to its gender.
        # What the seller picks is used as is (18/11: "chỉ suggest thôi").
        from flowboard.services.product_gender import for_product

        suggested = {**suggested, "gender": for_product(product, suggested.get("gender"))}
    if gender.startswith("hands_"):
        return None, {"gender": gender, "country": country, "look": str(pick.get("hand_look") or "")}
    if gender == "none":
        return None, None
    if gender in ("female", "male"):
        return {"gender": gender, "country": country,
                "vibe": str(pick.get("vibe") or (suggested or {}).get("vibe") or "casual"),
                "extras_en": (suggested or {}).get("extras_en") if gender == (suggested or {}).get("gender") else ""}, None
    return suggested, None


def board_spec(analysis: dict[str, Any], product: Optional[dict], character_pick: CharacterPick = None,
               *, voiceless: bool = False) -> dict:
    """A board spec in the same shape the templates use."""
    plan = analysis["plan"]
    character, hands = _character_for(analysis, product, character_pick)
    def shot(prompt: str) -> str:
        return with_hands(prompt, hands["gender"], hands["country"], hands["look"]) if hands else prompt
    nodes: list[dict] = []
    edges: list[list[str]] = []
    scene_lines = "\n".join(
        f"{i}. {p['title_vi']}: {p.get('narration_vi') or p['image_prompt_en'][:80]}" for i, p in enumerate(plan, 1)
    )
    script = (
        f"{analysis.get('script_vi') or ''}\n\n"
        f"{'Dựng theo video mẫu' if analysis.get('scenes') else 'Dựng theo link sản phẩm'} — hook: {analysis.get('hook') or ''}\n"
        f"Phong cách: {analysis.get('style') or ''} · {analysis.get('tone') or ''}\n\n"
        f"{len(plan)} cảnh × 8 s:\n{scene_lines}"
    ).strip()
    if hands:
        script += "\nChế độ chỉ quay bàn tay: không có người mẫu, không lộ mặt."
    if voiceless:
        script += "\n" + clip_style.NOTE_VOICELESS
    nodes.append({"key": "script", "type": "note", "data": {"title": "Kịch bản", "prompt": script}})
    refs: list[str] = []
    if character:
        nodes.append({"key": "model", "type": "character", "data": {
            "title": "Người mẫu",
            "charGender": character.get("gender", "female"),
            "charCountry": character.get("country", "vn"),
            "charVibe": character.get("vibe", "casual"),
            "charExtras": str(character.get("extras_en") or "")[:200],
        }})
        refs.append("model")
    nodes.append({"key": "product", "type": "visual_asset", "data": {"title": "Sản phẩm — upload ảnh thật"}})
    refs.append("product")
    rule = (" The product must match the reference photo exactly (shape, colour, print, material)."
            " Keep the product at its real size relative to the person, as in the reference photos. "
            + clip_style.NO_PHONE_UI)
    for i, p in enumerate(plan, start=1):
        nodes.append({"key": f"s{i}", "type": "image", "data": {
            "title": f"Cảnh {i} - {p['title_vi']}"[:80],
            "prompt": shot((p["image_prompt_en"].rstrip(".") + "." + rule)[:900]),
        }})
        nodes.append({"key": f"v{i}", "type": "video", "data": {
            "title": f"Video {i} - {p['title_vi']}"[:80],
            "prompt": shot(p.get("motion_prompt_en") or ""),
            "narration": "" if voiceless else (p.get("narration_vi") or ""),
        }})
        for r in refs:
            edges.append([r, f"s{i}"])
        edges.append([f"s{i}", f"v{i}"])
    spec = {"nodes": nodes, "edges": edges}
    return apply_product(spec, product) if product else spec


def build_board(analysis: dict[str, Any], product: Optional[dict], *, name: Optional[str],
                source_media_id: Optional[str], source_url: Optional[str] = None,
                character_pick: CharacterPick = None, channel_id: Optional[int] = None,
                voiceless: bool = False) -> dict[str, Any]:
    """Create the board for the plan. Returns ``{id, name, nodes}``."""
    spec = board_spec(analysis, product, character_pick, voiceless=voiceless)
    _, hands = _character_for(analysis, product, character_pick)
    base = (product.get("name") if product else None) or analysis.get("product_seen") or "Clip"
    from_link = source_media_id is None
    # From a link the product's own name is the clip name; "theo video mẫu"
    # stays on video clips, where it says what the clip was built from.
    board_name = (name or "").strip() or (base if from_link else f"{base} — theo video mẫu")
    with get_session() as s:
        board = Board(name=board_name, data={"quicktool": {
            "template_id": "product_link" if from_link else "reference_video",
            "product_id": product.get("id") if product else None,
            "channel_id": channel_id,
            "step": 1,
            "source_media_id": source_media_id,
            "source_url": source_url,
            "hands": hands,
            **({"voiceless": True} if voiceless else {}),
            "reference": {
                "category": analysis.get("category"),
                "hook": analysis.get("hook"),
                "product_seen": analysis.get("product_seen"),
                "match": analysis.get("match"),
            },
        }})
        s.add(board)
        s.commit()
        s.refresh(board)
        board_id, board_name = board.id, board.name
    created = _build_board(board_id, spec)
    return {"id": board_id, "name": board_name, "nodes": created}
