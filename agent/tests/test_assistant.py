"""🤖 Trợ lý AI: chat turns plan background work (models, products, posts, schedules, clips) from the catalog."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from flowboard.services import assistant, post_writer

VN = timezone(timedelta(hours=7))


def _model_plan(**args):
    return json.dumps({"reply": "Ok, mình tạo một mẫu nữ Việt sang chảnh nhé — khoảng 30 giây.",
                       "actions": [{"tool": "create_model", "args": {
                           "name": "Bảo Ngọc", "gender": "female", "country": "vn",
                           "look": "mid-20s, long straight black hair, elegant evening makeup, black satin dress, warm studio light",
                           "summary": "nữ Việt 25 tuổi, tóc dài thẳng, sang chảnh", **args}}]}, ensure_ascii=False)


def _cat():
    return {"channels": [{"id": 2, "name": "Chúng ta hay tò mò", "platforms": ["facebook"], "fb_connected": True},
                         {"id": 3, "name": "Mẹ bầu.", "platforms": ["facebook"], "fb_connected": False}],
            "series": [{"name": "những thú vị về hệ mặt trời", "channel_id": 2, "episodes": 6, "last_episode": 6}],
            "products": [{"id": 5, "name": "Cơm cháy chà bông", "category": "food", "has_photo": True}],
            "templates": [{"id": "food_review", "title": "Review đồ ăn", "category": "food"}], "models": []}


def _later(hours=26, hh=12):
    d = (datetime.now(VN) + timedelta(hours=hours)).replace(hour=hh, minute=0, second=0, microsecond=0)
    return d.strftime("%Y-%m-%dT%H:%M")


def test_parse_answer_keeps_a_good_plan_and_turns_a_bad_one_into_a_question():
    a = assistant.parse_answer("Đây:\n```json\n" + _model_plan() + "\n```")
    assert a["actions"][0]["tool"] == "create_model" and a["actions"][0]["args"]["gender"] == "female" and a["reply"].startswith("Ok")
    bad = assistant.parse_answer(_model_plan(gender="alien"))
    assert bad["actions"] == [] and "nam hay nữ" in bad["reply"]  # unknown gender → ask, don't draw
    assert assistant.parse_answer(_model_plan(country="zz"))["actions"][0]["args"]["country"] == "vn"
    plain = assistant.parse_answer('{"reply": "Mình làm được người mẫu AI, bài viết, lịch đăng.", "actions": []}')
    assert plain["actions"] == [] and "người mẫu" in plain["reply"]
    assert assistant.parse_answer("not json at all")["actions"] == []
    # the older single "action" shape still reads
    old = json.loads(_model_plan())
    assert assistant.parse_answer(json.dumps({"reply": "ok", "action": old["actions"][0]}))["actions"][0]["tool"] == "create_model"


def test_typos_and_missing_accents_still_land_on_the_right_channel_and_series():
    plan = {"reply": "Ok", "actions": [
        {"tool": "write_post", "args": {"channel_id": "chú ta hay tò mò", "series": "nhung thu vi ve he mat troi", "episode": 7}},
        {"tool": "schedule_post", "args": {"post": "previous", "at": _later()}}]}
    a = assistant.parse_answer(json.dumps(plan, ensure_ascii=False), _cat())
    w, s = a["actions"]
    assert w["args"]["channel_id"] == 2 and w["args"]["series"] == "những thú vị về hệ mặt trời" and w["args"]["count"] == 1
    assert s["args"]["post"] == "previous" and s["args"]["at"].endswith("Z")
    assert assistant.needs_go_ahead(a["actions"], _cat())  # auto-posting on a connected page waits for "ok"
    lines = assistant._plan_summary(a["actions"], _cat())
    assert "Chúng ta hay tò mò" in lines[0] and "những thú vị về hệ mặt trời" in lines[0] and "tự đăng" in lines[1]
    # a product by a loose name; a time already passed → a question, nothing planned
    p = assistant.parse_answer(json.dumps({"reply": "", "actions": [{"tool": "create_clip", "args": {"product_id": "com chay cha bong"}}]}), _cat())
    assert p["actions"][0]["args"]["product_id"] == 5
    past = (datetime.now(VN) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    q = assistant.parse_answer(json.dumps({"reply": "", "actions": [{"tool": "schedule_post", "args": {"post": "previous", "at": past}}]}), _cat())
    assert q["actions"] == [] and "đã qua" in q["reply"]
    # no channel named and several channels → ask which
    q = assistant.parse_answer(json.dumps({"reply": "", "actions": [{"tool": "write_post", "args": {"topic": "x"}}]}), _cat())
    assert q["actions"] == [] and "kênh nào" in q["reply"]


def test_model_prompt_is_a_front_facing_portrait_of_an_original_person():
    p = assistant.model_prompt({"gender": "female", "country": "kr", "look": "short bob hair, pastel cardigan"}, traits="x and y")
    assert p.startswith("Natural daylight head-and-shoulders portrait photo of a Korean female character")
    assert "not resembling any celebrity" in p and "own distinctive face (x and y)" in p and "short bob hair" in p


class _Worker:
    def __init__(self, seen):
        self.seen = seen

    def enqueue(self, rid):
        self.seen.setdefault("enqueued", []).append(rid)


async def _until(fn, tries=300):
    for _ in range(tries):
        if fn():
            return True
        await asyncio.sleep(0.02)
    return False


@pytest.mark.asyncio
async def test_a_chat_turn_draws_the_model_in_the_background_and_saves_it(client, monkeypatch):
    seen = {}

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        seen["prompt"], seen["system"] = prompt, system_prompt
        return _model_plan()

    monkeypatch.setattr(assistant, "run_llm", fake_llm)
    monkeypatch.setattr(assistant, "POLL_S", 0.02)
    monkeypatch.setattr("flowboard.services.flow_project.effective_project_id", lambda: "a" * 36)
    monkeypatch.setattr("flowboard.worker.processor.get_worker", lambda: _Worker(seen))

    out = await assistant.chat("tạo cho tao mẫu giống Ngọc Trinh, lưu lại")
    assert [m["role"] for m in out["messages"]] == ["user", "assistant"] and out["task"]["status"] == "running"
    assert "REAL PEOPLE" in seen["system"] and "Ngọc Trinh" in seen["prompt"] and "CATALOG" in seen["prompt"]
    from flowboard.db import get_session
    from flowboard.db.models import Reference, Request

    assert await _until(lambda: seen.get("enqueued"))
    with get_session() as s:
        req = s.get(Request, seen["enqueued"][0])
        assert req.params["origin"] == "assistant" and req.params["aspect_ratio"] == "IMAGE_ASPECT_RATIO_PORTRAIT"
        assert "Ngọc Trinh" not in req.params["prompt"] and "elegant evening makeup" in req.params["prompt"]
    # the running badge shows the assistant's row (back to its page, chat open), not a second "Ảnh AI" row
    items = client.get("/api/running").json()["items"]
    assert [i["kind"] for i in items] == ["assistant"] and items[0]["link"] == "/models?assistant=1"
    with get_session() as s:
        req = s.get(Request, seen["enqueued"][0])
        req.status, req.result = "done", {"media_ids": ["m_model_1"]}
        s.add(req)
        s.commit()
    assert await _until(lambda: assistant.task_outcome(out["task"]["id"])["status"] != "running")
    task = assistant.task_outcome(out["task"]["id"])
    assert task["status"] == "done" and task["media_id"] == "m_model_1"
    with get_session() as s:
        ref = s.get(Reference, task["reference_id"])
        assert ref.kind == "character" and ref.label == "Bảo Ngọc" and ref.meta["by"] == "assistant" and ref.meta["gender"] == "female"
    last = client.get("/api/assistant").json()["messages"][-1]
    assert last["data"]["link"] == "/models" and last["data"]["media_id"] == "m_model_1" and "Bảo Ngọc" in last["text"]
    assert client.get("/api/running/outcome", params={"key": f"assistant:{task['id']}"}).json()["ok"]
    assert client.delete("/api/assistant").json()["removed"] == 3 and client.get("/api/assistant").json()["messages"] == []


@pytest.mark.asyncio
async def test_no_pinned_project_is_said_in_the_chat(monkeypatch):
    async def fake_llm(*a, **k):
        return _model_plan()

    monkeypatch.setattr(assistant, "run_llm", fake_llm)
    monkeypatch.setattr("flowboard.services.flow_project.effective_project_id", lambda: "")
    out = await assistant.chat("tạo mẫu nam")
    assert await _until(lambda: assistant.task_outcome(out["task"]["id"])["status"] != "running")
    t = assistant.task_outcome(out["task"]["id"])
    assert t["status"] == "error" and "Flow project" in t["error"]
    assert "⚠" in assistant.state()["messages"][-1]["text"]


def _story_series(client):
    ch = client.post("/api/channels", json={"name": "Chúng ta hay tò mò", "platforms": ["facebook"]}).json()["id"]
    for ep in (1, 2):
        client.post("/api/posts", json={"body": f"Tập {ep}: hành tinh {ep}", "series": "những thú vị về hệ mặt trời", "episode": ep,
                                        "channel_id": ch, "kind": "serial",
                                        "brief": {"kind": "serial", "tone": "story", "images": 0, "topic": "những thú vị về hệ mặt trời"}})
    return ch


@pytest.fixture
def writer(monkeypatch):
    seen = {"writes": []}

    async def fake_writer_llm(feature, prompt, *, system_prompt=None, timeout=0):
        seen["writes"].append(prompt)
        return json.dumps({"reply": "ok", "title": "Tập mới - Sao Thổ", "body": "Tiếp tục câu chuyện lần trước… Sao Thổ.",
                           "hashtags": ["#vutru"], "image_prompts": [], "first_comment": ""}, ensure_ascii=False)

    monkeypatch.setattr(post_writer, "run_llm", fake_writer_llm)
    return seen


@pytest.mark.asyncio
async def test_write_the_next_episode_for_a_typo_named_channel_then_schedule_it(client, monkeypatch, writer):
    ch = _story_series(client)
    at = _later()

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        assert "Chúng ta hay tò mò" in prompt and "những thú vị về hệ mặt trời" in prompt  # the catalog reaches the AI
        return json.dumps({"reply": "Ok, mình viết tập tiếp rồi lên lịch.", "actions": [
            {"tool": "write_post", "args": {"channel_id": "chú ta hay tò mò", "series": "nhung thu vi ve he mat troi"}},
            {"tool": "schedule_post", "args": {"post": "previous", "at": at}}]}, ensure_ascii=False)

    monkeypatch.setattr(assistant, "run_llm", fake_llm)
    out = await assistant.chat("tạo 1 bài viết cho kênh chú ta hay tò mò, tập 3 trong series những thú vị về hệ mặt trời, xong set lịch post")
    assert out["task"]["status"] == "running"  # the page is not connected: nothing goes out by itself, no go-ahead needed
    assert await _until(lambda: assistant.task_outcome(out["task"]["id"])["status"] != "running")
    t = assistant.task_outcome(out["task"]["id"])
    assert t["status"] == "done", t
    posts = client.get("/api/posts").json()
    new = next(p for p in posts if p["episode"] == 3)
    assert new["series"] == "những thú vị về hệ mặt trời" and new["channel_id"] == ch and new["kind"] == "story"
    assert "EPISODE 3" in writer["writes"][0] and "Tập 2: hành tinh 2" in writer["writes"][0]  # it read the episodes before
    slot = new["schedule"]
    assert slot["status"] == "planned" and not slot["auto"]
    assert datetime.fromisoformat(slot["at"].replace("Z", "+00:00")).astimezone(VN).strftime("%Y-%m-%dT%H:%M") == at
    last = assistant.state()["messages"][-1]
    assert "Tập 3" in last["text"] and "Đã lên lịch" in last["text"]
    assert [lk["href"] for lk in last["data"]["links"]] == [f"/posts?post={new['id']}", "/schedule"]


@pytest.mark.asyncio
async def test_a_plan_that_posts_by_itself_waits_for_ok(client, monkeypatch, writer):
    ch = _story_series(client)
    monkeypatch.setattr("flowboard.services.scheduler.can_auto", lambda cid: True)  # the page is connected
    at = _later()

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        return json.dumps({"reply": "Ok.", "actions": [
            {"tool": "write_post", "args": {"channel_id": ch, "series": "những thú vị về hệ mặt trời"}},
            {"tool": "schedule_post", "args": {"post": "previous", "at": at, "story": True}}]}, ensure_ascii=False)

    monkeypatch.setattr(assistant, "run_llm", fake_llm)
    out = await assistant.chat("viết tập tiếp cho kênh chúng ta hay tò mò rồi tự đăng 12h mai, thêm vào tin luôn")
    assert out["task"]["status"] == "pending" and out["messages"][1]["data"]["confirm"] == out["task"]["id"]
    assert "tự đăng công khai" in out["messages"][1]["text"] and "thêm vào tin" in out["messages"][1]["text"]
    await asyncio.sleep(0.1)
    assert writer["writes"] == [] and all(p["episode"] != 3 for p in client.get("/api/posts").json())  # nothing ran yet
    done = await assistant.chat("ok")  # the go-ahead, without asking the AI again
    assert done["task"]["status"] == "running"
    assert await _until(lambda: assistant.task_outcome(out["task"]["id"])["status"] != "running")
    new = next(p for p in client.get("/api/posts").json() if p["episode"] == 3)
    assert new["schedule"]["auto"] is True
    from flowboard.db import get_session
    from flowboard.db.models import Schedule

    with get_session() as s:
        assert s.get(Schedule, new["schedule"]["slot_id"]).fb_story is True
    # "thôi" drops a waiting plan
    out2 = await assistant.chat("viết tập tiếp cho kênh chúng ta hay tò mò rồi tự đăng 12h mai")
    assert out2["task"]["status"] == "pending"
    await assistant.chat("thôi")
    assert assistant.task_outcome(out2["task"]["id"])["status"] == "canceled"


def test_off_topic_and_small_talk_get_a_canned_reply_without_the_ai():
    q = assistant.quick_reply
    for text in ("ê m 1+1= mấy?", "thời tiết hôm nay thế nào", "ai là tổng thống mỹ", "anh ơi 2+2 bằng mấy", "tóc ngắn hơn chút"):
        assert q(text) == assistant.OFF_TOPIC_REPLY, text
    assert q("hi") == assistant.GREETING_REPLY and q("cảm ơn") == assistant.THANKS_REPLY
    for text in ("tạo cho tao mẫu giống ngọc trinh", "tao muon tao mau nu han quoc", "lam clip cho sp nay https://s.shopee.vn/abc",
                 "bạn làm được gì", "tao muốn 1 con nhỏ tóc dài", "cho tao 1 hot girl hàn quốc", "đổi tóc ngắn đi",
                 "tạo 1 bài viết cho kênh chú ta hay tò mò, tập 7 trong series những thú vị về hệ mặt trời"):
        assert q(text) is None, text
    # in a conversation a describing word is a follow-up; an answer to the assistant's question always goes through
    assert q("tóc ngắn hơn chút", "Xong rồi!", in_conversation=True) is None
    assert q("2+2", "Bạn muốn người mẫu nam hay nữ?", in_conversation=True) is None


@pytest.mark.asyncio
async def test_a_canned_reply_spends_no_tokens(monkeypatch):
    async def never(*a, **k):
        raise AssertionError("the AI must not be called")

    monkeypatch.setattr(assistant, "run_llm", never)
    out = await assistant.chat("ê m 1+1= mấy?")
    assert out["task"] is None and out["messages"][1]["text"] == assistant.OFF_TOPIC_REPLY and out["messages"][1]["data"]["canned"]


@pytest.mark.asyncio
async def test_auto_post_sets_a_fixed_schedule_after_the_go_ahead(client, monkeypatch):
    """"tự động đăng kênh … T2-T6 20h": checked against the catalog, waits for "ok", then the plan is on (services/autopilot)."""
    a = assistant.parse_answer(json.dumps({"reply": "Ok", "actions": [{"tool": "auto_post", "args": {
        "channel_id": "chung ta hay to mo", "days": [0, 1, 2, 3, 4, 9], "times": ["20:00", "7:5", "8:30"],
        "series": "nhung thu vi ve he mat troi"}}]}, ensure_ascii=False), _cat())
    g = a["actions"][0]["args"]
    assert g["channel_id"] == 2 and g["days"] == [0, 1, 2, 3, 4] and g["times"] == ["08:30", "20:00"]
    assert g["series"] == "những thú vị về hệ mặt trời" and g["images"] == 1 and g["ai"] == "claude"
    assert assistant.needs_go_ahead(a["actions"], _cat())
    assert "T2 T3 T4 T5 T6" in assistant._plan_summary(a["actions"], _cat())[0]
    q = assistant.parse_answer(json.dumps({"reply": "", "actions": [{"tool": "auto_post", "args": {
        "channel_id": 3, "days": [0], "times": ["20:00"]}}]}), _cat())
    assert q["actions"] == [] and "chưa kết nối Facebook Page" in q["reply"]
    assert "đặt lịch tự động" in assistant.SKILLS_VI and assistant.quick_reply("tự động đăng kênh mẹ bầu mỗi ngày 20h") is None

    ch = client.post("/api/channels", json={"name": "Chúng ta hay tò mò", "platforms": ["facebook"]}).json()["id"]
    monkeypatch.setattr("flowboard.services.scheduler.can_auto", lambda cid: True)

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        return json.dumps({"reply": "Ok.", "actions": [{"tool": "auto_post", "args": {
            "channel_id": ch, "days": [5, 6], "times": ["09:00"], "kind": "tips", "ai": "gemini"}}]}, ensure_ascii=False)

    monkeypatch.setattr(assistant, "run_llm", fake_llm)
    out = await assistant.chat("tự động đăng mẹo vặt cho kênh chúng ta hay tò mò cuối tuần 9h sáng")
    assert out["task"]["status"] == "pending"
    from flowboard.services import autopilot

    assert autopilot.list_plans() == []  # nothing before the go-ahead
    await assistant.chat("ok")
    assert await _until(lambda: assistant.task_outcome(out["task"]["id"])["status"] != "running")
    plans = autopilot.list_plans()
    assert len(plans) == 1 and plans[0]["days"] == [5, 6] and plans[0]["times"] == ["09:00"] and plans[0]["ai"] == "gemini"
    assert plans[0]["brief"]["kind"] == "tips" and plans[0]["enabled"] is True
    assert "tự động đăng" in assistant.state()["messages"][-1]["text"]
