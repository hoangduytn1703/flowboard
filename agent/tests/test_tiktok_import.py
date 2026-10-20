"""TikTok import: the extension handshake decides whether the scrape is even
attempted, so a stale build fails at once instead of after the timeout."""
import asyncio
import json

import pytest

from flowboard.services import tiktok_import
from flowboard.services.flow_client import FlowClient


class FakeWs:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


def _client(version):
    c = FlowClient()
    c.set_extension(FakeWs())
    asyncio.run(c.handle_message({"type": "extension_ready", "flowKeyPresent": False, "version": version}))
    return c


def test_ready_records_the_extension_version_and_disconnect_clears_it():
    c = _client("0.2.0")
    assert c.extension_version == "0.2.0"
    c.clear_extension()
    assert c.extension_version is None
    assert _client(None).extension_version is None


@pytest.mark.parametrize("version", [None, "0.1.9", "0.1"])
def test_scrape_refuses_an_old_extension_at_once(monkeypatch, version):
    c = _client(version)
    monkeypatch.setattr(tiktok_import, "get_flow_client", lambda: c)
    with pytest.raises(tiktok_import.TikTokImportError, match="Reload"):
        asyncio.run(tiktok_import.scrape())
    assert not c._ws.sent  # nothing was sent to the extension


def test_scrape_sends_the_command_to_a_current_extension(monkeypatch):
    c = _client("0.2.0")
    monkeypatch.setattr(tiktok_import, "get_flow_client", lambda: c)

    async def fake_send(method, params, timeout=None):
        assert method == "scrape_page" and timeout == tiktok_import.SCRAPE_TIMEOUT_S
        return {"status": 404, "error": "NO_TIKTOK_TAB"}

    monkeypatch.setattr(c, "_send", fake_send)
    with pytest.raises(tiktok_import.TikTokImportError, match="tab TikTok"):
        asyncio.run(tiktok_import.scrape())


def test_scrape_timeout_message_tells_how_to_recover(monkeypatch):
    c = _client("0.2.0")
    monkeypatch.setattr(tiktok_import, "get_flow_client", lambda: c)

    async def fake_send(method, params, timeout=None):
        return {"error": "timeout"}

    monkeypatch.setattr(c, "_send", fake_send)
    with pytest.raises(tiktok_import.TikTokImportError, match="45 giây"):
        asyncio.run(tiktok_import.scrape())


@pytest.mark.parametrize("title, category", [
    ("Ốp lưng iPhone 15 trong suốt in mèo", "grocery"),
    ("Kệ mica để bàn 3 tầng đựng mỹ phẩm", "grocery"),
    ("Cáp sạc nhanh Type-C 1m bọc dù", "grocery"),
    ("Tai nghe bluetooth chống ồn", "grocery"),
    ("Móc treo tường dán tường chịu lực", "grocery"),
    ("Hộp đựng bút để bàn 3 ngăn", "grocery"),
    ("Nồi chiên không dầu 5L", "home"),
    ("Chảo chống dính đáy từ 28cm", "home"),
    ("Máy xay sinh tố cầm tay", "home"),
    ("Máy hút bụi không dây", "home"),
    ("Quạt tích điện mini để bàn", "home"),
    ("Bếp từ đơn cảm ứng", "home"),
    ("Máy lọc nước RO 9 lõi", "home"),
    ("Đèn ngủ cảm ứng", "home"),
    ("Áo thun oversize", "fashion"),
    ("Son kem lì", "cosmetics"),
    ("Bánh tráng trộn", "food"),
    ("Thứ gì đó lạ", "other"),
])
def test_guess_category_knows_grocery_and_home(title, category):
    assert tiktok_import.guess_category(title) == category
