"""Switching a clip between a model and hands-only, from step 1 and from the
review screen of a link / video clip."""
import pytest

from flowboard.services import reference_video as rv
from flowboard.services.templates import HANDS_MARKER


def _board_from(client, template_id, **inputs):
    r = client.post("/api/boards/from-template", json={"template_id": template_id, "inputs": inputs})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _detail(client, bid):
    d = client.get(f"/api/boards/{bid}").json()
    types = [n["type"] for n in d["nodes"]]
    prompts = [n["data"].get("prompt", "") for n in d["nodes"] if n["type"] in ("image", "video")]
    return d, types, prompts


def test_step1_switches_to_hands_and_back(client):
    bid = _board_from(client, "fast_food_ad")
    d, types, prompts = _detail(client, bid)
    assert "character" in types and not any(HANDS_MARKER in p for p in prompts)
    scenes = sum(1 for t in types if t == "image")

    r = client.post(f"/api/boards/{bid}/model-mode", json={"mode": "hands", "gender": "male", "country": "vn", "hand_look": "chubby hands"})
    assert r.status_code == 200 and r.json()["hands"]["gender"] == "hands_male"
    d, types, prompts = _detail(client, bid)
    assert "character" not in types
    assert all(HANDS_MARKER in p and "chubby hands" in p for p in prompts)
    assert d["board"]["data"]["quicktool"]["hands"]["gender"] == "hands_male"
    # no edge still points at the deleted model
    ids = {n["id"] for n in d["nodes"]}
    assert all(e["source_id"] in ids and e["target_id"] in ids for e in d["edges"])

    # re-apply with another look: exactly one sentence, the new one
    client.post(f"/api/boards/{bid}/model-mode", json={"mode": "hands", "gender": "female", "hand_look": "slim hands"})
    _, _, prompts = _detail(client, bid)
    assert all(p.count(HANDS_MARKER) == 1 and "slim hands" in p and "chubby" not in p for p in prompts)

    r = client.post(f"/api/boards/{bid}/model-mode", json={"mode": "person", "gender": "female", "country": "kr", "vibe": "kpop"})
    assert r.status_code == 200 and r.json()["hands"] is None
    d, types, prompts = _detail(client, bid)
    assert types.count("character") == 1 and not any(HANDS_MARKER in p for p in prompts)
    model = next(n for n in d["nodes"] if n["type"] == "character")
    assert model["data"]["charGender"] == "female" and model["data"]["charCountry"] == "kr"
    # the new model feeds every scene image
    fed = {e["target_id"] for e in d["edges"] if e["source_id"] == model["id"]}
    assert len(fed) == scenes
    assert d["board"]["data"]["quicktool"]["hands"] is None


def test_step1_takes_hands_for_a_bag_in_a_fashion_clip(client):
    """18/11: a bag sits in "thời trang" and used to be refused hands-only like clothes — now only a hint in the UI."""
    bid = _board_from(client, "fashion_ad")
    r = client.post(f"/api/boards/{bid}/model-mode", json={"mode": "hands", "gender": "female"})
    assert r.status_code == 200, r.text
    _, types, _ = _detail(client, bid)
    assert "character" not in types


def _analysis(category="food", character=None):
    return {
        "category": category, "category_vi": "đồ ăn", "product_seen": "bánh", "hook": "h", "has_person": character is not None,
        "plan": [{"title_vi": f"C{i}", "image_prompt_en": f"shot {i} of the model", "motion_prompt_en": f"move {i}", "narration_vi": "x"} for i in (1, 2)],
        "script_vi": "s", "character": character, "match": {"relevant": True, "score": 1.0, "reason_vi": ""}, "blocked": False,
    }


def test_review_screen_can_override_the_suggested_model():
    suggested = {"gender": "female", "country": "kr", "vibe": "clean", "extras_en": "long hair"}
    # AI suggestion kept
    spec = rv.board_spec(_analysis(character=suggested), None, None)
    model = next(n for n in spec["nodes"] if n["type"] == "character")
    assert model["data"]["charGender"] == "female" and model["data"]["charCountry"] == "kr"
    # user picks a man instead: the AI's female-specific extras are dropped
    spec = rv.board_spec(_analysis(character=suggested), None, {"gender": "male"})
    model = next(n for n in spec["nodes"] if n["type"] == "character")
    assert model["data"]["charGender"] == "male" and model["data"]["charExtras"] == ""
    # hands: no model node, every shot carries the sentence
    spec = rv.board_spec(_analysis(character=suggested), None, {"gender": "hands_female", "hand_look": "short nails"})
    assert not any(n["type"] == "character" for n in spec["nodes"])
    shots = [n["data"]["prompt"] for n in spec["nodes"] if n["type"] in ("image", "video")]
    assert shots and all(HANDS_MARKER in p and "short nails" in p for p in shots)
    # no person at all when the AI suggested one
    spec = rv.board_spec(_analysis(character=suggested), None, {"gender": "none"})
    assert not any(n["type"] == "character" for n in spec["nodes"])
    assert not any(HANDS_MARKER in n["data"].get("prompt", "") for n in spec["nodes"])


def test_review_screen_takes_hands_for_a_fashion_product():
    for analysis, product in ((_analysis(category="fashion"), None),
                              (_analysis(category="food"), {"id": 1, "name": "túi xách", "category": "fashion"})):
        spec = rv.board_spec(analysis, product, {"gender": "hands_male"})
        assert not any(n["type"] == "character" for n in spec["nodes"])
