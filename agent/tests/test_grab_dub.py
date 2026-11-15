""""🎙 Lồng tiếng ngay" on the grab list (services/grab_dub): download → dubbing queue, one video never holds the rest."""
import asyncio

import pytest

from flowboard import plans
from flowboard.services import channel_grab as grab
from flowboard.services import dub, grab_dub, tts, video_fetch
from tests.test_channel_grab import _scan_done, _wait, listed  # noqa: F401 — the fake channel listing


@pytest.fixture
def ready(client, listed, monkeypatch):  # noqa: F811
    monkeypatch.setattr(dub, "status", lambda: {"available": True, "whisper": True, "separate": True, "ytdlp": True, "root": "x"})
    started = []
    monkeypatch.setattr(dub, "_run_job", lambda j, render: started.append(j.id))  # jobs never finish by themselves
    monkeypatch.setattr(grab, "DOWNLOAD_RETRY_WAIT_S", 0.0)
    grab_dub.ITEMS.clear()
    dub.JOBS.clear()
    cid = client.post("/api/grab/channels", json={"url": "https://www.tiktok.com/@kenh"}).json()["id"]
    _scan_done(cid)
    vids = client.get("/api/grab/videos").json()
    yield client, vids, started
    grab_dub.ITEMS.clear()
    dub.JOBS.clear()


def _fetch(fail_first=(), never=()):
    seen: dict[str, int] = {}

    def fake(url, media_id, out_dir, *, max_duration_s=None, stop=None):
        seen[url] = seen.get(url, 0) + 1
        if any(url.endswith(n) for n in never):
            raise video_fetch.FetchError("video dài hơn 60 phút")
        if any(url.endswith(n) for n in fail_first) and seen[url] == 1:
            raise video_fetch.FetchError("Douyin không trả dữ liệu")
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{media_id}.mp4"
        path.write_bytes(b"not a real video")
        return path, "Tên từ trang"

    return fake, seen


def test_one_click_downloads_then_dubs_and_a_bad_video_holds_nobody(ready, monkeypatch):
    client, vids, started = ready
    a, b, c = vids[0], vids[1], vids[2]
    fake, seen = _fetch(fail_first=(a["url"][-7:],), never=(b["url"][-7:],))
    monkeypatch.setattr(video_fetch, "fetch_video", fake)
    assert client.post("/api/grab/dub", json={"ids": [a["id"]], "voice": "khong-co"}).status_code == 400
    r = client.post("/api/grab/dub", json={"ids": [a["id"], b["id"], c["id"]], "mode": "sub", "sub_lang": "orig"})
    assert r.status_code == 200 and r.json() == {"queued": 3, "skipped": 0}
    # sent twice while on their way: skipped
    assert client.post("/api/grab/dub", json={"ids": [a["id"]]}).json()["skipped"] in (0, 1)

    def settled():
        w = client.get("/api/grab/work").json()
        return all(str(v["id"]) in w and w[str(v["id"])]["dub"]["state"] != "downloading" for v in (a, b, c))

    _wait(settled, 20)
    w = client.get("/api/grab/work").json()
    # a: its first download was refused, tried again by itself; c: straight through — both are dub jobs now
    assert seen[a["url"]] == 2
    for v in (a, c):
        d = w[str(v["id"])]["dub"]
        assert d["state"] == "running" and d["id"] in dub.JOBS and d["mode"] == "sub"
        job = dub.JOBS[d["id"]]
        assert job.title == v["title"] and job.sub_lang == "orig" and job.source_media_id
    # b: too long — said on its card, never retried, the others went on
    assert seen[b["url"]] == 1
    assert w[str(b["id"])]["dub"]["state"] == "error" and "60 phút" in w[str(b["id"])]["dub"]["error"]
    # the queue position is on the waiting one's card
    aheads = sorted(w[str(v["id"])]["dub"]["ahead"] or 0 for v in (a, c))
    assert aheads == [0, 1] and len(started) == 1
    # no clip yet (the job runs): the card shows the run, "🎙 đã lồng" waits for the clip
    assert {v["id"]: v for v in client.get("/api/grab/videos").json()}[c["id"]]["used"] == {}
    # "Dừng tất cả"
    ours = [w[str(v["id"])]["dub"]["id"] for v in (a, c)]
    out = client.post("/api/grab/dub/stop").json()
    assert out["stopped"] == 2
    # only this lot's jobs: the list also reads jobs other tests saved (finished long ago, left as they were)
    assert all(dub.JOBS[i].stop or dub.JOBS[i].error.startswith("Đã dừng") for i in ours)


def test_a_full_dubbing_queue_makes_the_video_wait_not_fail(ready, monkeypatch):
    client, vids, _started = ready
    fake, _seen = _fetch()
    monkeypatch.setattr(video_fetch, "fetch_video", fake)
    monkeypatch.setattr(dub, "MAX_QUEUE", 1)
    ids = [v["id"] for v in vids[:3]]
    client.post("/api/grab/dub", json={"ids": ids})
    _wait(lambda: len(dub.JOBS) == 2 and any(it.status == "wait" for it in grab_dub.ITEMS.values()), 20)
    w = client.get("/api/grab/work").json()
    waiting = [i for i in ids if w[str(i)]["dub"]["phase"].startswith("Chờ hàng đợi")]
    assert len(waiting) == 1
    # room appears → it goes in by itself
    running = dub.running_job()
    running.status = "done"
    dub._pump()
    _wait(lambda: len(dub.JOBS) == 3, 20)


def test_states_names_and_the_plan_rule():
    assert grab._tool_state("error", dub.NO_SPEECH) == "nospeech"
    assert grab._tool_state("error", "Đã dừng theo yêu cầu") == "stopped" and grab._tool_state("error", "x") == "error"
    assert grab.passing_failure("Không tải được: Douyin không trả dữ liệu")
    assert not grab.passing_failure("Không tải được: video dài hơn 60 phút") and not grab.passing_failure(grab.STOPPED)
    assert plans.feature_for("POST", "/api/grab/dub") == ("dub",) and plans.feature_for("POST", "/api/grab/dub/stop") == ("dub",)
    # a Chinese caption is translated from Chinese even when Whisper heard "en" in the music
    job = dub.Job(id="t", url=None, source_media_id="m", voice=tts.DEFAULT_VOICE, keep_bgm=False, style="box_yellow")
    job.language = "en"
    assert dub._title_lang(job, "冷冰冰的雪山") is None and dub._title_lang(job, "Cold mountain") == "en"
    job.language = "zh"
    assert dub._title_lang(job, "冷冰冰的雪山") == "zh"


def test_the_name_check_gives_up_after_its_time(monkeypatch):
    from flowboard.services import dub_names

    async def slow(*a, **k):
        await asyncio.sleep(5)
        return {}, []

    monkeypatch.setattr(dub_names, "check", slow)
    monkeypatch.setattr(dub, "NAMES_TIMEOUT_S", 0.05)
    job = dub.Job(id="t2", url=None, source_media_id="m", voice=tts.DEFAULT_VOICE, keep_bgm=False, style="box_yellow")
    job.segments = [dub.Segment(start=0, end=1, src="你好", text="Xin chào")]
    asyncio.new_event_loop().run_until_complete(dub._check_names(job))
    assert "chậm quá" in job.names_note and job.segments[0].text == "Xin chào"
