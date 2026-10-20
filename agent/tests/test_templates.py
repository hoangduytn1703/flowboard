"""Board templates: every shipped file builds, placeholders fill, the route
creates a board with the graph on it."""
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Board, Edge, Node
from flowboard.services import templates as tpl
from flowboard.services.board_builder import _parse


def test_every_shipped_template_is_a_valid_spec():
    listed = tpl.list_templates()
    assert {t["id"] for t in listed} >= {"fashion_ad", "fast_food_ad", "cosmetics_ad", "unboxing_review"}
    for meta in listed:
        assert "nodes" not in meta and meta["title"] and meta["blurb"]
        full = tpl.get_template(meta["id"])
        spec = tpl.render(full, {})
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


def test_render_fills_inputs_and_character_picks():
    t = tpl.get_template("fashion_ad")
    spec = tpl.render(t, {"product": "a white linen shirt", "setting": "a rooftop at dusk",
                          "charGender": "male", "charCountry": "jp"})
    by_key = {n["key"]: n for n in spec["nodes"]}
    assert "a white linen shirt" in by_key["s1"]["data"]["prompt"]
    assert "a rooftop at dusk" in by_key["s1"]["data"]["prompt"]
    assert by_key["model"]["data"]["charGender"] == "male"
    assert by_key["model"]["data"]["charCountry"] == "jp"
    assert by_key["model"]["data"]["charVibe"] == "clean"  # template default kept


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
