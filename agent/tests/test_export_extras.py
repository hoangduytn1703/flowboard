"""Export-step extras: the voice preview route (tts mocked), the music
upload + mix (real ffmpeg on a synthetic track), the cover render (real
ffmpeg on a Pillow image) and the worker's bgm plumbing."""
import asyncio
import io
import shutil
import subprocess
import wave
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Asset, Board
from flowboard.services import media as media_service
from flowboard.services import tts, video_export
from flowboard.worker import processor

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not on PATH")


def _wav_bytes(seconds: float = 2.0, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


def _silent_clip(path: Path, seconds: float = 2.0, with_audio: bool = True) -> Path:
    """A tiny real mp4 (black frames, optional silent track) via lavfi."""
    cmd = [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s=320x568:d={seconds}:r=24"]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={seconds}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if with_audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd += [str(path)]
    subprocess.run(cmd, check=True, timeout=120)
    return path


def _png(path: Path, size=(640, 480)) -> Path:
    from PIL import Image
    Image.new("RGB", size, (40, 90, 160)).save(path)
    return path


def _register(path: Path, kind: str, mime: str) -> tuple[int, str]:
    with get_session() as s:
        row = Asset(kind=kind, uuid_media_id=path.stem, local_path=str(path), mime=mime)
        s.add(row)
        s.commit()
        s.refresh(row)
        return row.id, row.uuid_media_id


# ── 1. voice preview ──────────────────────────────────────────────────────

def test_voice_preview_route_speaks_the_sample_and_serves_it(client, tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "TTS_DIR", tmp_path)
    calls = []

    async def fake_synth(text, voice=tts.DEFAULT_VOICE, rate=0, style=None):
        calls.append((text, voice, rate, style))
        out = tmp_path / ("abcdef0123456789abcd" + (".wav" if tts.is_gemini_voice(voice) else ".mp3"))
        out.write_bytes(b"ID3" if out.suffix == ".mp3" else _wav_bytes(0.2))
        return tts.Narration(out, 1.0, [])

    with patch.object(tts, "synthesize", fake_synth):
        r = client.post("/api/llm/voices/preview", json={"voice": "vi-VN-NamMinhNeural", "style": "kịch tính"})
        assert r.status_code == 200, r.text
        assert r.json()["url"] == "/api/llm/voices/preview/abcdef0123456789abcd.mp3"
        # Edge voices ignore the style; Gemini voices get it.
        assert calls[-1] == (tts.PREVIEW_TEXT, "vi-VN-NamMinhNeural", 0, None)
        r = client.post("/api/llm/voices/preview", json={"voice": "gemini:Kore", "style": "kịch tính"})
        assert r.status_code == 200 and r.json()["url"].endswith(".wav")
        assert calls[-1] == (tts.PREVIEW_TEXT, "gemini:Kore", 0, "kịch tính")

    served = client.get("/api/llm/voices/preview/abcdef0123456789abcd.mp3")
    assert served.status_code == 200 and served.headers["content-type"].startswith("audio/mpeg")
    assert served.content == b"ID3"
    # Only hex ids with an audio extension are served from the tts dir.
    assert client.get("/api/llm/voices/preview/..%2Fsecret.mp3").status_code in (400, 404)
    assert client.get("/api/llm/voices/preview/zzzz.mp3").status_code == 400
    assert client.get("/api/llm/voices/preview/abcdef0123456789abce.mp3").status_code == 404
    assert client.post("/api/llm/voices/preview", json={"voice": "nope"}).status_code == 400


def test_voice_preview_reports_tts_failure(client, tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "TTS_DIR", tmp_path)

    async def boom(*a, **k):
        raise tts.TTSError("edge-tts failed: offline")

    with patch.object(tts, "synthesize", boom):
        r = client.post("/api/llm/voices/preview", json={"voice": tts.DEFAULT_VOICE})
    assert r.status_code == 502 and "offline" in r.text


# ── 2. background music ───────────────────────────────────────────────────

def test_music_upload_registers_an_audio_asset(client, tmp_path, monkeypatch):
    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path)
    r = client.post("/api/llm/music", files={"file": ("nhac nen.wav", _wav_bytes(1.0), "audio/wav")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "nhac nen.wav" and body["mime"] == "audio/wav"
    with get_session() as s:
        row = s.exec(select(Asset).where(Asset.uuid_media_id == body["media_id"])).first()
    assert row.kind == "audio" and Path(row.local_path).is_file() and row.local_path.endswith(".wav")
    # A browser that labels .m4a as octet-stream is trusted by extension.
    r = client.post("/api/llm/music", files={"file": ("beat.m4a", b"\x00" * 16, "application/octet-stream")})
    assert r.status_code in (200, 415)  # ffprobe may reject the junk bytes; the type itself is accepted
    assert client.post("/api/llm/music", files={"file": ("x.txt", b"hi", "text/plain")}).status_code == 415
    assert client.post("/api/llm/music", files={"file": ("x.mp3", b"", "audio/mpeg")}).status_code == 400
    big = b"\x00" * (20 * 1024 * 1024 + 1)
    assert client.post("/api/llm/music", files={"file": ("big.mp3", big, "audio/mpeg")}).status_code == 413


@needs_ffmpeg
def test_mix_background_music_loops_trims_and_keeps_video(tmp_path):
    clip = _silent_clip(tmp_path / "clip.mp4", 3.0)
    music = tmp_path / "music.wav"
    music.write_bytes(_wav_bytes(1.0))  # shorter than the clip: must loop
    out = tmp_path / "out.mp4"
    assert video_export.mix_background_music(clip, music, out, 0.25) is None
    info = video_export.probe_clip(out)
    assert info is not None and info.has_audio and abs(info.duration - 3.0) < 0.3
    assert (info.width, info.height) == (320, 568)

    # A join with no audio track at all gets the music as its only sound.
    mute = _silent_clip(tmp_path / "mute.mp4", 2.0, with_audio=False)
    out2 = tmp_path / "out2.mp4"
    assert video_export.mix_background_music(mute, music, out2, 0.15) is None
    info2 = video_export.probe_clip(out2)
    assert info2 is not None and info2.has_audio and abs(info2.duration - 2.0) < 0.3


@needs_ffmpeg
def test_export_video_mixes_bgm_on_the_plain_join_path(tmp_path):
    clip = _silent_clip(tmp_path / "joined.mp4", 2.0)
    joined_id, _ = _register(clip, "video", "video/mp4")
    music = tmp_path / "m.wav"
    music.write_bytes(_wav_bytes(1.0))
    bgm_id, _ = _register(music, "audio", "audio/wav")
    with patch("flowboard.services.video_concat.concat_video_assets", return_value=(joined_id, None)):
        media, err, report = video_export.export_video([joined_id], smooth60=False, bgm_asset_id=bgm_id, bgm_volume=0.2)
    assert err is None and report["bgm"] is True and report["bgm_error"] is None
    assert media != "joined"  # a new asset carries the mixed file
    with get_session() as s:
        row = s.exec(select(Asset).where(Asset.uuid_media_id == media)).first()
    assert row is not None and Path(row.local_path).name.startswith("bgm_")


def test_export_video_keeps_the_join_when_the_track_is_gone(tmp_path):
    clip = tmp_path / "joined.mp4"
    clip.write_bytes(b"\x00")
    joined_id, joined_media = _register(clip, "video", "video/mp4")
    with patch("flowboard.services.video_concat.concat_video_assets", return_value=(joined_id, None)):
        media, err, report = video_export.export_video([joined_id], smooth60=False, bgm_asset_id=99999)
    assert err is None and media == joined_media
    assert report["bgm"] is False and report["bgm_error"].startswith("asset_not_found")


def test_worker_passes_bgm_to_the_export(tmp_path):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"\x00")
    _, clip_media = _register(clip, "video", "video/mp4")
    music = tmp_path / "m.mp3"
    music.write_bytes(b"\x00")
    bgm_id, bgm_media = _register(music, "audio", "audio/mpeg")
    seen = {}

    def fake_export(asset_ids, *, smooth60, narration=None, items=None, bgm_asset_id=None, bgm_volume=None):
        seen["bgm"] = (bgm_asset_id, bgm_volume)
        return "joined-media-id", None, {"voiced": False, "bgm": bgm_asset_id is not None}

    with patch("flowboard.services.video_export.export_video", fake_export):
        result, err = asyncio.run(processor._handle_export_video(
            {"source_media_ids": [clip_media], "bgm_media_id": bgm_media, "bgm_volume": "0.08"}))
    assert err is None and seen["bgm"] == (bgm_id, 0.08) and result["report"]["bgm"] is True

    # A track that is no longer on disk does not block the export.
    with patch("flowboard.services.video_export.export_video", fake_export):
        result, err = asyncio.run(processor._handle_export_video(
            {"source_media_ids": [clip_media], "bgm_media_id": "deadbeefdeadbeefdeadbeefdeadbeef"}))
    assert err is None and seen["bgm"] == (None, video_export.BGM_DEFAULT_VOLUME)
    assert result["report"]["bgm_error"].startswith("bgm_unavailable:")


# ── 3. cover image ────────────────────────────────────────────────────────

def test_write_cover_ass_has_title_and_subtitle_styles(tmp_path):
    out = tts.write_cover_ass("Áo thun  cotton\nmát", tmp_path / "c.ass", width=1080, height=1920,
                              subtitle="Giảm 50%", style="white")
    text = out.read_text(encoding="utf-8")
    assert "Style: Cover,Arial,109,&H00FFFFFF" in text and "Style: CoverSub,Arial,56" in text
    assert "Cover,,0,0,0,,Áo thun cotton mát" in text and "CoverSub,,0,0,0,,Giảm 50%" in text


@needs_ffmpeg
def test_render_cover_makes_a_portrait_png(tmp_path):
    from PIL import Image
    src = _png(tmp_path / "scene.png")
    out = tmp_path / "cover.png"
    err = video_export.render_cover(src, out, "Áo thun cotton dày dặn mặc cực mát – giảm 50% hôm nay",
                                    subtitle="Mua ngay kẻo hết")
    assert err is None, err
    with Image.open(out) as im:
        assert im.size == (1080, 1920)
        # The band darkens the bottom; the top keeps the scene colour.
        top, bottom = im.getpixel((540, 200)), im.getpixel((20, 1900))
    assert top[2] > 120 and sum(bottom[:3]) < 90
    assert not out.with_suffix(".ass").exists()  # scratch file cleaned up
    assert video_export.render_cover(src, tmp_path / "x.png", "   ") == "empty title"


@needs_ffmpeg
def test_cover_route_registers_an_image_asset(client, tmp_path, monkeypatch):
    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path)
    scene = _png(tmp_path / "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png")
    _register(scene, "image", "image/png")
    with get_session() as s:
        board = Board(name="Áo thun SAIGON")
        s.add(board)
        s.commit()
        s.refresh(board)
        board_id = board.id

    r = client.post(f"/api/boards/{board_id}/cover",
                    json={"media_id": scene.stem, "title": "Áo thun SAIGON", "subtitle": "Giảm 50%", "style": "red"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["width"] == 1080 and body["url"] == f"/media/{body['media_id']}"
    with get_session() as s:
        row = s.exec(select(Asset).where(Asset.uuid_media_id == body["media_id"])).first()
    assert row.kind == "image" and row.mime == "image/png" and Path(row.local_path).stat().st_size > 1000
    served = client.get(body["url"])
    assert served.status_code == 200 and served.headers["content-type"] == "image/png"

    assert client.post("/api/boards/99999/cover", json={"media_id": scene.stem, "title": "x"}).status_code == 404
    assert client.post(f"/api/boards/{board_id}/cover",
                       json={"media_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "title": "x"}).status_code == 404
    assert client.post(f"/api/boards/{board_id}/cover", json={"media_id": scene.stem, "title": ""}).status_code == 422
