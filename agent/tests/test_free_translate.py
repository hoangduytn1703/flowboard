"""Dub translation without an AI quota: free Google → Microsoft (like VieDub), and the AI path
handing over to it when the AI fails (Claude's quota used up, CLI missing…)."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from flowboard.services import dub, free_translate
from flowboard.services.llm.base import LLMError


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_google_keeps_one_line_per_line_and_maps_chinese():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(dict(req.url.params))
        lines = req.url.params["q"].split("\n")
        return httpx.Response(200, json=[[[f"vi {x}\n" if i < len(lines) - 1 else f"vi {x}", x] for i, x in enumerate(lines)], None, "zh-CN"])

    out = free_translate.google_batch(["你好", "再见"], "zh", client=_client(handler))
    assert out == ["vi 你好", "vi 再见"]
    assert seen["sl"] == "zh-CN" and seen["tl"] == "vi" and seen["client"] == "gtx"
    with pytest.raises(free_translate.TranslateError):  # a merged answer is not trusted
        free_translate.google_batch(["a", "b"], None, client=_client(lambda r: httpx.Response(200, json=[[["một", "a b"]]])))
    with pytest.raises(free_translate.TranslateError):
        free_translate.google_batch(["a"], None, client=_client(lambda r: httpx.Response(429, text="sorry")))


def test_microsoft_answers_item_by_item():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params["to"] == "vi" and req.url.params["from"] == "zh-Hans"
        return httpx.Response(200, json=[{"translations": [{"text": f"vi {x}"}]} for x in json.loads(req.content)])

    assert free_translate.microsoft_batch(["a", "b", "c"], "zh", client=_client(handler)) == ["vi a", "vi b", "vi c"]


def test_batches_stay_small_enough_for_a_get_url():
    lines = ["字" * 100] * 20 + ["x"] * 40
    spans = free_translate.batches(lines)
    assert spans[0][0] == 0 and spans[-1][1] == 60 and all(a[1] == b[0] for a, b in zip(spans, spans[1:]))
    assert all(sum(len(t) for t in lines[a:b]) <= free_translate.GOOGLE_MAX_CHARS or b - a == 1 for a, b in spans)
    assert all(b - a <= free_translate.BATCH_LINES for a, b in spans)


def test_google_down_microsoft_takes_over_and_empty_lines_stay_empty(monkeypatch):
    calls = []

    def google(lines, source, target="vi", *, client=None):
        calls.append("g")
        raise free_translate.TranslateError("Google 429")

    def microsoft(lines, source, target="vi", *, client=None):
        calls.append("m")
        return [f"vi {x}" for x in lines]

    monkeypatch.setattr(free_translate, "google_batch", google)
    monkeypatch.setattr(free_translate, "microsoft_batch", microsoft)
    out, by = free_translate.translate_lines(["a", "  ", "b"], "zh", sleep=lambda s: None)
    assert out == ["vi a", "", "vi b"] and by == "microsoft"
    assert calls == ["g"] * free_translate.ATTEMPTS + ["m"]

    monkeypatch.setattr(free_translate, "microsoft_batch", google)
    with pytest.raises(free_translate.TranslateError, match="Google và Microsoft"):
        free_translate.translate_lines(["a"], None, sleep=lambda s: None)


def test_lines_left_in_chinese_are_asked_again_one_by_one(monkeypatch):
    """14/11: a Google batch came back with 6 of 82 lines still in Chinese."""
    asked = []

    def google(lines, source, target="vi", *, client=None):
        asked.append(("g", list(lines)))
        if len(lines) > 1:  # the batch: the 2nd and 3rd lines left as they were
            return ["vi một", lines[1], lines[2], "vi bốn"]
        return [lines[0]] if lines[0] == "风速" else ["tinh vân"]   # alone: one is translated, one still is not

    def microsoft(lines, source, target="vi", *, client=None):
        asked.append(("m", list(lines)))
        return ["tốc độ gió" for _ in lines]

    monkeypatch.setattr(free_translate, "google_batch", google)
    monkeypatch.setattr(free_translate, "microsoft_batch", microsoft)
    out, by = free_translate.translate_lines(["一", "星云", "风速", "四"], "zh", sleep=lambda s: None)
    assert out == ["vi một", "tinh vân", "tốc độ gió", "vi bốn"] and by == "google"
    assert asked[1:] == [("g", ["星云"]), ("g", ["风速"]), ("m", ["风速"])]
    # nothing better from either: the line is left as it was and reported
    monkeypatch.setattr(free_translate, "microsoft_batch", lambda lines, *a, **k: list(lines))
    still = free_translate.retry_leftovers(["风速"], ["风速"], "zh", sleep=lambda s: None)
    assert still == [0]
    # a Chinese / Japanese / Korean target keeps its writing: nothing is asked again
    assert not free_translate.left_untranslated("星云", "星云", "zh") and free_translate.left_untranslated("星云", "星云", "vi")
    assert not free_translate.left_untranslated("hello", "xin chào", "vi")


def test_a_name_fix_never_puts_the_chinese_back():
    from flowboard.services import dub_names

    assert not dub_names.is_name_fix("Tốc độ gió", "风速")
    assert dub_names.is_name_fix("Sao Hỏa rất xa", "Sao Hỏa rất xa nhé")


def _job(translator: str, n: int = 5) -> dub.Job:
    job = dub.Job(id="tr", url=None, source_media_id="x", language="zh", translator=translator,
                  title="棉花糖星球 #科普 #探索宇宙")
    job.segments = [dub.Segment(float(i), float(i) + 0.9, f"src{i}") for i in range(n)]
    return job


def test_a_new_dub_translates_with_google_by_default_and_never_calls_the_ai(monkeypatch):
    async def no_ai(*a, **k):
        raise AssertionError("the AI must not be called")

    def free(lines, source=None, target="vi", **kw):
        return [f"vi {x}" for x in lines], "google"

    monkeypatch.setattr(dub, "run_llm", no_ai)
    monkeypatch.setattr(free_translate, "translate_lines", free)
    job = dub.Job(id="d", url=None, source_media_id="x")
    assert job.translator == "google"
    job = _job("google")
    asyncio.run(dub._translate(job))
    assert [s.text for s in job.segments] == [f"vi src{i}" for i in range(5)]
    assert job.translated_by == "google"
    assert job.title == "vi 棉花糖星球"  # hashtags dropped before translating the title
    assert job.public()["translator"] == "google"


def test_an_ai_that_fails_hands_the_rest_to_google(monkeypatch):
    calls = []

    async def ai(feature, prompt, *, system_prompt=None, timeout=0):
        calls.append(prompt)
        if len(calls) == 2:
            raise LLMError("claude CLI exited 1: Claude AI usage limit reached")
        n = int(prompt.split("TRANSCRIPT (")[1].split(" lines")[0])
        return json.dumps({"title": "Tiêu đề AI", "lines": [f"ai{k}" for k in range(n)]})

    def free(lines, source=None, target="vi", **kw):
        return [f"gg {x}" for x in lines], "google"

    monkeypatch.setattr(dub, "run_llm", ai)
    monkeypatch.setattr(free_translate, "translate_lines", free)
    job = _job("ai", 130)
    asyncio.run(dub._translate(job))
    assert job.segments[0].text == "ai0" and job.segments[59].text == "ai59"
    assert job.segments[60].text == "gg src60" and job.segments[-1].text == "gg src129"
    assert job.title == "Tiêu đề AI"
    assert job.translated_by.startswith("google (AI lỗi") and "usage limit" in job.translated_by


def test_routes_and_the_library_carry_the_translator(client, monkeypatch):
    st = client.get("/api/dub/status").json()
    assert [t["key"] for t in st["translators"]] == ["google", "ai"]
    monkeypatch.setattr(dub, "status", lambda: {"available": True, "separate": False, "remotion": False})
    monkeypatch.setattr(dub, "_pump", lambda: None)
    r = client.post("/api/dub/jobs", json={"url": "https://v.douyin.com/abc", "voice": dub.tts.DEFAULT_VOICE,
                                           "keep_bgm": False, "style": "box_yellow", "auto_render": True, "translator": "ai"})
    try:
        assert r.status_code == 201 and r.json()["translator"] == "ai"
    finally:
        dub.JOBS.pop(r.json().get("job_id"), None)
    bad = client.post("/api/dub/jobs", json={"url": "https://v.douyin.com/abc", "voice": dub.tts.DEFAULT_VOICE,
                                             "keep_bgm": False, "style": "box_yellow", "auto_render": True, "translator": "x"})
    assert bad.status_code == 422


def test_a_failed_claude_run_says_why():
    from flowboard.services.claude_cli import _stdout_reason

    env = json.dumps({"type": "result", "is_error": True, "result": "Claude AI usage limit reached|1761868800"})
    assert _stdout_reason(env) == "Claude AI usage limit reached|1761868800"
    assert _stdout_reason("plain text error") == "plain text error"
    assert _stdout_reason("") == ""


def test_the_target_language_is_mapped_for_each_service():
    seen = {}

    def google(req: httpx.Request) -> httpx.Response:
        seen["tl"] = req.url.params["tl"]
        return httpx.Response(200, json=[[["你好", "hello"]], None, "en"])

    free_translate.google_batch(["hello"], "en", "zh", client=_client(google))
    assert seen["tl"] == "zh-CN"

    def ms(req: httpx.Request) -> httpx.Response:
        assert req.url.params["to"] == "zh-Hans"
        return httpx.Response(200, json=[{"translations": [{"text": "你好"}]}])

    assert free_translate.microsoft_batch(["hello"], "en", "zh", client=_client(ms)) == ["你好"]
