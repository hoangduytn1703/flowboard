"""Affiliate: product aff_link / shop with duplicate guard, and the post's first comment."""
import json

import pytest

from flowboard.services import post_writer, product_link


def test_affiliate_link_detection():
    assert product_link.affiliate_link("https://s.shopee.vn/3qNyfcNZlD") == "https://s.shopee.vn/3qNyfcNZlD"
    assert product_link.affiliate_link("https://vt.tiktok.com/ZSabc/") == "https://vt.tiktok.com/ZSabc/"
    assert product_link.affiliate_link("https://shopee.vn/product/1/2") == ""


def test_products_keep_aff_link_and_shop_and_refuse_duplicates(client):
    a = client.post("/api/products", json={"name": "Gối bầu", "category": "home", "aff_link": "xem https://s.shopee.vn/3qNyfcNZlD/ nha",
                                           "shop": "PeeWees Official"}).json()
    assert a["aff_link"] == "https://s.shopee.vn/3qNyfcNZlD" and a["shop"] == "PeeWees Official"
    dup = client.post("/api/products", json={"name": "Gối bầu bản 2", "category": "home", "aff_link": "https://s.shopee.vn/3qNyfcNZlD"})
    assert dup.status_code == 409 and "Gối bầu" in dup.json()["detail"] and "link tiếp thị" in dup.json()["detail"]
    b = client.post("/api/products", json={"name": "Đai bầu", "category": "home", "aff_link": "https://vt.tiktok.com/ZSx1/", "shop": "PeeWees Official"}).json()
    # moving b onto a's link is refused too; editing a itself is fine
    assert client.patch(f"/api/products/{b['id']}", json={"aff_link": a["aff_link"]}).status_code == 409
    assert client.patch(f"/api/products/{a['id']}", json={"aff_link": a["aff_link"], "price": "249k"}).json()["price"] == "249k"
    shops = client.get("/api/products/shops").json()
    assert shops == [{"shop": "PeeWees Official", "products": 2, "with_aff": 2}]
    # the plain page link is not unique (several products can share a shop page)
    client.post("/api/products", json={"name": "A", "category": "home", "link": "https://shopee.vn/x-i.1.2"})
    assert client.post("/api/products", json={"name": "B", "category": "home", "link": "https://shopee.vn/x-i.1.2"}).status_code == 200


@pytest.mark.asyncio
async def test_writer_puts_the_affiliate_link_in_the_first_comment(monkeypatch):
    seen = {}

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        seen["prompt"], seen["system"] = prompt, system_prompt
        return json.dumps({"reply": "ok", "body": "Bài. Link ở bình luận đầu nha.", "hashtags": [],
                           "image_prompts": [], "first_comment": "Dạ em gửi các mom tham khảo gối bầu ở đây nha 🥰"})

    monkeypatch.setattr(post_writer, "run_llm", fake_llm)
    product = {"name": "Gối bầu", "aff_link": "https://s.shopee.vn/3qNyfcNZlD", "shop": "PeeWees Official"}
    out = await post_writer.write_post({"kind": "review"}, product=product)
    assert "AFFILIATE LINK (goes ONLY in first_comment" in seen["prompt"] and "Shop: PeeWees Official" in seen["prompt"]
    assert "first_comment" in seen["system"]
    # the model forgot the link → it is appended
    assert out["first_comment"] == "Dạ em gửi các mom tham khảo gối bầu ở đây nha 🥰\nhttps://s.shopee.vn/3qNyfcNZlD"
    out = await post_writer.write_post({"kind": "review"})  # no product → the model's invented comment is dropped
    assert out["first_comment"] == ""
    out = await post_writer.write_post({"kind": "review"}, current={"body": "x", "first_comment": "của tôi"}, message="ngắn hơn")
    assert out["first_comment"] == "của tôi"  # …but a comment the user typed stays


def test_post_routes_carry_first_comment(client, monkeypatch):
    async def fake_llm(*a, **k):
        return json.dumps({"reply": "ok", "body": "Bài", "hashtags": [], "image_prompts": [], "first_comment": ""})

    monkeypatch.setattr(post_writer, "run_llm", fake_llm)
    p = client.post("/api/products", json={"name": "Gối bầu", "category": "home", "aff_link": "https://s.shopee.vn/abc"}).json()
    r = client.post("/api/posts/write", json={"brief": {"kind": "review"}, "product_id": p["id"]}).json()
    assert r["post"]["first_comment"].endswith("https://s.shopee.vn/abc")
    saved = client.post("/api/posts", json={"body": "Bài", "first_comment": "Link đây nha\nhttps://s.shopee.vn/abc", "product_id": p["id"]}).json()
    assert saved["first_comment"].startswith("Link đây nha")
    assert client.get("/api/posts").json()[0]["first_comment"] == saved["first_comment"]


def test_aff_migration(tmp_path):
    from sqlalchemy import create_engine, inspect

    from flowboard.db import ensure_product_aff_columns

    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.connect() as conn:
        conn.exec_driver_sql("CREATE TABLE product (id INTEGER PRIMARY KEY, name VARCHAR)")
        conn.exec_driver_sql("CREATE TABLE post (id INTEGER PRIMARY KEY, body VARCHAR)")
        conn.commit()
    assert ensure_product_aff_columns(eng) is True and ensure_product_aff_columns(eng) is False
    with eng.connect() as conn:
        assert {"aff_link", "shop"} <= {c["name"] for c in inspect(conn).get_columns("product")}
        assert "first_comment" in {c["name"] for c in inspect(conn).get_columns("post")}
