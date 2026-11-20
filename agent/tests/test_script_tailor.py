"""Clips made for a product get their scenes rewritten for it (script_tailor)."""
import json

import pytest

from flowboard.services import script_tailor
from flowboard.services.prompt_synth import PRODUCT_GUARD
from flowboard.services.templates import HANDS_MARKER, apply_product, get_template, product_inputs, render

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
    assert "crumpled napkin" in seen["prompt"]
    imgs = [n for n in out["nodes"] if n["type"] == "image"]
    vids = [n for n in out["nodes"] if n["type"] == "video"]
    assert all("scorched rice" in n["data"]["prompt"] and "cheese" not in n["data"]["prompt"] for n in imgs)
    assert all(n["data"]["prompt"].count(PRODUCT_GUARD[0]) == 1 for n in imgs)       # guard restored
    assert all(n["data"]["prompt"].count(HANDS_MARKER) == 1 for n in imgs + vids)     # hands kept, once
    assert all(n["data"]["narration"].startswith("Cơm cháy giòn rụm") for n in vids)
    # The input spec is untouched (the caller falls back to it on failure).
    assert "crumpled napkin" in [n for n in spec["nodes"] if n["type"] == "image"][0]["data"]["prompt"]


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
             for i, t in ((1, "Món vừa mở"), (2, "Thưởng thức"), (3, "Kết"))]
    old_v1 = by_title["Video 1 - Món vừa mở"]["data"]["prompt"]
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


BAG = {"id": 8, "name": "Túi xách hộp", "category": "fashion", "media_ids": ["m-pink"],
       "description": ("A rectangular-shaped handheld bag with a structured boxy silhouette. It comes in three solid "
                       "color options: cream, red, and pink, as well as two set variants."),
       "selling_points": "", "notes": "Màu sắc: Kem, Đỏ, Hồng"}


@pytest.mark.asyncio
async def test_the_writer_sees_the_sellers_photo_and_never_a_colour_option_list(monkeypatch, tmp_path):
    """18/11: a pink bag sold in cream / red / pink came out cream in 2 of 4 scenes — the writer picked a colour
    from the option list. Now it gets the photo and no option list."""
    photo = tmp_path / "pink.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0jpeg")
    _, spec = _spec()
    seen = {}

    async def fake_photo(product):
        return str(photo)

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0, attachments=None):
        seen.update(prompt=prompt, system=system_prompt, attachments=attachments)
        n = prompt.count('"scene":')
        return json.dumps([{"image_prompt": f"pale pink quilted bag with a white bow, scene {i}.",
                            "video_prompt": "0-3s: a hand lifts it.", "voice": "Xinh ghê"} for i in range(1, n + 1)])

    monkeypatch.setattr(script_tailor, "_product_photo", fake_photo)
    monkeypatch.setattr(script_tailor, "run_llm", fake_llm)
    await script_tailor.tailor_spec(spec, BAG, template_title="t")
    assert seen["attachments"] == [str(photo)] and seen["prompt"].startswith("ATTACHED: the seller's photo")
    assert "color options" not in seen["prompt"] and "structured boxy silhouette" in seen["prompt"]
    assert "never take its colour from a list of colour options" in seen["system"].lower()
    assert "same concrete words in EVERY image_prompt" in seen["system"]


@pytest.mark.asyncio
async def test_a_writer_that_takes_no_image_still_writes_from_the_text(monkeypatch, tmp_path):
    photo = tmp_path / "pink.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0jpeg")
    _, spec = _spec()
    calls = []

    async def fake_photo(product):
        return str(photo)

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0, attachments=None):
        calls.append(attachments)
        if attachments:
            raise script_tailor.LLMError("codex doesn't support vision")
        n = prompt.count('"scene":')
        return json.dumps([{"image_prompt": f"the bag from the reference photo, scene {i}.", "video_prompt": "x",
                            "voice": "y"} for i in range(1, n + 1)])

    monkeypatch.setattr(script_tailor, "_product_photo", fake_photo)
    monkeypatch.setattr(script_tailor, "run_llm", fake_llm)
    out = await script_tailor.tailor_spec(spec, BAG, template_title="t")
    assert calls == [[str(photo)], None]
    assert any("reference photo" in n["data"]["prompt"] for n in out["nodes"] if n["type"] == "image")
    # "phone footage" once drew the camera app over the picture: every scene image says not to
    from flowboard.services.clip_style import NO_PHONE_UI
    assert all(n["data"]["prompt"].count(NO_PHONE_UI) == 1 for n in out["nodes"] if n["type"] == "image")


def test_colour_option_lists_never_reach_an_image_prompt():
    from flowboard.services.templates import visual_description

    assert visual_description(BAG["description"]) == "A rectangular-shaped handheld bag with a structured boxy silhouette."
    assert visual_description("Pink lipstick in a gold tube. Available in 5 shades.") == "Pink lipstick in a gold tube."
    assert visual_description("Comes in a gift box with a ribbon.") == "Comes in a gift box with a ribbon."
    assert visual_description("Available in 3 colours.") == "Available in 3 colours."  # nothing else to keep: kept
    t = get_template("unboxing_review")
    spec = apply_product(render(t, product_inputs(t, BAG, {})), BAG)
    prompts = " ".join(n["data"].get("prompt", "") + str(n["data"].get("aiBrief", "")) for n in spec["nodes"])
    assert "color options" not in prompts and "structured boxy silhouette" in prompts
