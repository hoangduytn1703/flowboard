"""Multi-voice dialogue in one narration line: ``[A] … [B] …`` tags, the
joined audio, and the plumbing from the worker params down to
``NarrationOptions``. Edge/Gemini are mocked; ffmpeg runs for real on
tiny generated WAVs."""
import asyncio
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from flowboard.services import tts, video_export
from flowboard.worker import processor

from tests.test_export_video import _clip


# ── parsing ─────────────────────────────────────────────────────────────────

def test_parse_speakers_splits_on_tags_and_uppercases():
    assert tts.parse_speakers("[A] Ủa áo này mặc mát không? [b] Mát lắm, cotton 100% luôn.") == [
        ("A", "Ủa áo này mặc mát không?"), ("B", "Mát lắm, cotton 100% luôn."),
    ]


def test_parse_speakers_untagged_lead_and_empty_segments():
    assert tts.parse_speakers("Mở đầu. [A] Một [B] [C] Ba ") == [
        (None, "Mở đầu."), ("A", "Một"), ("C", "Ba"),
    ]
    assert tts.parse_speakers("Không có tag") == [(None, "Không có tag")]
    assert tts.parse_speakers("") == [] and tts.parse_speakers("[A]  ") == []
    # digits are allowed, longer / odd tags are not tags
    assert tts.parse_speakers("[a1] x [này] y") == [("A1", "x [này] y")]


def test_strip_speaker_tags_keeps_plain_text_untouched():
    assert tts.strip_speaker_tags("[A] Một hai [B] ba") == "Một hai ba"
    plain = "  giữ nguyên   khoảng trắng "
    assert tts.strip_speaker_tags(plain) is plain
    assert tts.has_speaker_tags("[A] x") and not tts.has_speaker_tags("x")


# ── joined audio ─────────────────────────────────────────────────────────────

def _lavfi_wav(path: Path, seconds: float) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    "-ar", "24000", "-ac", "1", str(path)], check=True, capture_output=True)
    return path


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="needs ffmpeg")
def test_synthesize_dialogue_joins_segments_with_a_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "TTS_DIR", tmp_path)
    calls = []

    async def fake_synth(text, voice=tts.DEFAULT_VOICE, rate=0, style=None):
        calls.append((text, voice, rate, style))
        if voice == "vi-VN-HoaiMyNeural":
            # Edge-style: word timings come with the audio.
            return tts.Narration(_lavfi_wav(tmp_path / "a.wav", 1.0), 1.0,
                                 [tts.Word(0.0, 0.4, "Ủa"), tts.Word(0.4, 0.8, "sao?")])
        # Gemini-style: no timings.
        return tts.Narration(_lavfi_wav(tmp_path / "b.wav", 0.5), 0.5, [])

    monkeypatch.setattr(tts, "synthesize", fake_synth)
    n = asyncio.run(tts.synthesize_dialogue(
        "[A] Ủa sao? [B] Mát lắm", "vi-VN-NamMinhNeural", 0, "vui tươi",
        {"a": "vi-VN-HoaiMyNeural", "B": "gemini:Puck"}))
    assert calls == [("Ủa sao?", "vi-VN-HoaiMyNeural", 0, None), ("Mát lắm", "gemini:Puck", 0, "vui tươi")]
    assert n.path.is_file() and n.path.suffix == ".wav" and n.path.parent == tmp_path
    assert abs(n.duration - (1.0 + 0.3 + 0.5)) < 0.1
    assert [w.text for w in n.words] == ["Ủa", "sao?", "Mát", "lắm"]
    assert n.words[0].start == 0.0 and n.words[1].end == 0.8
    # the second turn starts after the first one plus the gap, its words spread evenly
    assert abs(n.words[2].start - 1.3) < 1e-6 and abs(n.words[3].end - 1.8) < 1e-6
    assert n.words[2].end <= n.words[3].start
    # cues over the tag-free text follow the shifted timings, no tag in them
    cues = tts.subtitle_cues(n, tts.strip_speaker_tags("[A] Ủa sao? [B] Mát lắm"))
    assert all("[" not in line for _, _, line in cues) and cues[0][0] == 0.0

    # cached: the same recipe does not synthesise again
    before = len(calls)
    again = asyncio.run(tts.synthesize_dialogue(
        "[A] Ủa sao? [B] Mát lắm", "vi-VN-NamMinhNeural", 0, "vui tươi",
        {"A": "vi-VN-HoaiMyNeural", "B": "gemini:Puck"}))
    assert len(calls) == before and again.path == n.path and len(again.words) == 4


def test_synthesize_dialogue_unknown_tag_uses_default_voice(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "TTS_DIR", tmp_path)
    seen = []

    async def fake_synth(text, voice=tts.DEFAULT_VOICE, rate=0, style=None):
        seen.append(voice)
        p = tmp_path / f"{len(seen)}.wav"
        p.write_bytes(b"RIFF")
        return tts.Narration(p, 0.2, [])

    monkeypatch.setattr(tts, "synthesize", fake_synth)
    monkeypatch.setattr(tts, "_concat_audio", lambda parts, out, gap: out.write_bytes(b"RIFF"))
    monkeypatch.setattr(tts, "_probe_duration", lambda p: None)
    n = asyncio.run(tts.synthesize_dialogue("Dẫn. [A] Một [Z] Hai", "vi-VN-NamMinhNeural", 5, None,
                                            {"A": "gemini:Kore", "B": "nope"}))
    assert seen == ["vi-VN-NamMinhNeural", "gemini:Kore", "vi-VN-NamMinhNeural"]
    assert abs(n.duration - (0.2 * 3 + 0.3 * 2)) < 1e-6
    with pytest.raises(tts.TTSError):
        asyncio.run(tts.synthesize_dialogue("   ", "vi-VN-NamMinhNeural"))


# ── per-clip rendering ───────────────────────────────────────────────────────

def _fake_run(cmd, timeout):
    Path(cmd[-1]).write_bytes(b"\x00")
    return None


def test_voice_clip_dialogue_reaches_tts_and_subtitles_drop_tags(tmp_path):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"\x00")
    seen = {}

    async def fake_dialogue(text, default_voice, rate, style, speakers):
        seen.update(text=text, voice=default_voice, rate=rate, style=style, speakers=speakers)
        p = tmp_path / "d.wav"
        p.write_bytes(b"RIFF")
        return tts.Narration(p, 2.0, [])

    async def fake_single(*_a, **_k):
        raise AssertionError("single-voice path must not run for a tagged line")

    opts = video_export.NarrationOptions(lines=["x"], voice="vi-VN-HoaiMyNeural", style="kịch tính",
                                         speakers={"A": "gemini:Kore", "B": "vi-VN-NamMinhNeural"},
                                         line_voices=["gemini:Puck"])
    with (
        patch("flowboard.services.video_export.probe_clip", return_value=video_export.ClipInfo(8.0, 720, 1280, True)),
        patch("flowboard.services.video_export._run", _fake_run),
        patch.object(tts, "synthesize_dialogue", fake_dialogue),
        patch.object(tts, "synthesize", fake_single),
    ):
        rep = video_export._voice_clip("ffmpeg", src, "[A] Ủa áo này? [B] Mát lắm.", opts,
                                       tmp_path / "clip00.mp4", tmp_path, voice=opts.voice_for(0))
    assert rep.error is None and rep.narration_s == 2.0
    assert seen["text"] == "[A] Ủa áo này? [B] Mát lắm." and seen["voice"] == "gemini:Puck"
    assert seen["speakers"] == {"A": "gemini:Kore", "B": "vi-VN-NamMinhNeural"} and seen["style"] == "kịch tính"
    ass = (tmp_path / "clip00.ass").read_text(encoding="utf-8")
    assert "[A]" not in ass and "[B]" not in ass and "Ủa áo này? Mát lắm." in ass


def test_voice_clip_plain_line_keeps_the_single_voice_path(tmp_path):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"\x00")
    calls = []

    async def fake_single(text, voice=tts.DEFAULT_VOICE, rate=0, style=None):
        calls.append((text, voice, rate, style))
        p = tmp_path / "s.mp3"
        p.write_bytes(b"\x00")
        return tts.Narration(p, 1.0, [])

    async def fake_dialogue(*_a, **_k):
        raise AssertionError("dialogue path must not run for a plain line")

    opts = video_export.NarrationOptions(lines=["x", "y"], voice="vi-VN-HoaiMyNeural",
                                         line_voices=[None, "vi-VN-NamMinhNeural"])
    with (
        patch("flowboard.services.video_export.probe_clip", return_value=video_export.ClipInfo(8.0, 720, 1280, True)),
        patch("flowboard.services.video_export._run", _fake_run),
        patch.object(tts, "synthesize", fake_single),
        patch.object(tts, "synthesize_dialogue", fake_dialogue),
    ):
        video_export._voice_clip("ffmpeg", src, "Xin chào", opts, tmp_path / "c0.mp4", tmp_path,
                                 voice=opts.voice_for(0))
        video_export._voice_clip("ffmpeg", src, "Chào lại", opts, tmp_path / "c1.mp4", tmp_path,
                                 voice=opts.voice_for(1))
    # exactly the call the one-voice export always made, then the per-clip override
    assert calls == [("Xin chào", "vi-VN-HoaiMyNeural", 0, None), ("Chào lại", "vi-VN-NamMinhNeural", 0, None)]
    assert opts.voice_for(5) == "vi-VN-HoaiMyNeural"


# ── worker plumbing ──────────────────────────────────────────────────────────

def test_handler_passes_speakers_and_line_voices(tmp_path):
    a, b = (_clip(tmp_path, n) for n in ("ffffffff", "gggggggg"))
    seen = {}

    def fake_export(asset_ids, *, smooth60, narration=None, items=None, **_bgm):
        seen["narration"] = narration
        return "voiced-id", None, {"voiced": True}

    with patch("flowboard.services.video_export.export_video", fake_export):
        result, err = asyncio.run(processor._handle_export_video({
            "source_media_ids": [a, b], "narrations": ["[A] Ủa? [B] Mát lắm", "Câu hai"],
            "voice": "vi-VN-HoaiMyNeural",
            "speakers": {"a": "gemini:Kore", "B": "vi-VN-NamMinhNeural", "C": "nope", "toolongtag": "gemini:Puck",
                         "D": "gemini:Leda", "E": "gemini:Orus", "F": "gemini:Puck"},
            "voices": [None, "gemini:Charon", "bad"],
        }))
    assert err is None
    n = seen["narration"]
    assert n.speakers == {"A": "gemini:Kore", "B": "vi-VN-NamMinhNeural", "D": "gemini:Leda", "E": "gemini:Orus"}
    assert n.line_voices == [None, "gemini:Charon", None]
    assert n.voice_for(0) == "vi-VN-HoaiMyNeural" and n.voice_for(1) == "gemini:Charon"

    # absent → empty, so the one-voice export is unchanged
    with patch("flowboard.services.video_export.export_video", fake_export):
        asyncio.run(processor._handle_export_video({"source_media_ids": [a], "narrations": ["x"]}))
    assert seen["narration"].speakers == {} and seen["narration"].line_voices == []
