"""Câu mở đầu A/B: variants for a post and for a clip's first voice line."""
import json

import pytest

from flowboard.services import hooks, post_writer


def _answer(lines):
    return json.dumps({"variants": [{"style": s, "line": l} for s, l in lines]})


@pytest.mark.asyncio
async def test_post_hooks_keep_the_post_and_styles(monkeypatch):
    seen = {}

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        seen["prompt"], seen["system"] = prompt, system_prompt
        return _answer([("question", "Mẹ nào từng mất ngủ vì lo con?"), ("number", "3 điều mình ước biết sớm"),
                        ("bogus", "x"), ("question", "mẹ nào từng mất ngủ vì lo con?"), ("pain", "Đêm nào cũng dậy 3 lần…")])

    monkeypatch.setattr(hooks, "run_llm", fake_llm)
    out = await hooks.post_hooks("Hôm qua mình mất ngủ cả đêm.\n\nVì con quấy. " * 3, n=3)
    assert [v["style"] for v in out] == ["question", "number", "auto"]  # duplicates dropped, unknown style → auto, capped at n
    assert out[0]["label"] == "Câu hỏi chạm đúng vấn đề"
    assert "STYLES" in seen["prompt"] and "- question:" in seen["prompt"] and "CURRENT POST" in seen["prompt"]
    assert "engagement bait" in seen["system"]
    with pytest.raises(post_writer.PostWriterError):
        await hooks.post_hooks("ngắn")


@pytest.mark.asyncio
async def test_clip_hooks_are_short_spoken_lines(monkeypatch):
    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        assert "Scene 1: Câu một" in prompt and "Scene 2: Câu hai" in prompt
        return _answer([("question", " ".join(["từ"] * 40)), ("story", "Sáng nay mình thử cái này")])

    monkeypatch.setattr(hooks, "run_llm", fake_llm)
    out = await hooks.clip_hooks(["Câu một", "Câu hai"], clip_name="Cơm cháy", n=2)
    assert len(out[0]["line"].split()) == hooks.CLIP_HOOK_WORDS + 6  # over-long lines are cut
    assert out[1]["line"] == "Sáng nay mình thử cái này"
    with pytest.raises(post_writer.PostWriterError):
        await hooks.clip_hooks(["", ""])


def test_replace_opening():
    assert hooks.replace_opening("Dòng 1\nvẫn dòng đầu\n\nThân bài\n\nKết", "Mở mới") == "Mở mới\n\nThân bài\n\nKết"
    assert hooks.replace_opening("Chỉ một đoạn", "Mở mới") == "Mở mới"
    assert hooks.replace_opening("", "Mở mới") == "Mở mới"


def test_hook_routes(client, monkeypatch):
    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        return _answer([("question", "Hỏi?"), ("pain", "Khổ.")])

    monkeypatch.setattr(hooks, "run_llm", fake_llm)
    r = client.post("/api/posts/hooks", json={"body": "Một bài viết đủ dài để có câu mở đầu khác.", "n": 2})
    assert r.status_code == 200 and [v["line"] for v in r.json()["variants"]] == ["Hỏi?", "Khổ."]
    board = client.post("/api/boards", json={"name": "Clip"}).json()
    client.post("/api/nodes", json={"board_id": board["id"], "type": "video", "data": {"narration": "Lời cảnh 1"}})
    r = client.post("/api/posts/clip-hooks", json={"board_id": board["id"]})
    assert r.status_code == 200 and r.json()["current"] == "Lời cảnh 1" and len(r.json()["variants"]) == 2
    assert client.post("/api/posts/clip-hooks", json={"board_id": 9999}).status_code == 404
