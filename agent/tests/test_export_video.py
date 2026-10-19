"""`export_video` worker handler: joins the clips behind the given media ids
in order, optionally smoothed to 60 fps. ffmpeg itself is mocked."""
import asyncio
from pathlib import Path
from unittest.mock import patch

from flowboard.db import get_session
from flowboard.db.models import Asset
from flowboard.request_types import MEDIA_PRODUCING_TYPES
from flowboard.services import video_export
from flowboard.worker import processor


def _clip(tmp_path: Path, name: str) -> str:
    f = tmp_path / f"{name}.mp4"
    f.write_bytes(b"\x00")
    with get_session() as s:
        a = Asset(kind="video", uuid_media_id=f"{name}0000-0000-4000-8000-000000000000"[:36],
                  local_path=str(f), mime="video/mp4")
        s.add(a)
        s.commit()
        s.refresh(a)
        return a.uuid_media_id


def test_export_video_is_a_media_producing_type():
    assert "export_video" in MEDIA_PRODUCING_TYPES
    assert "export_video" in processor._DEFAULT_HANDLERS


def test_handler_joins_in_the_given_order(tmp_path):
    a, b, c = (_clip(tmp_path, n) for n in ("aaaaaaaa", "bbbbbbbb", "cccccccc"))
    seen = {}

    def fake_export(asset_ids, *, smooth60, narration=None):
        seen["asset_ids"], seen["smooth60"], seen["narration"] = list(asset_ids), smooth60, narration
        return "joined-media-id", None, {"voiced": False}

    with patch("flowboard.services.video_export.export_video", fake_export):
        result, err = asyncio.run(processor._handle_export_video(
            {"source_media_ids": [c, a, b], "smooth60": True}))
    assert err is None
    assert result["media_ids"] == ["joined-media-id"] and result["clips"] == 3
    with get_session() as s:
        order = [s.exec(__import__("sqlmodel").select(Asset).where(Asset.uuid_media_id == m)).first().id
                 for m in (c, a, b)]
    assert seen["asset_ids"] == order and seen["smooth60"] is True
    assert seen["narration"] is None  # no lines sent → plain join


def test_handler_rejects_missing_inputs_and_unknown_clips():
    assert asyncio.run(processor._handle_export_video({}))[1] == "missing_source_media_ids"
    with patch("flowboard.services.media.fetch_and_cache", return_value=None):
        _, err = asyncio.run(processor._handle_export_video(
            {"source_media_ids": ["12345678-0000-4000-8000-000000000000"]}))
    assert err.startswith("clip_unavailable:")


def test_export_video_falls_back_to_the_join_when_smoothing_fails(tmp_path):
    joined = tmp_path / "joined.mp4"
    joined.write_bytes(b"\x00")
    with get_session() as s:
        row = Asset(kind="video", uuid_media_id="joined00-0000-4000-8000-000000000000",
                    local_path=str(joined), mime="video/mp4")
        s.add(row)
        s.commit()
        s.refresh(row)
        joined_id = row.id
    with (
        patch("flowboard.services.video_concat.concat_video_assets", return_value=(joined_id, None)),
        patch("flowboard.services.video_export.smooth_to_60fps", return_value="ffmpeg_not_found"),
    ):
        media, err, report = video_export.export_video([1], smooth60=True)
    assert err is None and media == "joined00-0000-4000-8000-000000000000"
    assert report["smooth60"] is False and report["smooth60_error"] == "ffmpeg_not_found"


def test_handler_builds_narration_options(tmp_path):
    a, b = (_clip(tmp_path, n) for n in ("dddddddd", "eeeeeeee"))
    seen = {}

    def fake_export(asset_ids, *, smooth60, narration=None):
        seen["narration"] = narration
        return "voiced-id", None, {"voiced": True}

    with patch("flowboard.services.video_export.export_video", fake_export):
        result, err = asyncio.run(processor._handle_export_video({
            "source_media_ids": [a, b], "narrations": ["Xin chào", ""],
            "voice": "vi-VN-NamMinhNeural", "voice_rate": "10", "subtitles": False,
            "original_audio": "mute"}))
    assert err is None and result["report"] == {"voiced": True}
    n = seen["narration"]
    assert n.lines == ["Xin chào", ""] and n.voice == "vi-VN-NamMinhNeural"
    assert n.rate == 10 and n.subtitles is False and n.original_audio == "mute"

    # Unknown voice / audio mode fall back; blank lines mean a plain join.
    with patch("flowboard.services.video_export.export_video", fake_export):
        asyncio.run(processor._handle_export_video({
            "source_media_ids": [a], "narrations": ["x"], "voice": "nope", "original_audio": "loud"}))
    assert seen["narration"].voice == "vi-VN-HoaiMyNeural" and seen["narration"].original_audio == "duck"
    with patch("flowboard.services.video_export.export_video", fake_export):
        asyncio.run(processor._handle_export_video({"source_media_ids": [a], "narrations": ["", "  "]}))
    assert seen["narration"] is None
