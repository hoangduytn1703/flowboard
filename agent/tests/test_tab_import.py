""""Nhập từ tab đang mở": one button for TikTok and Shopee, many tabs at once."""
import json

import pytest

from flowboard.services import product_link as pl
from flowboard.services import tab_import, tiktok_import

SHOPEE_PRODUCT = "https://shopee.vn/Ao-Mua-Dang-Dai-i.123456.987654321?sp_atk=x"
SHOPEE_SEARCH = "https://shopee.vn/search?keyword=ao"
TIKTOK_PDP = "https://shop.tiktok.com/vn/pdp/1729384756?source=share"
TIKTOK_SHOWCASE = "https://www.tiktok.com/@shop.cua.toi/showcase"
TIKTOK_VIDEO = "https://www.tiktok.com/@ai.do/video/7400000000000000000"


def _product_read(name, url, **over):
    data = {
        "ready": True, "url": url, "tabUrl": url, "tabTitle": f"{name} | Shopee Việt Nam",
        "title": f"{name} | Shopee Việt Nam", "description": "", "ogImage": "https://down-vn.img.susercontent.com/file/x_tn",
        "images": [], "ld": [{"@type": "Product", "name": name, "offers": {"price": "79000"}}],
        "text": f"{name}\n₫79.000\n" + "Mô tả sản phẩm " * 100,
    }
    data.update(over)
    return data


class FakeClient:
    """The extension: ``tabs`` for list_shop_tabs, ``reads[tab_id]`` for read_tab,
    ``cards[tab_id]`` for scrape_page."""

    def __init__(self, tabs, reads=None, cards=None, version="0.5.0"):
        self.connected, self.extension_version = True, version
        self.tabs, self.reads, self.cards, self.sent = tabs, reads or {}, cards or {}, []

    async def _send(self, method, params, timeout=None):
        self.sent.append((method, params))
        if method == "list_shop_tabs":
            return {"status": 200, "data": json.dumps({"tabs": self.tabs})}
        if method == "read_tab":
            r = self.reads.get(params["tabId"])
            return r if "error" in (r or {}) else {"status": 200, "data": json.dumps(r)}
        if method == "scrape_page":
            tab = next(t for t in self.tabs if t["id"] == params["tabId"])
            return {"status": 200, "data": json.dumps({"tabUrl": tab["url"], "items": self.cards.get(params["tabId"], [])})}
        raise AssertionError(method)


def _tab(id, url, title="", active=False, last=0):
    return {"id": id, "url": url, "title": title or url, "active": active, "lastAccessed": last}


@pytest.fixture
def fake(monkeypatch):
    def install(client):
        import flowboard.services.flow_client as fc
        monkeypatch.setattr(fc, "get_flow_client", lambda: client)
        monkeypatch.setattr(tab_import, "get_flow_client", lambda: client)
        monkeypatch.setattr(tiktok_import, "get_flow_client", lambda: client)
        monkeypatch.setattr(pl.gemini_api, "configured", lambda: True)
        monkeypatch.setattr(tiktok_import, "start_photo_task", lambda created: None)

        async def fake_generate(prompt, **kw):
            name = "Áo mưa dáng dài" if "Áo Mưa" in prompt else "Tai nghe bluetooth" if "Tai Nghe" in prompt else "Son kem lì"
            return json.dumps({"name": name, "description": "x", "category": "other", "price": "79.000đ",
                               "selling_points": "", "gender": "unknown"})

        monkeypatch.setattr(pl.gemini_api, "generate_text", fake_generate)
        return client
    return install


@pytest.mark.parametrize("url, platform, kind, importable", [
    (SHOPEE_PRODUCT, "shopee", "product", True),
    ("https://shopee.vn/product/123/456", "shopee", "product", True),
    (SHOPEE_SEARCH, "shopee", "other", False),
    (TIKTOK_PDP, "tiktok", "product", True),
    (TIKTOK_SHOWCASE, "tiktok", "list", True),
    ("https://affiliate.tiktok.com/connection/creator", "tiktok", "list", True),
    (TIKTOK_VIDEO, "tiktok", "other", True),
    ("https://example.com/a", "", "other", False),
])
def test_classify_knows_the_shop_and_the_page(url, platform, kind, importable):
    info = tab_import.classify(url)
    assert (info["platform"], info["kind"], info["importable"]) == (platform, kind, importable)


def test_open_tabs_lists_and_orders_them(client, fake):
    fake(FakeClient([
        _tab(1, SHOPEE_SEARCH, last=50), _tab(2, TIKTOK_PDP, last=10), _tab(3, SHOPEE_PRODUCT, active=True, last=1),
        _tab(4, TIKTOK_VIDEO, last=99),
    ]))
    r = client.get("/api/products/open-tabs")
    assert r.status_code == 200, r.text
    tabs = r.json()["tabs"]
    assert [t["id"] for t in tabs] == [3, 4, 1, 2]  # the tab in view first, then most recently used
    by_id = {t["id"]: t for t in tabs}
    assert by_id[3]["suggested"] and by_id[2]["suggested"]
    assert not by_id[1]["importable"] and not by_id[4]["suggested"]


def test_old_extension_is_told_to_reload(client, fake):
    c = fake(FakeClient([], version="0.4.1"))
    r = client.get("/api/products/open-tabs")
    assert r.status_code == 400 and "0.5.0" in r.json()["detail"] and c.sent == []


def test_imports_many_tabs_of_both_shops_at_once(client, fake):
    other = "https://shopee.vn/Tai-Nghe-i.9.8"
    c = fake(FakeClient(
        tabs=[_tab(1, SHOPEE_PRODUCT), _tab(2, other), _tab(3, TIKTOK_SHOWCASE), _tab(4, SHOPEE_SEARCH)],
        reads={1: _product_read("Áo Mưa Dáng Dài", SHOPEE_PRODUCT), 2: _product_read("Tai Nghe Bluetooth", other)},
        cards={3: [{"title": "Son kem lì mịn môi", "price": "99.000đ", "url": "https://shop.tiktok.com/view/product/1", "image": ""},
                   {"title": "Bình giữ nhiệt 500ml", "price": "120.000đ", "url": "https://shop.tiktok.com/view/product/2", "image": ""}]},
    ))
    r = client.post("/api/products/import-tabs", json={"tab_ids": [1, 2, 3, 4]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tabs"] == 3  # the Shopee search tab is not a product page: left out
    assert body["created"] == 4 and body["failed"] == 0
    assert {m for m, _ in c.sent} == {"list_shop_tabs", "read_tab", "scrape_page"}
    names = sorted(p["name"] for p in client.get("/api/products").json())
    assert names == ["Bình giữ nhiệt 500ml", "Son kem lì mịn môi", "Tai nghe bluetooth", "Áo mưa dáng dài"]
    notes = {p["name"]: p["notes"] for p in client.get("/api/products").json()}
    assert "Nhập từ Shopee" in notes["Áo mưa dáng dài"] and "Nhập từ TikTok" in notes["Son kem lì mịn môi"]
    # the same tabs again: everything is already in the library
    again = client.post("/api/products/import-tabs", json={"tab_ids": [1, 2, 3]}).json()
    assert again["created"] == 0 and again["skipped"] == 4


def test_a_failing_tab_does_not_stop_the_others(client, fake):
    fake(FakeClient(
        tabs=[_tab(1, SHOPEE_PRODUCT), _tab(2, "https://shopee.vn/Hop-i.5.6")],
        reads={1: _product_read("Áo Mưa Dáng Dài", SHOPEE_PRODUCT),
               2: _product_read("x", "https://shopee.vn/buyer/login", tabUrl="https://shopee.vn/buyer/login", ld=[], text="Cần đăng nhập")},
    ))
    body = client.post("/api/products/import-tabs", json={"tab_ids": [1, 2]}).json()
    by_tab = {r["tab_id"]: r for r in body["results"]}
    assert by_tab[1]["ok"] and by_tab[1]["created"] == 1
    assert not by_tab[2]["ok"] and "đăng nhập" in by_tab[2]["error"]
    assert body["created"] == 1 and body["failed"] == 1


def test_a_closed_tab_is_reported(client, fake):
    fake(FakeClient(tabs=[_tab(1, SHOPEE_PRODUCT)], reads={1: {"error": "TAB_CLOSED"}}))
    body = client.post("/api/products/import-tabs", json={"tab_ids": [1]}).json()
    assert body["failed"] == 1 and "đã đóng" in body["results"][0]["error"]


def test_tabs_no_longer_open_are_refused(client, fake):
    fake(FakeClient(tabs=[_tab(1, SHOPEE_SEARCH)]))
    r = client.post("/api/products/import-tabs", json={"tab_ids": [1, 77]})
    assert r.status_code == 400 and "quét lại" in r.json()["detail"]


def test_tiktok_product_tab_strips_the_shop_suffix(client, fake):
    read = _product_read("Tai Nghe Bluetooth", TIKTOK_PDP, title="Tai Nghe Bluetooth | TikTok Shop",
                         tabTitle="Tai Nghe Bluetooth | TikTok Shop", ld=[])
    fake(FakeClient(tabs=[_tab(5, TIKTOK_PDP)], reads={5: read}))
    body = client.post("/api/products/import-tabs", json={"tab_ids": [5]}).json()
    assert body["created"] == 1, body
    saved = client.get("/api/products").json()[0]
    assert saved["link"] == "https://shop.tiktok.com/vn/pdp/1729384756"  # tracking query dropped
