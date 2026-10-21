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


def test_check():
    shirt = {"name": "Áo nam", "gender": "male"}
    pg.check(shirt, "male")
    pg.check(shirt, "hands_male")
    pg.check(shirt, None)                      # no person: nothing to contradict
    with pytest.raises(pg.GenderMismatchError, match="dành cho nam"):
        pg.check(shirt, "female")
    with pytest.raises(pg.GenderMismatchError):
        pg.check(shirt, "hands_female")
    pg.check({"name": "x", "gender": "unisex"}, "female")
    pg.check({"name": "x", "gender": ""}, "female")


def _product(client, **body):
    return client.post("/api/products", json={"name": "SP", **body}).json()


def test_new_product_gets_a_guess_unless_given(client):
    assert _product(client, name="Áo thun nam basic")["gender"] == "male"
    assert _product(client, name="Áo thun nam basic", gender="unisex")["gender"] == "unisex"
    assert client.post("/api/products", json={"name": "x", "gender": "boy"}).status_code == 400


def test_clip_from_template_refuses_the_wrong_gender(client):
    p = _product(client, name="Áo thun nam", category="fashion")
    r = client.post("/api/boards/from-template", json={"template_id": "fashion_ad", "product_id": p["id"], "inputs": {"charGender": "female"}})
    assert r.status_code == 400 and "dành cho nam" in r.json()["detail"]
    # the template default is female for fashion_ad: leaving it must be refused too
    r = client.post("/api/boards/from-template", json={"template_id": "fashion_ad", "product_id": p["id"], "inputs": {}})
    assert r.status_code == 400
    r = client.post("/api/boards/from-template", json={"template_id": "fashion_ad", "product_id": p["id"], "inputs": {"charGender": "male"}})
    assert r.status_code == 200


def test_step1_switch_refuses_the_wrong_hands(client):
    p = _product(client, name="Nồi chiên cho nữ", category="home", gender="female")
    bid = client.post("/api/boards/from-template", json={"template_id": "home_appliance_review", "product_id": p["id"], "inputs": {"charGender": "female"}}).json()["id"]
    r = client.post(f"/api/boards/{bid}/model-mode", json={"mode": "hands", "gender": "male"})
    assert r.status_code == 400 and "nữ" in r.json()["detail"]
    assert client.post(f"/api/boards/{bid}/model-mode", json={"mode": "hands", "gender": "female"}).status_code == 200


def test_link_clip_refuses_the_wrong_pick_and_the_wrong_ai_suggestion():
    analysis = {
        "category": "fashion", "category_vi": "thời trang", "product_seen": "áo", "hook": "h", "has_person": True,
        "plan": [{"title_vi": "C", "image_prompt_en": "the model", "motion_prompt_en": "m", "narration_vi": "x"}] * 2,
        "script_vi": "s", "character": {"gender": "female", "country": "vn", "vibe": "clean"},
        "match": {"relevant": True, "score": 1.0, "reason_vi": ""}, "blocked": False,
    }
    shirt = {"id": 1, "name": "Áo nam", "category": "fashion", "gender": "male"}
    with pytest.raises(pg.GenderMismatchError):
        rv.board_spec(analysis, shirt, {"gender": "female"})
    with pytest.raises(pg.GenderMismatchError):     # AI suggested a woman for a men's shirt
        rv.board_spec(analysis, shirt, None)
    spec = rv.board_spec(analysis, shirt, {"gender": "male"})
    assert next(n for n in spec["nodes"] if n["type"] == "character")["data"]["charGender"] == "male"
