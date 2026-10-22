"""Shopee product links: read through the Chrome extension, not fetched."""
import asyncio
import json

import pytest

from flowboard.services import product_link as pl


SHOPEE = "https://shopee.vn/Ao-Mua-Dang-Dai-i.123456.987654321?sp_atk=abc&xptdk=def"


def test_shopee_hosts_go_through_the_browser():
    assert pl.needs_browser(SHOPEE)
    assert pl.needs_browser("https://s.shopee.vn/AbCdEf")
    assert pl.needs_browser("https://shp.ee/xyz")
    assert not pl.needs_browser("https://shop.tiktok.com/vn/pdp/1")
    assert pl.clean_link(SHOPEE) == "https://shopee.vn/Ao-Mua-Dang-Dai-i.123456.987654321"
    assert pl._bigger_image("https://down-vn.img.susercontent.com/file/vn-11134207-abc_tn") == \
        "https://down-vn.img.susercontent.com/file/vn-11134207-abc"


def _browser_read(**over):
    data = {
        "ready": True, "url": "https://shopee.vn/Ao-Mua-i.1.2", "title": "Áo Mưa Dáng Dài | Shopee Việt Nam",
        "description": "", "ogImage": "", "images": [{"src": "https://down-vn.img.susercontent.com/file/big", "w": 800, "h": 800}],
        "ld": [{"@context": "http://schema.org", "@type": "Product", "name": "Áo Mưa Dáng Dài Vải Oxford",
                "description": "Áo mưa trùm kín, vải Oxford dày", "image": ["https://down-vn.img.susercontent.com/file/main_tn"],
                "offers": {"@type": "AggregateOffer", "lowPrice": "79000", "highPrice": "99000", "priceCurrency": "VND"},
                "brand": {"@type": "Brand", "name": "VIONO"}}],
        "text": "Áo Mưa Dáng Dài Vải Oxford\n₫79.000 - ₫99.000\n" + "Mô tả sản phẩm " * 200,
    }
    data.update(over)
    return data


class FakeClient:
    def __init__(self, version="0.4.0", reply=None, connected=True):
        self.extension_version, self.connected, self.reply, self.sent = version, connected, reply, []

    async def _send(self, method, params, timeout=None):
        self.sent.append((method, params))
        return self.reply


def _with_client(monkeypatch, client):
    import flowboard.services.flow_client as fc
    monkeypatch.setattr(fc, "get_flow_client", lambda: client)


def test_reads_the_product_from_the_extension(monkeypatch):
    client = FakeClient(reply={"status": 200, "data": json.dumps(_browser_read())})
    _with_client(monkeypatch, client)
    page = asyncio.run(pl.get_page(SHOPEE))
    assert client.sent[0][0] == "read_page"
    assert page["title"] == "Áo Mưa Dáng Dài Vải Oxford"  # JSON-LD name, not the tab title
    assert page["image_url"] == "https://down-vn.img.susercontent.com/file/main_tn"
    assert "lowPrice: 79000" in page["text"] and "brand: VIONO" in page["text"]


def test_falls_back_to_the_tab_title_and_largest_image(monkeypatch):
    read = _browser_read(ld=[])
    _with_client(monkeypatch, FakeClient(reply={"status": 200, "data": json.dumps(read)}))
    page = asyncio.run(pl.get_page(SHOPEE))
    assert page["title"] == "Áo Mưa Dáng Dài"  # " | Shopee Việt Nam" dropped
    assert page["image_url"] == "https://down-vn.img.susercontent.com/file/big"


@pytest.mark.parametrize("client, msg", [
    (FakeClient(connected=False), "chưa kết nối"),
    (FakeClient(version="0.3.0"), "0.4.0"),
    (FakeClient(reply={"status": 200, "data": json.dumps({"blocked": True, "url": "https://shopee.vn/verify/traffic"})}), "đăng nhập"),
    (FakeClient(reply={"status": 200, "data": json.dumps(_browser_read(ld=[], title="Shopee", text="Cần đăng nhập\nĐăng nhập để tiếp tục"))}), "đăng nhập"),
    (FakeClient(reply={"error": "timeout"}), "không trả lời"),
    (FakeClient(reply={"status": 200, "data": json.dumps({"timeout": True})}), "chưa hiện xong"),
])
def test_clear_errors(monkeypatch, client, msg):
    _with_client(monkeypatch, client)
    with pytest.raises(pl.ProductLinkError, match=msg):
        asyncio.run(pl.get_page(SHOPEE))


def test_extract_product_from_a_shopee_link(monkeypatch):
    _with_client(monkeypatch, FakeClient(reply={"status": 200, "data": json.dumps(_browser_read())}))

    async def fake_generate(prompt, **kw):
        assert "Áo Mưa Dáng Dài Vải Oxford" in prompt
        return json.dumps({"name": "Áo mưa dáng dài vải Oxford", "description": "a long grey raincoat",
                           "category": "fashion", "price": "79.000đ", "selling_points": "Vải Oxford dày"})

    monkeypatch.setattr(pl.gemini_api, "generate_text", fake_generate)
    r = asyncio.run(pl.extract_product(SHOPEE))
    assert r["draft"]["link"] == "https://shopee.vn/Ao-Mua-i.1.2"
    assert r["image_url"] == "https://down-vn.img.susercontent.com/file/main"  # _tn removed
