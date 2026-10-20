"""Drama clips: plan shaping, the board, the routes with Gemini faked, and
a still rendered into a clip by real ffmpeg (voice faked)."""
import asyncio
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Board, Node
from flowboard.services import drama, tts, video_export


def _plan(n=4):
    return {
        "title_vi": "Vụ ồn ào quán cà phê", "summary_vi": "Tóm tắt.", "hook_vi": "Chuyện gì đã xảy ra?", "tone": "tò mò",
        "beats": [
            {"title_vi": f"Đoạn {i}", "caption_vi": f"Tiêu đề {i}", "narration_vi": f"Lời kể đoạn {i}, theo bài viết.",
             "image_prompt_en": f"A moody cafe at night, beat {i}"} for i in range(1, n + 1)
        ],
    }


def test_normalize_bounds_and_defaults():
    p = drama.normalize({**_plan(14), "title_vi": ""}, {"url": "https://x.vn/a", "title": "Bài gốc"})
    assert len(p["beats"]) == drama.MAX_BEATS and p["title_vi"] == "Bài gốc" and p["source_url"] == "https://x.vn/a"
    with pytest.raises(drama.DramaError, match="at least"):
        drama.normalize(_plan(2))
    assert asyncio.run(drama.read_source(None, "Một câu chuyện đủ dài để làm clip drama cho mọi người xem nha."))["url"] is None
    with pytest.raises(drama.DramaError):
        asyncio.run(drama.read_source(None, "ngắn"))


def test_board_has_a_still_per_beat_with_narration_and_order():
    p = drama.normalize(_plan(4), {"url": "https://x.vn/a"})
    out = drama.build_board(p, name=None)
    assert out["name"] == "Drama — Vụ ồn ào quán cà phê"
    with get_session() as s:
        board = s.get(Board, out["id"])
        nodes = {n.short_id: n for n in s.exec(select(Node).where(Node.board_id == out["id"])).all()}
    qt = board.data["quicktool"]
    assert qt["template_id"] == "drama" and qt["source_url"] == "https://x.vn/a"
    assert [x["node"] for x in qt["sequence"]] == [out["nodes"][f"s{i}"] for i in range(1, 5)]
    s2 = nodes[out["nodes"]["s2"]]
    assert s2.type == "image" and s2.data["narration"] == "Lời kể đoạn 2, theo bài viết."
    assert s2.data["caption"] == "Tiêu đề 2" and "No text" in s2.data["prompt"]
    assert not any(n.type == "video" for n in nodes.values())


def test_routes_analyze_and_build(client, monkeypatch, tmp_path):
    # The drama API is parked (FLOWBOARD_DRAMA=1 mounts it); mount it here.
    from flowboard.main import app
    from flowboard.routes import drama as drama_route
    if not any(getattr(r, "path", "").startswith("/api/drama") for r in app.routes):
        app.include_router(drama_route.router)
    monkeypatch.setenv("FLOWBOARD_SECRETS_PATH", str(tmp_path / "s.json"))
    from flowboard.services.llm import secrets
    secrets.set_gemini_keys(["k1"])

    async def fake_plan(source, *, beats=None, model=None):
        assert "câu chuyện" in source["text"]
        return drama.normalize(_plan(beats or 8), source)

    with patch.object(drama, "plan", fake_plan):
        r = client.post("/api/drama/analyze", json={"text": "Đây là câu chuyện drama khá dài để kể cho mọi người nghe.", "beats": 5})
    assert r.status_code == 200, r.text
    plan = r.json()["plan"]
    assert len(plan["beats"]) == 5 and r.json()["source"]["url"] is None
    r = client.post("/api/drama/build", json={"plan": plan, "name": "Drama test"})
    assert r.status_code == 200 and r.json()["name"] == "Drama test" and len(r.json()["sequence"]) == 5
    assert client.post("/api/drama/analyze", json={"text": "x"}).status_code == 400


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_image_clip_renders_a_still_with_headline(tmp_path, monkeypatch):
    from PIL import Image

    img = tmp_path / "beat.png"
    Image.new("RGB", (900, 600), (60, 90, 140)).save(img)
    # Fake voice: a 1.2 s silent mp3-ish wav via ffmpeg, with word timings.
    voice = tmp_path / "voice.wav"
    import subprocess
    subprocess.run([shutil.which("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                    "-t", "1.2", str(voice)], check=True)

    async def fake_synth(text, voice_name, rate, style=None):
        return tts.Narration(voice, 1.2, [tts.Word(0.0, 0.5, "Theo"), tts.Word(0.5, 1.1, "bài")])

    monkeypatch.setattr(tts, "synthesize", fake_synth)
    opts = video_export.NarrationOptions(lines=["x"])
    dst = tmp_path / "out.mp4"
    rep = video_export._image_clip(shutil.which("ffmpeg"), img, "Theo bài", opts, dst, tmp_path, caption="Tiêu đề")
    assert rep.error is None, rep.error
    info = video_export.probe_clip(dst)
    assert info and (info.width, info.height) == video_export.STILL_SIZE and 1.8 <= info.duration <= 2.6
    ass = (tmp_path / "out.ass").read_text(encoding="utf-8")
    assert "Headline,,0,0,0,,Tiêu đề" in ass and "Theo bài" in ass


def test_export_items_mix_stills_and_clips(tmp_path, monkeypatch):
    """The worker hands stills to the still renderer and clips to the voice
    renderer, in the given order, with per-item audio modes."""
    from flowboard.db.models import Asset
    from flowboard.worker import processor

    still, clip = tmp_path / "a.png", tmp_path / "b.mp4"
    still.write_bytes(b"\x89PNG"); clip.write_bytes(b"\x00")
    with get_session() as s:
        s.add(Asset(kind="image", uuid_media_id="aa000000-0000-4000-8000-000000000001", local_path=str(still), mime="image/png"))
        s.add(Asset(kind="video", uuid_media_id="bb000000-0000-4000-8000-000000000002", local_path=str(clip), mime="video/mp4"))
        s.commit()
    seen = {}

    def fake_export(asset_ids, *, smooth60, narration=None, items=None, **_bgm):
        seen["items"] = items
        seen["lines"] = narration.lines if narration else None
        return "out-id", None, {"voiced": True}

    with patch("flowboard.services.video_export.export_video", fake_export):
        result, err = asyncio.run(processor._handle_export_video({
            "items": [
                {"media_id": "bb000000-0000-4000-8000-000000000002", "kind": "video", "narration": "", "original_audio": "keep"},
                {"media_id": "aa000000-0000-4000-8000-000000000001", "narration": "Lời kể", "caption": "Tít"},
            ],
            "voice": "vi-VN-NamMinhNeural",
        }))
    assert err is None and result["media_ids"] == ["out-id"]
    kinds = [(it.kind, it.narration, it.caption, it.original_audio) for it in seen["items"]]
    assert kinds == [("video", "", "", "keep"), ("image", "Lời kể", "Tít", None)]
    assert seen["lines"] == ["", "Lời kể"]
