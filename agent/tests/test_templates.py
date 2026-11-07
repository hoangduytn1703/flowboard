"""Board templates: every shipped file builds, placeholders fill, the route
creates a board with the graph on it."""
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Board, Edge, Node
from flowboard.services import templates as tpl
from flowboard.services.board_builder import _parse


#: Every shipped template, in the order the dialog lists them.
ALL_TEMPLATES = ["fashion_ad", "cosmetics_ad", "fast_food_ad", "food_review", "grocery_ad",
                 "home_appliance_review", "unboxing_review", "affiliate_reel"]
#: Every scene image prompt keeps Flow on the uploaded product.
GUARD = "The product must match the reference photo exactly"


def test_every_shipped_template_is_a_valid_spec():
    listed = tpl.list_templates()
    assert [t["id"] for t in listed] == ALL_TEMPLATES
    for meta in listed:
        assert "nodes" not in meta and meta["title"] and meta["blurb"]
        full = tpl.get_template(meta["id"])
        # A template may default to hands-only (no model node): check the
        # graph with a person, the default is covered below.
        spec = tpl.render(full, {"charGender": "female"})
        specs, edges = _parse(spec)  # raises BoardSpecError on a bad file
        types = {v["type"] for v in specs.values()}
        assert {"character", "visual_asset", "image", "video"} <= types
        # every scene image feeds exactly one video
        images = [k for k, v in specs.items() if v["type"] == "image"]
        videos = [k for k, v in specs.items() if v["type"] == "video"]
        assert len(images) == len(videos) == meta["scenes"]
        assert sorted(a for a, b in edges if specs[b]["type"] == "video") == sorted(images)
        # no placeholder survives rendering with defaults
        for v in specs.values():
            for text in v["data"].values():
                assert "{{" not in str(text)
        # the defaults alone also build (hands-only drops the model node)
        default_spec = tpl.render(full, {})
        _parse(default_spec)
        gender = next(i for i in full["inputs"] if i["key"] == "charGender")["default"]
        has_model = any(n["type"] == "character" for n in default_spec["nodes"])
        assert has_model == (gender not in tpl.HANDS_GENDERS), meta["id"]


def test_new_product_line_templates():
    """The four quicktools added for grocery / home / food-review / any:
    4 scenes each, the right category, a product node every scene reads."""
    expect = {"grocery_ad": "grocery", "home_appliance_review": "home",
              "food_review": "food", "affiliate_reel": tpl.ANY_CATEGORY}
    for tid, category in expect.items():
        full = tpl.get_template(tid)
        assert full["category"] == category and full["scenes"] == 4, tid
        assert {i["key"] for i in full["inputs"]} >= {"product", "product_name", "setting", "charGender", "charCountry"}
        spec = tpl.render(full, {"charGender": "female", "product": "a clear acrylic phone stand"})
        images = [n for n in spec["nodes"] if n["type"] == "image"]
        videos = [n for n in spec["nodes"] if n["type"] == "video"]
        assert len(images) == len(videos) == 4, tid
        edges = {(a, b) for a, b in spec["edges"]}
        for n in images:
            assert "a clear acrylic phone stand" in n["data"]["prompt"], (tid, n["key"])
            assert ("product", n["key"]) in edges, (tid, n["key"])
        assert all(n["data"]["narration"] for n in videos), tid
    # the generic reel's wording does not assume a product line
    reel = tpl.render(tpl.get_template("affiliate_reel"), {})
    assert "giỏ hàng" in next(n for n in reel["nodes"] if n["key"] == "v4")["data"]["narration"]


def test_every_scene_prompt_carries_the_product_guard():
    for meta in tpl.list_templates():
        spec = tpl.render(tpl.get_template(meta["id"]), {"charGender": "female"})
        for n in spec["nodes"]:
            if n["type"] == "image":
                assert GUARD in n["data"]["prompt"], (meta["id"], n["key"])


def test_grocery_defaults_to_hands_only_and_food_review_needs_a_person():
    import pytest

    grocery = tpl.get_template("grocery_ad")
    assert next(i for i in grocery["inputs"] if i["key"] == "charGender")["default"] == "hands_female"
    spec = tpl.render(grocery, {})
    assert not any(n["type"] == "character" for n in spec["nodes"])
    assert all("HANDS-ONLY SHOT" in n["data"]["prompt"] for n in spec["nodes"] if n["type"] in ("image", "video"))

    food = tpl.get_template("food_review")
    assert food["person_required"] is True
    with pytest.raises(tpl.PersonRequiredError, match="ăn thử"):
        tpl.render(food, {"charGender": "hands_female"})
    # the clothes message is unchanged
    with pytest.raises(tpl.PersonRequiredError, match="cần người mẫu mặc"):
        tpl.render(tpl.get_template("fashion_ad"), {"charGender": "hands_female"})


def test_template_for_category_picks_the_first_and_skips_any():
    assert tpl.template_for_category("food") == "fast_food_ad"  # not food_review
    assert tpl.template_for_category("grocery") == "grocery_ad"
    assert tpl.template_for_category("home") == "home_appliance_review"
    assert tpl.template_for_category("other") == "unboxing_review"
    assert tpl.template_for_category("any") is None
    assert tpl.template_for_category("") is None
    assert tpl.CATEGORIES == ("fashion", "cosmetics", "food", "grocery", "home", "other")
    assert [t["id"] for t in tpl.templates_for_category("food")] == ["fast_food_ad", "food_review", "affiliate_reel"]
    assert [t["id"] for t in tpl.templates_for_category(None)] == ["affiliate_reel"]


def test_price_line_reads_the_saved_price_over_the_filler():
    t = tpl.get_template("grocery_ad")
    product = {"id": 3, "name": "Ốp lưng mèo", "price": "39.000đ", "description": "a clear phone case",
               "selling_points": "", "link": "", "media_ids": []}
    # the dialog sends the template default untouched → the product's price
    assert tpl.product_inputs(t, product, {"price": "hạt dẻ"})["price"] == "39.000đ"
    assert tpl.product_inputs(t, product, {})["price"] == "39.000đ"
    # a typed price wins; a product without one keeps the filler
    assert tpl.product_inputs(t, product, {"price": "35k"})["price"] == "35k"
    assert tpl.product_inputs(t, {**product, "price": ""}, {"price": "hạt dẻ"})["price"] == "hạt dẻ"
    spec = tpl.render(t, tpl.product_inputs(t, product, {"price": "hạt dẻ"}))
    assert "Giá 39.000đ" in next(n for n in spec["nodes"] if n["key"] == "v4")["data"]["narration"]


def test_render_fills_inputs_and_character_picks():
    t = tpl.get_template("fashion_ad")
    spec = tpl.render(t, {"product": "a white linen shirt", "setting": "a rooftop at dusk",
                          "charGender": "male", "charCountry": "jp"})
    by_key = {n["key"]: n for n in spec["nodes"]}
    assert "a white linen shirt" in by_key["s1"]["data"]["prompt"]
    assert "a rooftop at dusk" in by_key["s1"]["data"]["prompt"]
    assert by_key["model"]["data"]["charGender"] == "male"
    assert by_key["model"]["data"]["charCountry"] == "jp"
    assert by_key["model"]["data"]["charVibe"] == "casual"  # template default kept


def test_create_board_from_template_route(client):
    r = client.get("/api/templates")
    assert r.status_code == 200 and any(t["id"] == "fast_food_ad" for t in r.json())

    r = client.post("/api/boards/from-template",
                    json={"template_id": "fast_food_ad", "name": "Burger tháng 10",
                          "inputs": {"product": "a double cheeseburger"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Burger tháng 10" and len(body["nodes"]) == 9
    with get_session() as s:
        assert s.get(Board, body["id"]) is not None
        nodes = s.exec(select(Node).where(Node.board_id == body["id"])).all()
        edges = s.exec(select(Edge).where(Edge.board_id == body["id"])).all()
    assert len(nodes) == 9 and len(edges) == 8
    assert any("double cheeseburger" in (n.data.get("prompt") or "") for n in nodes)
    assert all(n.status == "idle" for n in nodes)


def test_create_board_from_unknown_template_is_404(client):
    r = client.post("/api/boards/from-template", json={"template_id": "nope"})
    assert r.status_code == 404


def test_hands_only_drops_the_model_and_keeps_the_scenes():
    full = tpl.get_template("fast_food_ad")
    person = tpl.render(full, {"charGender": "female"})
    hands = tpl.render(full, {"charGender": "hands_male", "charCountry": "vn", "handLook": "chubby hands"})
    assert any(n["type"] == "character" for n in person["nodes"])
    assert not any(n["type"] == "character" for n in hands["nodes"])
    # nothing still points at the dropped model node
    keys = {n["key"] for n in hands["nodes"]}
    assert all(set(e) <= keys for e in hands["edges"])
    assert len([n for n in hands["nodes"] if n["type"] == "image"]) == full["scenes"]
    for n in hands["nodes"]:
        if n["type"] in ("image", "video"):
            assert "HANDS-ONLY SHOT" in n["data"]["prompt"]
            assert "Vietnamese male hands" in n["data"]["prompt"] and "chubby hands" in n["data"]["prompt"]
    # the default look is a pretty one
    default = tpl.render(full, {"charGender": "hands_female"})
    assert "beautiful, well-groomed hands" in default["nodes"][3]["data"]["prompt"]


def test_templates_offer_hands_except_where_a_person_is_required():
    for meta in tpl.list_templates():
        gender = next(i for i in meta["inputs"] if i["key"] == "charGender")
        offered = {o[0] for o in gender["options"]}
        assert {"female", "male"} <= offered
        if meta.get("person_required"):
            assert not offered & {"hands_female", "hands_male"}
        else:
            assert {"hands_female", "hands_male"} <= offered


def test_clothes_ad_refuses_hands_only():
    import pytest

    fashion = tpl.get_template("fashion_ad")
    assert fashion["person_required"] is True
    with pytest.raises(tpl.PersonRequiredError, match="cần người mẫu"):
        tpl.render(fashion, {"charGender": "hands_female"})
    # a person is still fine, and other kinds still take hands
    tpl.render(fashion, {"charGender": "male"})
    tpl.render(tpl.get_template("fast_food_ad"), {"charGender": "hands_male"})


def test_from_template_route_rejects_hands_for_clothes(client):
    r = client.post("/api/boards/from-template", json={"template_id": "fashion_ad", "inputs": {"charGender": "hands_male"}})
    assert r.status_code == 400 and "người mẫu" in r.json()["detail"]
    r = client.post("/api/boards/from-template", json={"template_id": "fast_food_ad", "inputs": {"charGender": "hands_male"}})
    assert r.status_code == 200


def test_product_note_uses_the_product_name_not_its_english_description():
    """The script note is Vietnamese: with a saved product its title must
    name the product, not repeat the English phrase that fills {{product}}."""
    t = tpl.get_template("fashion_ad")
    product = {"id": 7, "name": "Áo thun oversize SAIGON", "price": "149k",
               "description": "a navy blue oversized cotton t-shirt with a white chest print",
               "selling_points": "", "link": "", "media_ids": []}
    spec = tpl.apply_product(tpl.render(t, tpl.product_inputs(t, product, {})), product)
    note = next(n for n in spec["nodes"] if n["key"] == "script")["data"]["prompt"]
    assert note.startswith("Quảng cáo Áo thun oversize SAIGON — 4 cảnh")
    assert "navy blue oversized" not in note
    # the scene prompts still carry the English description for Flow
    s1 = next(n for n in spec["nodes"] if n["key"] == "s1")["data"]["prompt"]
    assert "navy blue oversized" in s1


def test_note_how_to_matches_the_wizard_and_drops_the_model_step_in_hands_mode():
    for meta in tpl.list_templates():
        full = tpl.get_template(meta["id"])
        note = next(n for n in tpl.render(full, {"charGender": "female"})["nodes"] if n["key"] == "script")["data"]["prompt"]
        assert "Veo 3.1" not in note and "Chat AI" not in note
        assert "Omni Flash" in note and "bước 5" in note and "tạo Người" in note
        if not full.get("person_required"):
            hands = tpl.render(full, {"charGender": "hands_female"})
            note = next(n for n in hands["nodes"] if n["key"] == "script")["data"]["prompt"]
            assert "tạo Người" not in note and "chỉ quay bàn tay" in note


def test_every_template_defaults_the_model_to_vietnam():
    for meta in tpl.list_templates():
        country = next(i for i in meta["inputs"] if i["key"] == "charCountry")
        assert country["default"] == "vn", meta["id"]
