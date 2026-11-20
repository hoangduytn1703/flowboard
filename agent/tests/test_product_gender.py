"""A men's / women's product cannot get a model of the other gender."""
import pytest

from flowboard.services import product_gender as pg
from flowboard.services import reference_video as rv


@pytest.mark.parametrize("text, want", [
    ("Áo thun nam cổ tròn", "male"),
    ("Áo thun nam Việt Nam", "male"),
    ("Hàng Việt Nam chất lượng cao", ""),      # "Nam" of "Việt Nam" is not "nam"
    ("Áo mưa dáng dài nam nữ", "unisex"),
    ("Áo sơ mi unisex form rộng", "unisex"),
    ("Đầm maxi đi biển", "female"),
    ("Quần jean nữ ống rộng", "female"),
    ("Men's polo shirt", "male"),
    ("Bánh bao trứng muối", ""),
])
def test_guess(text, want):
    assert pg.guess(text) == want


def test_a_model_of_the_other_gender_is_only_a_hint():
    shirt = {"name": "Áo nam", "gender": "male"}
    assert pg.mismatch(shirt, "male") is None and pg.mismatch(shirt, "hands_male") is None
    assert pg.mismatch(shirt, None) is None                      # no person: nothing to suggest
    assert "dành cho nam" in pg.mismatch(shirt, "female") and pg.mismatch(shirt, "hands_female")
    assert pg.mismatch({"name": "x", "gender": "unisex"}, "female") is None
    assert pg.mismatch({"name": "x", "gender": ""}, "female") is None
    # a default (nobody picked it) follows the product, hands kept
    assert pg.for_product(shirt, "female") == "male" and pg.for_product(shirt, "hands_female") == "hands_male"
    assert pg.for_product(shirt, "male") == "male" and pg.for_product({"gender": ""}, "female") == "female"


def _product(client, **body):
    return client.post("/api/products", json={"name": "SP", **body}).json()


def test_new_product_gets_a_guess_unless_given(client):
    assert _product(client, name="Áo thun nam basic")["gender"] == "male"
    assert _product(client, name="Áo thun nam basic", gender="unisex")["gender"] == "unisex"
    assert client.post("/api/products", json={"name": "x", "gender": "boy"}).status_code == 400


def test_clip_from_template_keeps_the_pick_and_fits_only_the_default(client):
    p = _product(client, name="Áo thun nam", category="fashion")

    def model_gender(r):
        assert r.status_code == 200, r.text
        board = client.get(f"/api/boards/{r.json()['id']}").json()
        return next(n for n in board["nodes"] if n["type"] == "character")["data"]["charGender"]

    # 18/11: the seller's pick stands, even a woman for a men's shirt
    assert model_gender(client.post("/api/boards/from-template", json={
        "template_id": "fashion_ad", "product_id": p["id"], "inputs": {"charGender": "female"}, "tailor": False})) == "female"
    # nobody picked: the template's default (female) follows the men's product
    assert model_gender(client.post("/api/boards/from-template", json={
        "template_id": "fashion_ad", "product_id": p["id"], "inputs": {}, "tailor": False})) == "male"


def test_step1_switch_takes_any_hands(client):
    p = _product(client, name="Nồi chiên cho nữ", category="home", gender="female")
    bid = client.post("/api/boards/from-template", json={"template_id": "home_appliance_review", "product_id": p["id"], "inputs": {"charGender": "female"}}).json()["id"]
    assert client.post(f"/api/boards/{bid}/model-mode", json={"mode": "hands", "gender": "male"}).status_code == 200
    assert client.post(f"/api/boards/{bid}/model-mode", json={"mode": "hands", "gender": "female"}).status_code == 200


def test_link_clip_keeps_the_pick_and_fits_only_the_ai_suggestion():
    analysis = {
        "category": "fashion", "category_vi": "thời trang", "product_seen": "áo", "hook": "h", "has_person": True,
        "plan": [{"title_vi": "C", "image_prompt_en": "the model", "motion_prompt_en": "m", "narration_vi": "x"}] * 2,
        "script_vi": "s", "character": {"gender": "female", "country": "vn", "vibe": "clean"},
        "match": {"relevant": True, "score": 1.0, "reason_vi": ""}, "blocked": False,
    }
    shirt = {"id": 1, "name": "Áo nam", "category": "fashion", "gender": "male"}

    def gender(pick):
        spec = rv.board_spec(analysis, shirt, pick)
        return next(n for n in spec["nodes"] if n["type"] == "character")["data"]["charGender"]

    assert gender({"gender": "female"}) == "female"   # the seller's pick
    assert gender(None) == "male"                      # the AI suggested a woman for a men's shirt: moved
    assert gender({"gender": "male"}) == "male"
