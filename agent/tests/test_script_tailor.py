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


def test_existing_clip_is_rewritten_in_place_and_keeps_the_old_text(client, monkeypatch):
    prod = client.post("/api/products", json={
        "name": PRODUCT["name"], "category": "food", "price": PRODUCT["price"],
        "description": PRODUCT["description"], "selling_points": PRODUCT["selling_points"],
    }).json()
    board = client.post("/api/boards/from-template", json={
        "template_id": "fast_food_ad", "product_id": prod["id"], "inputs": {},
    }).json()  # no LLM configured in tests: the template text stays
    nodes = client.get(f"/api/boards/{board['id']}").json()["nodes"]
    by_title = {n["data"].get("title"): n for n in nodes}
    pairs = [(by_title[f"Cảnh {i} - {t}"]["id"], by_title[f"Video {i} - {t}"]["id"])
             for i, t in ((1, "Hero shot"), (2, "Thưởng thức"), (3, "Kết"))]
    old_v1 = by_title["Video 1 - Hero shot"]["data"]["prompt"]
    seen = {}

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        seen["prompt"] = prompt
        return json.dumps([{"image_prompt": f"Scorched rice close-up {i}.",
                            "video_prompt": f"0-3s: floss settles {i}. 3-6s: a piece snaps. 6-8s: still.",
                            "voice": f"Cơm cháy giòn rụm số {i}"} for i in (1, 2, 3)])

    monkeypatch.setattr(script_tailor, "run_llm", fake_llm)
    r = client.post(f"/api/boards/{board['id']}/tailor", json={
        "scenes": [{"image_id": a, "video_id": b} for a, b in pairs], "instructions": "nhấn mạnh giá"})
    assert r.status_code == 200 and r.json()["updated"] == 6
    assert "nhấn mạnh giá" in seen["prompt"]
    after = {n["id"]: n["data"] for n in client.get(f"/api/boards/{board['id']}").json()["nodes"]}
    v1 = after[pairs[0][1]]
    assert v1["prompt"].startswith("0-3s: floss settles 1") and v1["narration"] == "Cơm cháy giòn rụm số 1"
    assert v1["prevPrompt"] == old_v1 and v1["lastRequest"] == script_tailor.TAILOR_REQUEST_LABEL
    assert after[pairs[0][0]]["prompt"].count(PRODUCT_GUARD[0]) == 1
    # A clip without a product cannot be tailored.
    plain = client.post("/api/boards/from-template", json={"template_id": "fast_food_ad", "inputs": {}}).json()
    assert client.post(f"/api/boards/{plain['id']}/tailor", json={
        "scenes": [{"image_id": pairs[0][0]}]}).status_code == 400
