"""Product library: CRUD, and a board made from a template + a saved product."""
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Edge, Node

PHOTO_A = "a1b2c3d4-0000-4000-8000-000000000001"
PHOTO_B = "a1b2c3d4-0000-4000-8000-000000000002"


def _create(client, **over):
    body = {
        "name": "Áo thun trắng logo đỏ",
        "description": "a white cotton t-shirt with a small red logo on the chest",
        "category": "fashion",
        "price": "199k",
        "selling_points": "Cotton 100% thoáng mát\n- Form rộng unisex\n\n",
        "link": "https://shop.example/ao-thun",
        "media_ids": [PHOTO_A],
        "aspect_ratio": "IMAGE_ASPECT_RATIO_PORTRAIT",
        **over,
    }
    r = client.post("/api/products", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_product_crud(client):
    p = _create(client)
    assert p["id"] and p["template_id"] == "fashion_ad" and p["media_ids"] == [PHOTO_A]

    r = client.patch(f"/api/products/{p['id']}",
                     json={"price": "179k", "media_ids": [PHOTO_A, f"media/{PHOTO_B}", PHOTO_A]})
    assert r.status_code == 200, r.text
    assert r.json()["price"] == "179k"
    assert r.json()["media_ids"] == [PHOTO_A, PHOTO_B]  # prefix stripped, de-duped
    assert r.json()["name"] == p["name"]  # untouched fields stay

    assert [x["id"] for x in client.get("/api/products").json()] == [p["id"]]
    assert client.delete(f"/api/products/{p['id']}").status_code == 204
    assert client.get(f"/api/products/{p['id']}").status_code == 404


def test_product_validation(client):
    assert client.post("/api/products", json={"name": "  "}).status_code == 400
    assert client.post("/api/products", json={"name": "x", "category": "cars"}).status_code == 400
    assert client.post("/api/products", json={"name": "x", "media_ids": ["../etc"]}).status_code == 400


def test_board_from_template_with_product(client):
    p = _create(client, media_ids=[PHOTO_A, PHOTO_B])
    r = client.post("/api/boards/from-template",
                    json={"template_id": "fashion_ad", "product_id": p["id"],
                          # the dialog sends the template default untouched
                          "inputs": {"product": "the garment shown in the uploaded product photo"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Áo thun trắng logo đỏ — Quảng cáo quần áo"
    with get_session() as s:
        nodes = {n.short_id: n for n in s.exec(select(Node).where(Node.board_id == body["id"])).all()}
        edges = s.exec(select(Edge).where(Edge.board_id == body["id"])).all()
    by_key = {k: nodes[sid] for k, sid in body["nodes"].items()}

    main = by_key["product"]
    assert main.status == "done" and main.data["mediaId"] == PHOTO_A
    assert main.data["aiBrief"].startswith("a white cotton t-shirt")
    assert main.data["aspectRatio"] == "IMAGE_ASPECT_RATIO_PORTRAIT"
    extra = by_key["product_2"]
    assert extra.status == "done" and extra.data["mediaId"] == PHOTO_B

    # the extra photo feeds the same scenes as the main one
    def sources_of(key):
        return {e.source_id for e in edges if e.target_id == by_key[key].id}
    assert {main.id, extra.id} <= sources_of("s1")

    assert "a white cotton t-shirt with a small red logo" in by_key["s1"].data["prompt"]
    script = by_key["script"].data["prompt"]
    assert "Áo thun trắng logo đỏ — 199k" in script
    assert "- Cotton 100% thoáng mát" in script and "- Form rộng unisex" in script
    assert "https://shop.example/ao-thun" in script
    assert all(by_key[k].status == "idle" for k in ("s1", "v1", "model"))


def test_typed_product_phrase_beats_the_saved_description(client):
    p = _create(client, media_ids=[])
    r = client.post("/api/boards/from-template",
                    json={"template_id": "fashion_ad", "product_id": p["id"],
                          "inputs": {"product": "a navy linen shirt"}})
    assert r.status_code == 200, r.text
    with get_session() as s:
        nodes = s.exec(select(Node).where(Node.board_id == r.json()["id"])).all()
    s1 = next(n for n in nodes if n.data.get("title", "").startswith("Cảnh 1"))
    assert "a navy linen shirt" in s1.data["prompt"]
    product = next(n for n in nodes if n.type == "visual_asset")
    assert product.status == "idle" and "mediaId" not in product.data  # no photo saved yet


def test_unknown_product_is_404(client):
    r = client.post("/api/boards/from-template", json={"template_id": "fashion_ad", "product_id": 999})
    assert r.status_code == 404


def test_chat_agent_sees_products_and_builds_from_one(client):
    import asyncio

    from flowboard.db.models import Board
    from flowboard.services import chat_agent

    p = _create(client)
    with get_session() as s:
        b = Board(name="chat")
        s.add(b)
        s.commit()
        s.refresh(b)
        board_id = b.id

    ctx = chat_agent.build_board_context(board_id, "làm clip cho áo thun", [], [])
    assert f"product_id={p['id']}" in ctx and "Áo thun trắng logo đỏ" in ctx
    assert "Cotton 100% thoáng mát; Form rộng unisex" in ctx

    obs = asyncio.run(chat_agent._execute_tool(
        board_id, "build_from_template", {"product_id": str(p["id"]), "inputs": {"setting": "a rooftop"}}))
    assert obs["ok"] is True and obs["template_id"] == "fashion_ad"
    with get_session() as s:
        nodes = {n.short_id: n for n in s.exec(select(Node).where(Node.board_id == board_id)).all()}
    product = nodes[obs["nodes"]["product"]]
    assert product.status == "done" and product.data["mediaId"] == PHOTO_A
    assert "a rooftop" in nodes[obs["nodes"]["s1"]].data["prompt"]

    bad = asyncio.run(chat_agent._execute_tool(board_id, "build_from_template", {"product_id": 999}))
    assert bad["ok"] is False and "999" in bad["error"]
