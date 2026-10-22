"""Clips made for a product get their scenes rewritten for it (script_tailor)."""
import json

import pytest

from flowboard.services import script_tailor
from flowboard.services.prompt_synth import PRODUCT_GUARD
from flowboard.services.templates import HANDS_MARKER, get_template, render

PRODUCT = {
    "id": 7, "name": "Cơm cháy siêu chà bông", "category": "food", "price": "129.000đ",
    "description": "Crispy handmade scorched rice topped with pork and chicken floss and a fish sauce glaze.",
    "selling_points": "Giòn rụm, không vỡ vụn\nSốt mắm gia truyền\nChà bông heo + gà",
}


def _spec(hands=False):
    t = get_template("fast_food_ad")
    inputs = {"product": PRODUCT["description"], "product_name": PRODUCT["name"]}
    if hands:
        inputs.update(charGender="hands_female", charCountry="vn")
    return t, render(t, inputs)


@pytest.mark.asyncio
async def test_scenes_are_rewritten_from_the_product_and_keep_constraints(monkeypatch):
    t, spec = _spec(hands=True)
    seen = {}

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        seen["prompt"], seen["system"] = prompt, system_prompt
        n = prompt.count('"scene":')
        return json.dumps([{"image_prompt": f"Close-up of Crispy handmade scorched rice, scene {i}.",
                            "video_prompt": "0-3s: floss flakes settle. 3-6s: a piece snaps. 6-8s: still.",
                            "voice": f"Cơm cháy giòn rụm, sốt mắm gia truyền cảnh {i}"} for i in range(1, n + 1)])

    monkeypatch.setattr(script_tailor, "run_llm", fake_llm)
    out = await script_tailor.tailor_spec(spec, PRODUCT, variant=1, of=3, template_title=t["title"])
    # The product facts and the clip number went to the model; the template text did too.
    assert "Sốt mắm gia truyền" in seen["prompt"] and "clip 2 of 3" in seen["prompt"]
    assert "melted cheese" in seen["prompt"]
    imgs = [n for n in out["nodes"] if n["type"] == "image"]
    vids = [n for n in out["nodes"] if n["type"] == "video"]
    assert all("scorched rice" in n["data"]["prompt"] and "cheese" not in n["data"]["prompt"] for n in imgs)
    assert all(n["data"]["prompt"].count(PRODUCT_GUARD[0]) == 1 for n in imgs)       # guard restored
    assert all(n["data"]["prompt"].count(HANDS_MARKER) == 1 for n in imgs + vids)     # hands kept, once
    assert all(n["data"]["narration"].startswith("Cơm cháy giòn rụm") for n in vids)
    # The input spec is untouched (the caller falls back to it on failure).
    assert "melted cheese" in [n for n in spec["nodes"] if n["type"] == "image"][0]["data"]["prompt"]


@pytest.mark.asyncio
async def test_a_bad_answer_raises_so_the_template_text_stays(monkeypatch):
    _, spec = _spec()

    async def fake_llm(*a, **k):
        return '[{"image_prompt": "only one scene"}]'

    monkeypatch.setattr(script_tailor, "run_llm", fake_llm)
    with pytest.raises(script_tailor.TailorError):
        await script_tailor.tailor_spec(spec, PRODUCT)


@pytest.mark.asyncio
async def test_a_typed_product_phrase_is_passed_on(monkeypatch):
    _, spec = _spec()
    seen = {}

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        seen["prompt"] = prompt
        raise script_tailor.LLMError("offline")

    monkeypatch.setattr(script_tailor, "run_llm", fake_llm)
    with pytest.raises(script_tailor.TailorError):
        await script_tailor.tailor_spec(spec, PRODUCT, shown_as="a family-size 500g zip bag")
    assert "exactly as: a family-size 500g zip bag" in seen["prompt"]
