"""Clips that look like a real buyer filmed them on a phone, and "🔇 Không lời" clips (7/11).

The templates and every LLM that writes scenes follow ``clip_style``: no studio / editorial words, a phone
position, real sounds at the end of each motion, the model's gender spelled out; a voiceless clip carries no
voice line anywhere (template, tailoring, product-link / reference-video plans, assistant)."""
import json

import pytest
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Board, Node
from flowboard.services import assistant, clip_style, reference_video, script_tailor
from flowboard.services.prompt_synth import PRODUCT_GUARD
from flowboard.services.templates import get_template, list_templates, render, voiceless_spec

PRODUCT = {
    "id": 5, "name": "Áo Điều Hòa KAW", "category": "fashion", "price": "359.000đ",
    "description": "A grey long-sleeved work jacket with two small fans on the lower back and a battery pack.",
    "selling_points": "2 quạt gió 2 chiều\nPin 8-14 giờ\nChống nắng, tia UV",
}


def test_every_template_reads_like_phone_footage():
    for meta in list_templates():
        t = get_template(meta["id"])
        for n in t["nodes"]:
            data = n.get("data") or {}
            if n["type"] not in ("image", "video"):
                continue
            text = json.dumps(data, ensure_ascii=False)
            assert clip_style.polish_words(text) == [], (t["id"], n["key"], clip_style.polish_words(text))
            if n["type"] == "image":
                assert "phone" in data["prompt"].lower() and PRODUCT_GUARD[0] in data["prompt"], (t["id"], n["key"])
            else:
                assert "Audio: " in data["prompt"], (t["id"], n["key"])
                assert "slow" not in data["prompt"].lower(), (t["id"], n["key"])  # Veo would render slow motion
                assert data.get("narration") and not data["narration"].startswith("Mọi người ơi"), (t["id"], n["key"])
        setting = next(i["default"] for i in t["inputs"] if i["key"] == "setting")
        assert "studio" not in setting.lower(), t["id"]
        assert t.get("character", {}).get("charVibe") == "casual", t["id"]


def test_person_line_names_the_gender_and_hands():
    assert "man — write he" in clip_style.person_line("male", "vn") and "Vietnamese" in clip_style.person_line("male", "vn")
    assert "woman — write she" in clip_style.person_line("female", "kr")
    assert "hands" in clip_style.person_line("hands_female", "vn") and "never a face" in clip_style.person_line("hands_male")
    assert clip_style.person_line(None) == ""


def test_voiceless_spec_drops_every_voice_line_and_says_so():
    spec = voiceless_spec(render(get_template("fashion_ad"), {}))
    vids = [n for n in spec["nodes"] if n["type"] == "video"]
    assert vids and all(n["data"]["narration"] == "" for n in vids)
    note = next(n for n in spec["nodes"] if n["type"] == "note")["data"]["prompt"]
    assert clip_style.NOTE_VOICELESS in note and clip_style.NOTE_VOICE not in note


def _fake(seen, voice="Trời nắng mà mặc cái này vô là mát liền"):
    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        seen["prompt"], seen["system"] = prompt, system_prompt
        n = prompt.count('"scene":')
        return json.dumps([{"image_prompt": f"Vertical phone photo of the grey long-sleeved work jacket, scene {i}.",
                            "video_prompt": "0-3s: he zips it up. 3-6s: the fans start. 6-8s: an easy exhale. Audio: zip, fan whirr.",
                            "voice": voice} for i in range(1, n + 1)])
    return fake_llm


@pytest.mark.asyncio
async def test_tailoring_knows_the_person_the_place_and_the_voice(monkeypatch):
    t = get_template("fashion_ad")
    spec = render(t, {"charGender": "male", "product": PRODUCT["description"]})
    seen: dict = {}
    monkeypatch.setattr(script_tailor, "run_llm", _fake(seen))
    place, fixed = script_tailor.setting_choice(t, {})
    assert not fixed and "bedroom" in place
    out = await script_tailor.tailor_spec(spec, PRODUCT, template_title=t["title"],
                                          person=clip_style.person_line("male", "vn"), place=place, place_fixed=fixed)
    assert "write he" in seen["prompt"] and "template's suggestion" in seen["prompt"]
    assert clip_style.LOOK_RULES in seen["system"] and clip_style.voice_rules(script_tailor.MAX_WORDS) in seen["system"]
    assert all(n["data"]["narration"].startswith("Trời nắng") for n in out["nodes"] if n["type"] == "video")
    # A place the seller typed is kept as theirs.
    _, fixed = script_tailor.setting_choice(t, {"setting": "an outdoor worksite in hard sun"})
    assert fixed


@pytest.mark.asyncio
async def test_a_voiceless_tailoring_never_keeps_a_voice_line(monkeypatch):
    t = get_template("fashion_ad")
    spec = voiceless_spec(render(t, {"product": PRODUCT["description"]}))
    seen: dict = {}
    monkeypatch.setattr(script_tailor, "run_llm", _fake(seen))  # the model answers with a line anyway
    out = await script_tailor.tailor_spec(spec, PRODUCT, template_title=t["title"], voiceless=True)
    assert clip_style.VOICELESS_RULES in seen["system"] and "VOICE (voice" not in seen["system"]
    vids = [n for n in out["nodes"] if n["type"] == "video"]
    assert all(n["data"]["narration"] == "" and "Audio:" in n["data"]["prompt"] for n in vids)


def test_a_voiceless_clip_from_a_template(client):
    r = client.post("/api/boards/from-template", json={"template_id": "fashion_ad", "inputs": {}, "voiceless": True})
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    with get_session() as s:
        board = s.get(Board, bid)
        nodes = s.exec(select(Node).where(Node.board_id == bid)).all()
    assert board.data["quicktool"]["voiceless"] is True
    assert all(not (n.data or {}).get("narration") for n in nodes if n.type == "video")
    # A normal clip keeps its lines and has no flag.
    r = client.post("/api/boards/from-template", json={"template_id": "fashion_ad", "inputs": {}})
    with get_session() as s:
        board = s.get(Board, r.json()["id"])
        nodes = s.exec(select(Node).where(Node.board_id == board.id)).all()
    assert "voiceless" not in board.data["quicktool"]
    assert all((n.data or {}).get("narration") for n in nodes if n.type == "video")


def _plan():
    return {"category": "fashion", "product_seen": "Áo", "hook": "h", "has_person": True, "scenes": [],
            "script_vi": "", "match": {"relevant": True, "score": 1.0, "reason_vi": ""},
            "character": {"gender": "male", "country": "vn", "vibe": "casual"},
            "plan": [{"title_vi": f"Cảnh {i}", "image_prompt_en": "Vertical phone photo of the model",
                      "motion_prompt_en": "0-3s: zips it. Audio: zip.", "narration_vi": "Mát liền nè"} for i in (1, 2)]}


def test_a_voiceless_plan_and_board_from_a_link_have_no_narration():
    a = reference_video.normalize(_plan(), None, voiceless=True)
    assert a["voiceless"] is True and all(p["narration_vi"] == "" for p in a["plan"])
    spec = reference_video.board_spec(reference_video.normalize(_plan(), None), None, voiceless=True)
    assert all(n["data"]["narration"] == "" for n in spec["nodes"] if n["type"] == "video")
    assert clip_style.NOTE_VOICELESS in next(n for n in spec["nodes"] if n["type"] == "note")["data"]["prompt"]
    # The plan's rules: phone footage, and narration_vi rules or none.
    assert "LOOK" in reference_video.plan_rules(False) and "VOICE (narration_vi" in reference_video.plan_rules(False)
    assert "empty narration_vi" in reference_video.plan_rules(True)


def test_the_assistant_understands_a_voiceless_clip():
    cat = {"channels": [], "series": [], "products": [{"id": 5, "name": "Áo Điều Hòa KAW"}],
           "templates": [{"id": "fashion_ad", "title": "Quảng cáo quần áo"}], "models": []}
    p = assistant.parse_answer(json.dumps({"reply": "ok", "actions": [
        {"tool": "create_clip", "args": {"product_id": 5, "voiceless": True}}]}), cat)
    assert p["actions"][0]["args"]["voiceless"] is True
    q = assistant.parse_answer(json.dumps({"reply": "ok", "actions": [
        {"tool": "create_clip", "args": {"product_id": 5}}]}), cat)
    assert q["actions"][0]["args"]["voiceless"] is False
