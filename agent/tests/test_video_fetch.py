"""Pasted share blurbs → URL; Douyin share-page parsing; yt-dlp fallback."""
import json
from pathlib import Path

import httpx
import pytest

from flowboard.services import video_fetch as vf

SHARE = ("6.10 :6pm U@l.pq mQK:/ 07/28 合集:本视频由AI制作。带你体验坠入不同的星球。# 探索宇宙 # 沉浸式科普 "
         " https://v.douyin.com/rGpRrauR1Uc/ 复制此链接，打开Dou音搜索，直接观看视频！")


def test_extract_url_from_share_blurbs():
    assert vf.extract_url(SHARE) == "https://v.douyin.com/rGpRrauR1Uc/"
    assert vf.extract_url("xem cái này https://www.tiktok.com/@a/video/123?lang=vi. hay lắm") == "https://www.tiktok.com/@a/video/123?lang=vi"
    assert vf.extract_url("không có link") is None
    assert vf.is_douyin("https://v.douyin.com/abc/") and vf.is_douyin("https://www.iesdouyin.com/share/video/1/")
    assert not vf.is_douyin("https://www.tiktok.com/@a/video/1")


def _page(item):
    data = {"loaderData": {"video_(id)/page": {"videoInfoRes": {"item_list": [item]}}}}
    return f"<html><script>window._ROUTER_DATA = {json.dumps(data, ensure_ascii=False)}</script></html>"


ITEM = {"desc": "Bay vào các hành tinh", "video": {"duration": 15300, "play_addr": {"url_list": ["https://cdn/playwm/x.mp4"]}}}


def test_douyin_info_follows_the_short_link_and_retries_for_the_item():
    calls = []

    def handler(req: httpx.Request):
        calls.append(str(req.url))
        if req.url.host == "v.douyin.com":
            return httpx.Response(302, headers={"location": "https://www.iesdouyin.com/share/video/7638247731006535281/?x=1"})
        if len(calls) == 2:  # first share-page hit only sets cookies
            return httpx.Response(200, text="<html>cookie only</html>")
        return httpx.Response(200, text=_page(ITEM))

    c = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    info = vf.douyin_info("https://v.douyin.com/rGpRrauR1Uc/", client=c)
    assert info["id"] == "7638247731006535281" and info["title"] == "Bay vào các hành tinh"
    assert info["direct_url"] == "https://cdn/play/x.mp4" and info["duration"] == 15.3
    assert calls[-1] == "https://www.iesdouyin.com/share/video/7638247731006535281/"


def test_douyin_info_errors():
    blocked = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>verify</html>")), follow_redirects=True)
    with pytest.raises(vf.FetchError, match="chặn"):
        vf.douyin_info("https://www.douyin.com/video/7638247731006535281", client=blocked)
    photo = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=_page({"desc": "x", "video": {}}))), follow_redirects=True)
    with pytest.raises(vf.FetchError, match="không phải video"):
        vf.douyin_info("https://www.douyin.com/video/7638247731006535281", client=photo)


def test_fetch_video_uses_douyin_then_falls_back_to_ytdlp(monkeypatch, tmp_path):
    monkeypatch.setattr(vf, "douyin_info", lambda url: {"id": "1", "title": "Douyin clip", "duration": 3, "direct_url": "https://cdn/x.mp4"})
    monkeypatch.setattr(vf, "download_direct", lambda url, dest, **k: Path(dest).write_bytes(b"mp4"))
    path, title = vf.fetch_video(SHARE, "m1", tmp_path)
    assert path == tmp_path / "m1.mp4" and title == "Douyin clip"

    def boom(url):
        raise vf.FetchError("chặn")

    monkeypatch.setattr(vf, "douyin_info", boom)
    import flowboard.routes.reference_video as rv

    monkeypatch.setattr(rv, "_run_ytdlp", lambda url, mid, limit=None: (tmp_path / f"{mid}.mp4", "via yt-dlp", ""))
    assert vf.fetch_video(SHARE, "m2", tmp_path)[1] == "via yt-dlp"
    monkeypatch.setattr(rv, "_run_ytdlp", lambda url, mid, limit=None: (None, "", "Fresh cookies are needed"))
    with pytest.raises(vf.FetchError, match="Douyin: chặn · yt-dlp: Fresh cookies"):
        vf.fetch_video(SHARE, "m3", tmp_path)
    with pytest.raises(vf.FetchError, match="Không thấy link"):
        vf.fetch_video("chỉ có chữ", "m4", tmp_path)
    with pytest.raises(vf.FetchError, match="Link phải là"):
        vf.fetch_video("https://example.com/v.mp4", "m5", tmp_path)


def test_douyin_compilation_is_refused_before_downloading(monkeypatch, tmp_path):
    monkeypatch.setattr(vf, "douyin_info", lambda url: {"id": "1", "title": "合集", "duration": 3329.4, "direct_url": "https://cdn/x.mp4"})

    def no_download(*a, **k):
        raise AssertionError("must not download")

    monkeypatch.setattr(vf, "download_direct", no_download)
    with pytest.raises(vf.FetchError, match="55 phút — tối đa 10 phút"):
        vf.fetch_video(SHARE, "m6", tmp_path, max_duration_s=600)
