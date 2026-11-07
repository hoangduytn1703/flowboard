"""Proper names in dubbed videos (7/11): the free Google translation turned Whisper's 安音斯坦 (for 爱因斯坦)
into "Anyinstein", 奥尔特云 into "Ultra Cloud", left "Mercury" for Sao Thủy — and the Vietnamese voice read
them wrongly. Whisper now gets the title as hotwords, a Gemini pass fixes the names right after Google, and
a glossary makes the voice read "Anh xtanh" where the subtitle shows "Einstein"."""
import json
from pathlib import Path

import pytest

from flowboard.services import dub, dub_names, dub_runner, tts
from flowboard.services.llm import gemini_api


def test_asr_hint_keeps_the_words_and_hashtags_without_the_marks():
    hint = dub_names.asr_hint("如果你和牛顿爱因斯坦一起逃离银河系 #爱因斯坦 #牛顿 #爱因斯坦 @科普君 https://v.douyin.com/x")
    assert "爱因斯坦" in hint and "牛顿" in hint and "#" not in hint and "@" not in hint and "http" not in hint
    assert hint.count("爱因斯坦") == 1 or hint.split().count("爱因斯坦") == 1
    assert dub_names.asr_hint("") == ""


def test_names_are_normalized_and_read_aloud_by_whole_word():
    names = dub_names.normalize_names([{"write": " Einstein ", "say": "Anh-xtanh"}, {"write": "einstein", "say": "x"},
                                       {"write": "", "say": "y"}, {"write": "Proxima Centauri", "say": "Prốc xi ma Xen tau ri"},
                                       {"write": "Oort"}])
    assert names == [{"write": "Einstein", "say": "Anh xtanh"},
                     {"write": "Proxima Centauri", "say": "Prốc xi ma Xen tau ri"},
                     {"write": "Oort", "say": "Oort"}]
    text = "Einstein và Proxima Centauri, còn Einsteinium thì không"
    assert dub_names.spoken(text, names) == "Anh xtanh và Prốc xi ma Xen tau ri, còn Einsteinium thì không"


@pytest.mark.asyncio
async def test_the_check_fixes_names_and_drops_rewrites(monkeypatch):
    lines = ["Anyinstein", "Nó là Ultra Cloud", "Mercury biết trước chúng ta", "Trời hôm nay đẹp"]
    seen = {}

    async def fake_generate(prompt, **kw):
        seen["prompt"], seen["system"] = prompt, kw.get("system")
        return json.dumps({"fixes": [{"line": 1, "text": "Einstein"},
                                     {"line": 2, "text": "Nó là đám mây Oort"},
                                     {"line": 3, "text": "Sao Thủy biết trước chúng ta"},
                                     {"line": 4, "text": "Một câu hoàn toàn khác không liên quan gì tới câu gốc cả"},
                                     {"line": 99, "text": "ngoài phạm vi"}],
                           "names": [{"write": "Einstein", "say": "Anh xtanh"}, {"write": "Oort", "say": "Ót"}]})

    monkeypatch.setattr(gemini_api, "configured", lambda: True)
    monkeypatch.setattr(gemini_api, "generate_text", fake_generate)
    fixes, names = await dub_names.check(["安音斯坦", "这就是奥特云", "水星比我们早知道", "今天天气很好"], lines,
                                         title="和牛顿爱因斯坦逃离银河系", language="zh")
    assert "安音斯坦 => Anyinstein" in seen["prompt"] and "爱因斯坦" in seen["prompt"]
    assert fixes == {0: "Einstein", 1: "Nó là đám mây Oort", 2: "Sao Thủy biết trước chúng ta"}  # line 4 rewritten → dropped
    assert names == [{"write": "Einstein", "say": "Anh xtanh"}, {"write": "Oort", "say": "Ót"}]


@pytest.mark.asyncio
async def test_no_gemini_key_means_no_check(monkeypatch):
    monkeypatch.setattr(gemini_api, "configured", lambda: False)
    with pytest.raises(dub_names.NamesError, match="Gemini"):
        await dub_names.check(["a"], ["b"])


def test_the_voice_reads_the_glossary_but_gemini_reads_as_written():
    job = dub.Job(id="n1", url=None, source_media_id="x", voice="vieneu:Hải Đăng")
    job.segments = [dub.Segment(0, 1, "安音斯坦", "Einstein nói vậy")]
    before = dub.voice_key(job)
    job.names = [{"write": "Einstein", "say": "Anh xtanh"}]
    assert dub.speech(job, job.segments[0].text) == "Anh xtanh nói vậy"
    assert dub.voice_key(job) != before  # a new reading → the voice is read again
    job.voice = next(v for v in tts.VOICES if tts.voice_kind(v) == "gemini")
    assert dub.speech(job, job.segments[0].text) == "Einstein nói vậy"


@pytest.mark.asyncio
async def test_the_pipeline_check_fixes_lines_or_leaves_them(monkeypatch):
    job = dub.Job(id="n2", url=None, source_media_id="x", language="zh", translated_by="google")
    job.segments = [dub.Segment(0, 1, "安音斯坦", "Anyinstein"), dub.Segment(1, 2, "今天", "Hôm nay")]
    assert dub.needs_name_check(job)

    async def fake_check(src, lines, **kw):
        return {0: "Einstein"}, [{"write": "Einstein", "say": "Anh xtanh"}]

    monkeypatch.setattr(dub_names, "check", fake_check)
    await dub._check_names(job, "标题")
    assert job.segments[0].text == "Einstein" and job.names[0]["say"] == "Anh xtanh" and "sửa 1 câu" in job.names_note

    async def broken(src, lines, **kw):
        raise dub_names.NamesError("chưa có Gemini API key")

    monkeypatch.setattr(dub_names, "check", broken)
    job.segments[1].text = "Hôm nay"
    await dub._check_names(job)
    assert job.segments[1].text == "Hôm nay" and "chưa rà" in job.names_note
    # the AI translator / subtitles in another language are not checked
    assert not dub.needs_name_check(dub.Job(id="n3", url=None, source_media_id="x", translated_by="ai"))
    assert not dub.needs_name_check(dub.Job(id="n4", url=None, source_media_id="x", translated_by="google",
                                            mode="sub", sub_lang="en"))


def test_names_travel_with_the_job_and_the_editor_saves_them(client, monkeypatch, tmp_path):
    src = tmp_path / "s.mp4"
    src.write_bytes(b"x")
    job = dub.Job(id="beef0000000a", url=None, source_media_id="x", language="zh", status="done", src_path=src)
    job.segments = [dub.Segment(0, 1, "安音斯坦", "Anyinstein")]
    dub.JOBS[job.id] = job

    async def fake_check(src_lines, lines, **kw):
        assert lines == ["Anyinstein (sửa tay)"]
        return {0: "Einstein (sửa tay)"}, [{"write": "Einstein", "say": "Anh xtanh"}]

    monkeypatch.setattr(dub_names, "check", fake_check)
    monkeypatch.setattr(dub, "_pump", lambda: None)
    monkeypatch.setattr(dub, "persist", lambda j: None)
    try:
        r = client.post(f"/api/dub/jobs/{job.id}/names", json={"lines": ["Anyinstein (sửa tay)"]})
        assert r.status_code == 200, r.text
        assert r.json() == {"fixes": {"0": "Einstein (sửa tay)"}, "names": [{"write": "Einstein", "say": "Anh xtanh"}]}
        assert job.segments[0].text == "Anyinstein" and job.names == []  # nothing saved until the export
        dub.render_job(job, lines=["Einstein"], voice=None, style=None, keep_bgm=None, name=None,
                       names=[{"write": "Einstein", "say": "Anh-xtanh"}])
        assert job.names == [{"write": "Einstein", "say": "Anh xtanh"}] and job.public()["names"] == job.names
        restored = dub._job_from_dict(dub.snapshot(job), Path("."), 0)
        assert restored.names == job.names
    finally:
        dub.JOBS.pop(job.id, None)


def test_the_runner_passes_the_hint_to_whisper(monkeypatch):
    seen = {}
    monkeypatch.setattr(dub_runner, "transcribe", lambda a, o, lang, words=False, hint=None: seen.update(lang=lang, words=words, hint=hint))
    assert dub_runner.main(["transcribe", "a.wav", "o.json", "auto", "-", "牛顿 爱因斯坦"]) == 0
    assert seen == {"lang": None, "words": False, "hint": "牛顿 爱因斯坦"}
    dub_runner.main(["transcribe", "a.wav", "o.json", "auto", "words"])
    assert seen == {"lang": None, "words": True, "hint": None}
