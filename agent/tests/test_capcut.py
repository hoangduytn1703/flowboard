"""Edit auto CapCut: learning the user's styles, writing a project CapCut lists,
subtitles, key moments, cutting pauses, and bringing the exported video back."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from flowboard.services import capcut_auto as auto
from flowboard.services import capcut_draft as cc

S = cc.S


def _text(tid: str, text: str, size: float, y: float) -> tuple[dict, dict, dict]:
    anim = {"id": f"A-{tid}", "type": "sticker_animation", "animations": []}
    mat = {"id": f"M-{tid}", "type": "text", "font_size": size, "text_color": "#ffffff", "fonts": [{"title": f"Font{tid}"}],
           "content": json.dumps({"text": text, "styles": [{"size": size, "range": [0, len(text)]}]}, ensure_ascii=False),
           "words": {"start_time": [], "end_time": [], "text": []}}
    seg = {"id": f"S-{tid}", "material_id": mat["id"], "extra_material_refs": [anim["id"]], "source_timerange": None,
           "target_timerange": {"start": 0, "duration": 2 * S}, "render_index": 14000,
           "clip": {"scale": {"x": 0.4, "y": 0.4}, "rotation": 0.0, "transform": {"x": 0.0, "y": y}, "alpha": 1.0}}
    return seg, mat, anim


def _drafts(tmp_path: Path, sound: Path) -> Path:
    """A drafts root with one project made "by hand" in CapCut: a video, three labelled texts, one sound effect."""
    root = tmp_path / "com.lveditor.draft"
    tid = "TL-1"
    pdir = root / "Mine"
    (pdir / "Timelines" / tid).mkdir(parents=True)
    speed = {"id": "SP-1", "type": "speed", "speed": 1.0}
    video = {"id": "V-1", "type": "video", "path": "C:/x.mp4", "duration": 10 * S, "width": 720, "height": 1280,
             "material_name": "x.mp4", "crop": {}, "local_material_id": "old"}
    vseg = {"id": "VS-1", "material_id": "V-1", "extra_material_refs": ["SP-1"], "volume": 1.0,
            "source_timerange": {"start": 0, "duration": 10 * S}, "target_timerange": {"start": 0, "duration": 10 * S},
            "clip": {"scale": {"x": 1.0, "y": 1.0}, "rotation": 0.0, "transform": {"x": 0.0, "y": 0.0}, "alpha": 1.0},
            "common_keyframes": []}
    sfx = {"id": "SFX-1", "type": "sound", "name": "Pop", "path": str(sound), "duration": int(0.8 * S)}
    beats = {"id": "B-1", "type": "beats"}
    aseg = {"id": "AS-1", "material_id": "SFX-1", "extra_material_refs": ["B-1"], "volume": 1.0,
            "source_timerange": {"start": 0, "duration": int(0.8 * S)}, "target_timerange": {"start": 0, "duration": int(0.8 * S)}}
    texts = [_text("1", "Phụ đề", 15, -0.45), _text("2", "Nhấn mạnh", 15, -0.5), _text("3", "Tiêu đề", 39, 0.5)]
    content = {"id": tid, "duration": 10 * S, "fps": 30.0, "canvas_config": {"ratio": "original", "width": 1920, "height": 1080},
               "platform": {"os": "windows"}, "keyframes": {"videos": []}, "relationships": [],
               "materials": {"videos": [video], "audios": [sfx], "texts": [t[1] for t in texts],
                             "speeds": [speed], "beats": [beats], "material_animations": [t[2] for t in texts]},
               "tracks": [{"id": "T-v", "type": "video", "segments": [vseg]},
                          {"id": "T-a", "type": "audio", "segments": [aseg]},
                          *({"id": f"T-t{i}", "type": "text", "segments": [t[0]]} for i, t in enumerate(texts))]}
    for p in (pdir / "draft_content.json", pdir / "Timelines" / tid / "draft_content.json"):
        p.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    (pdir / "timeline_layout.json").write_text(json.dumps(
        {"dockItems": [{"dockIndex": 0, "ratio": 1, "timelineIds": [tid], "timelineNames": ["Timeline 01"]}],
         "layoutOrientation": 1}), encoding="utf-8")
    (pdir / "Timelines" / "project.json").write_text(json.dumps({"id": "P-1", "main_timeline_id": tid, "timelines": []}), encoding="utf-8")
    (pdir / "draft_meta_info.json").write_text(json.dumps(
        {"draft_id": "OLD", "draft_name": "Mine", "draft_materials": [{"type": 0, "value": [{"id": "x"}]}, {"type": 8, "value": []}]}),
        encoding="utf-8")
    (pdir / "draft_agency_config.json").write_text("{}", encoding="utf-8")
    (root / "root_meta_info.json").write_text(json.dumps(
        {"all_draft_store": [{"draft_name": "Mine", "draft_fold_path": pdir.as_posix(), "draft_id": "OLD"}],
         "draft_ids": 1, "root_path": root.as_posix()}), encoding="utf-8")
    return root


@pytest.fixture()
def drafts(tmp_path, monkeypatch) -> Path:
    sound = tmp_path / "pop.mp3"
    sound.write_bytes(b"x")
    root = _drafts(tmp_path, sound)
    monkeypatch.setenv("FLOWBOARD_CAPCUT_DRAFTS", str(root))
    monkeypatch.setattr(cc, "capcut_running", lambda: False)
    return root


def test_learn_finds_the_styles_by_their_sample_text(drafts):
    kho = cc.learn(drafts)
    assert len(kho["texts"]) == 3 and list(kho["sounds"]) == ["s1"]
    roles = {kho["texts"][v]["examples"][0]: k for k, v in kho["aliases"].items()}
    assert roles == {"Phụ đề": "subtitle", "Nhấn mạnh": "emphasis", "Tiêu đề": "title"}
    assert kho["base"] == "Mine" and kho["video_tpl"] and kho["audio_tpl"]


def test_a_new_project_is_written_and_listed_on_capcuts_home(drafts, tmp_path):
    kho = cc.learn(drafts)
    base = cc.base_project(drafts, kho)
    b = cc.DraftBuilder(kho, cc.base_content(base), 576, 1024)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    b.add_video(clip, duration_s=20, width=576, height=1024, has_audio=True, start=0, src_start=0, dur=4)
    b.add_video(clip, duration_s=20, width=576, height=1024, has_audio=True, start=4, src_start=6, dur=3)
    b.add_text("subtitle", 0.5, 1.0, "Chỉ 99k", lane="subtitle")
    b.add_text("subtitle", 1.5, 1.0, "mà dùng", lane="subtitle")
    b.add_text("emphasis", 0.6, 1.2, "99K", lane="emphasis")
    assert b.add_zoom(0.6) is True
    assert b.add_sfx(0.6) == "s1"
    res = cc.create_project(drafts, "Clip: thử/1", b, base, None)
    pdir = Path(res["folder"])
    assert pdir.name == "Clip thử 1" and res["counts"] == {"video": 2, "audio": 0, "text": 3, "sfx": 1, "zoom": 1}
    d = json.loads((pdir / "draft_content.json").read_text(encoding="utf-8"))
    tl = json.loads((pdir / "Timelines" / d["id"] / "draft_content.json").read_text(encoding="utf-8"))
    assert d == tl and d["canvas_config"]["width"] == 576 and d["duration"] == 7 * S
    assert len(d["materials"]["videos"]) == 1  # two pieces of one file share its material
    vt = next(t for t in d["tracks"] if t["type"] == "video")
    assert [s["source_timerange"]["start"] for s in vt["segments"]] == [0, 6 * S]
    assert vt["segments"][0]["common_keyframes"][0]["property_type"] == "KFTypeScaleX"
    texts = [json.loads(m["content"])["text"] for m in d["materials"]["texts"]]
    assert texts == ["Chỉ 99k", "mà dùng", "99K"]
    assert len([t for t in d["tracks"] if t["type"] == "text"]) == 2  # subtitles on one track, the key word on another
    ids = {m["id"] for v in d["materials"].values() if isinstance(v, list) for m in v}
    assert len(ids) == sum(len(v) for v in d["materials"].values() if isinstance(v, list))  # every id fresh
    meta = json.loads((pdir / "draft_meta_info.json").read_text(encoding="utf-8"))
    assert meta["draft_name"] == "Clip thử 1" and meta["draft_id"] == res["draft_id"] and len(meta["draft_materials"][0]["value"]) == 1
    reg = json.loads((drafts / "root_meta_info.json").read_text(encoding="utf-8"))
    assert [e["draft_name"] for e in reg["all_draft_store"]] == ["Clip thử 1", "Mine"] and reg["draft_ids"] == 2
    assert (drafts / "root_meta_info.json.flowboard.bak").is_file()
    # a second one with the same name gets its own folder
    again = cc.create_project(drafts, "Clip: thử/1", cc.DraftBuilder(kho, cc.base_content(base), 576, 1024), base, None)
    assert Path(again["folder"]).name == "Clip thử 1 (2)"
    assert cc.remove_project(drafts, again["folder"]) is True
    assert not Path(again["folder"]).exists()


def test_nothing_is_written_while_capcut_runs(drafts, monkeypatch):
    kho = cc.learn(drafts)
    base = cc.base_project(drafts, kho)
    monkeypatch.setattr(cc, "capcut_running", lambda: True)
    with pytest.raises(cc.CapcutError):
        cc.create_project(drafts, "x", cc.DraftBuilder(kho, cc.base_content(base), 720, 1280), base, None)
    assert [p.name for p in drafts.iterdir() if p.is_dir()] == ["Mine"]


def test_subtitles_tiktok_style_and_whole_lines():
    lines = [auto.Line(0.0, 4.0, "Chỉ 99k mà dùng cả năm, quá rẻ luôn.")]
    tiktok = auto.chunk_lines(lines, "tiktok")
    assert [c.text for c in tiktok] == ["Chỉ 99k mà dùng", "cả năm", "quá rẻ luôn"]
    assert tiktok[0].start == 0.0 and tiktok[-1].end == 4.0
    assert all(a.end == b.start for a, b in zip(tiktok, tiktok[1:]))  # back to back, no flicker
    assert [c.text for c in auto.chunk_lines(lines, "line")] == ["Chỉ 99k mà dùng cả năm, quá rẻ luôn."]
    assert auto.chunk_lines(lines, "off") == []
    heard = [auto.Line(1.0, 2.0, "một hai", [(1.0, 1.2, "một"), (1.6, 2.0, "hai")])]
    assert [(c.start, c.text) for c in auto.chunk_lines(heard, "tiktok")] == [(1.0, "một hai")]


def test_key_moments_are_found_in_their_line_and_kept_apart():
    lines = [auto.Line(0.0, 3.0, "Giá chỉ 99k thôi"), auto.Line(3.0, 6.0, "Chất vải siêu mát"), auto.Line(8.0, 11.0, "Mua ngay kẻo hết")]
    raw = [{"line": 1, "words": "99K"}, {"line": 2, "words": "siêu mát"}, {"line": 3, "words": "kẻo hết"},
           {"line": 9, "words": "x"}, {"line": 1, "words": "không có"}]
    pts = auto.place_points(lines, raw, 12.0)
    assert [p["words"] for p in pts] == ["99k"]  # 12 s → one point; the made-up and missing words are dropped
    pts = auto.place_points(lines, raw, 60.0)
    assert [p["words"] for p in pts] == ["99k", "kẻo hết"]  # "siêu mát" is < 5 s after "99k"
    assert auto._parse_points('Đây: {"points": [{"line": 1, "words": "99k"}]} xong') == [{"line": 1, "words": "99k"}]
    assert [p["words"] for p in auto.fallback_points(lines, 60.0)] == ["99k thôi"]


def test_pauses_are_cut_and_times_follow():
    lines = [auto.Line(1.0, 2.0, "một", [(1.0, 2.0, "một")]), auto.Line(5.0, 6.0, "hai", [(5.0, 6.0, "hai")])]
    keeps = auto.keep_ranges(lines, 10.0)
    assert keeps == [(0.88, 2.12), (4.88, 6.12)]
    moved = auto.remap_lines(lines, keeps)
    assert [(l.start, l.text) for l in moved] == [(0.12, "một"), (1.36, "hai")]
    assert auto.remap(3.0, keeps) is None


@pytest.fixture()
def capcut_storage(tmp_path, monkeypatch):
    from flowboard import config

    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path / "storage")
    return tmp_path


def test_styles_routes_and_status(client, drafts, capcut_storage):
    r = client.post("/api/capcut/learn")
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["aliases"]["emphasis"] and len(st["texts"]) == 3 and st["sounds"][0]["label"] == "Pop"
    r = client.put("/api/capcut/styles", json={"emphasis": "t3"})
    assert r.json()["aliases"]["emphasis"] == "t3"
    assert client.put("/api/capcut/styles", json={"emphasis": "t9"}).status_code == 400
    s = client.get("/api/capcut/status").json()
    assert s["capcut_installed"] is True and s["styles"]["aliases"]["emphasis"] == "t3"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_an_own_video_becomes_a_project_and_the_capcut_version_comes_back(client, drafts, capcut_storage, tmp_path, monkeypatch):
    from flowboard.services import media as media_service

    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path / "media")
    video = tmp_path / "own.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=360x640:d=8", "-f", "lavfi",
                    "-i", "sine=f=440:d=8", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)],
                   check=True)
    client.post("/api/capcut/learn")
    with video.open("rb") as fh:
        up = client.post("/api/capcut/upload", files={"file": ("own.mp4", fh, "video/mp4")}).json()
    heard = [auto.Line(0.5, 2.5, "Giá chỉ 99k thôi mọi người", [])]
    monkeypatch.setattr(auto, "_hear", lambda path, work, job, p0, p1: heard)

    async def fake_points(lines, duration):
        return auto.place_points(lines, [{"line": 1, "words": "99k"}], duration)

    monkeypatch.setattr(auto, "pick_points", fake_points)
    r = client.post("/api/capcut/jobs", json={"source": {"kind": "upload", "id": up["media_id"], "title": "Video của tôi"},
                                              "name": "Thử CapCut"})
    assert r.status_code == 201, r.text
    job = auto.JOBS[r.json()["id"]]
    for _ in range(200):
        if job.status in ("done", "error"):
            break
        import time

        time.sleep(0.05)
    assert job.status == "done", job.error
    res = job.result
    assert res["name"] == "Thử CapCut" and res["counts"]["text"] == 3 and res["counts"]["zoom"] == 1
    projects = client.get("/api/capcut/projects").json()
    assert projects[0]["name"] == "Thử CapCut" and projects[0]["exists"] is True and projects[0]["board_id"] is None
    # the edited video comes back: a clip of its own, holding it as its final video
    with video.open("rb") as fh:
        back = client.post(f"/api/capcut/projects/{projects[0]['id']}/return", files={"file": ("final.mp4", fh, "video/mp4")})
    assert back.status_code == 200, back.text
    bid = back.json()["board_id"]
    from flowboard.routes.exports import _final_media

    assert _final_media(bid) == back.json()["media_id"]
    assert client.get("/api/capcut/projects").json()[0]["returned"]["media_id"] == back.json()["media_id"]
    assert client.delete(f"/api/capcut/projects/{projects[0]['id']}?remove_folder=true").json() == {"ok": True}
    assert not Path(projects[0]["folder"]).exists() and client.get("/api/capcut/projects").json() == []


def test_every_sound_takes_its_turn_and_each_layer_keeps_its_own_track(drafts, tmp_path):
    import copy as _copy

    kho = cc.learn(drafts)
    long_one = _copy.deepcopy(kho["sounds"]["s1"])
    long_one["tpl"]["material"][1]["duration"] = 9 * S  # a long sound is used too, cut short
    long_one["duration"] = 9.0
    kho["sounds"]["s2"] = long_one
    b = cc.DraftBuilder(kho, cc.base_content(cc.base_project(drafts, kho)), 720, 1280)
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    b.add_video(clip, duration_s=30, width=720, height=1280, has_audio=True, start=0)
    assert [b.add_sfx(t) for t in (1, 6, 11, 16)] == ["s1", "s2", "s1", "s2"]
    sfx = [s for t in b.d["tracks"] if t["type"] == "audio" for s in t["segments"]]
    assert max(s["target_timerange"]["duration"] for s in sfx) == int(2.5 * S)
    b.add_text("subtitle", 0.0, 2.0, "một", lane="subtitle")
    b.add_text("emphasis", 2.5, 1.0, "HAI", lane="emphasis")  # a gap in the subtitles: still its own track
    b.add_text("subtitle", 2.0, 2.0, "ba", lane="subtitle")
    b.add_text("subtitle", 3.0, 2.0, "bốn", lane="subtitle")  # overlaps "ba": an extra subtitle track, not the key words'
    tracks = [[json.loads(next(m for m in b.d["materials"]["texts"] if m["id"] == s["material_id"])["content"])["text"]
               for s in t["segments"]] for t in b.d["tracks"] if t["type"] == "text"]
    assert tracks == [["một", "ba"], ["HAI"], ["bốn"]]


def test_subtitles_never_overlap():
    lines = [auto.Line(0.0, 2.5, "một hai ba bốn năm"), auto.Line(2.0, 4.0, "sáu bảy")]
    cues = auto.chunk_lines(lines, "tiktok")
    assert all(a.end <= b.start for a, b in zip(cues, cues[1:]))


def test_a_picked_style_stays_picked_when_new_styles_shift_the_numbers(drafts, capcut_storage, tmp_path):
    first = auto.learn()
    sub = first["aliases"]["subtitle"]
    label = first["texts"][sub]["label"]
    emph_label = first["texts"][first["aliases"]["emphasis"]]["label"]
    auto.choose_styles({"emphasis": first["aliases"]["title"]})  # the user picks the big one for key words
    picked = first["texts"][first["aliases"]["title"]]["label"]
    # a newer project with a style used many times → it becomes t1 and every number moves
    newer = drafts / "Newer"
    shutil.copytree(drafts / "Mine", newer)
    d = json.loads((newer / "draft_content.json").read_text(encoding="utf-8"))
    seg, mat, anim = _text("9", "Xin chào", 20, 0.0)
    mat["text_color"] = "#ffc800"
    d["materials"]["texts"].append(mat)
    d["materials"]["material_animations"].append(anim)
    d["tracks"].append({"id": "T-new", "type": "text", "segments": [
        {**seg, "id": f"S-9-{i}", "target_timerange": {"start": i * S, "duration": S}} for i in range(6)]})
    tid = json.loads((newer / "timeline_layout.json").read_text(encoding="utf-8"))["dockItems"][0]["timelineIds"][0]
    for p in (newer / "draft_content.json", newer / "Timelines" / tid / "draft_content.json"):
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    import os
    import time as _t

    os.utime(newer, (_t.time() + 5, _t.time() + 5))
    again = auto.learn()
    assert again["texts"]["t1"]["color"] == "#ffc800"  # the new style took number 1
    assert again["texts"][again["aliases"]["subtitle"]]["label"] == label
    assert again["texts"][again["aliases"]["emphasis"]]["label"] == picked != emph_label


def test_a_style_can_be_set_to_not_used_and_stays_so(drafts, capcut_storage):
    auto.learn()
    kho = auto.choose_styles({"subtitle": "", "emphasis": None})
    assert kho["aliases"]["subtitle"] == "" and kho["aliases"]["emphasis"]
    assert auto.learn()["aliases"]["subtitle"] == ""  # learning again keeps "— Không dùng —"
    with pytest.raises(auto.CapcutAutoError):
        auto.choose_styles({"title": "t9"})


def test_dub_first_then_carry_on_as_a_dubbed_video(monkeypatch):
    """Source "dub_new": the dub starts at once (its own queue); the CapCut job follows its progress, then goes on as "dub"."""
    from types import SimpleNamespace

    from flowboard.services import dub

    fake = SimpleNamespace(id="d1", status="queued", phase="Chờ", progress=0, error=None)
    started = {}

    def start_job(**kw):
        started.update(kw)
        dub.JOBS["d1"] = fake
        return fake

    monkeypatch.setattr(dub, "start_job", start_job)
    monkeypatch.setattr(auto.time, "sleep", lambda s: steps.pop(0)())
    steps = [lambda: setattr(fake, "status", "running"),
             lambda: (setattr(fake, "progress", 50), setattr(fake, "phase", "Đang dịch")),
             lambda: setattr(fake, "status", "done")]
    source = {"kind": "dub_new", "id": "", "title": "Video mới", "media_id": "m1"}
    sid = auto._start_dub(source, {"voice": "vi-VN-NamMinhNeural", "keep_bgm": True})
    assert sid == "d1" and started["source_media_id"] == "m1" and started["auto_render"] is True and started["name"] == "Video mới"
    job = auto.Job(id="j1", source={**source, "id": sid}, options={})
    auto._wait_dub(job)
    assert job.source["kind"] == "dub" and job.source["id"] == "d1" and job.progress == auto.DUB_SHARE
    fake.status, fake.error = "error", "Edge từ chối"
    job2 = auto.Job(id="j2", source={**source, "id": sid}, options={})
    with pytest.raises(auto.CapcutAutoError, match="Lồng tiếng lỗi: Edge từ chối"):
        auto._wait_dub(job2)
    dub.JOBS.pop("d1", None)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_a_video_by_link_becomes_an_upload(client, tmp_path, monkeypatch):
    from flowboard.services import media as media_service
    from flowboard.services import video_fetch

    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path / "media")

    def fake_fetch(text, media_id, out_dir, max_duration_s=None):
        out = out_dir / f"{media_id}.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=360x640:d=2", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", str(out)], check=True)
        return out, "Video Douyin hay"

    monkeypatch.setattr(video_fetch, "fetch_video", fake_fetch)
    r = client.post("/api/capcut/fetch", json={"url": "xem nè https://v.douyin.com/abc/ hay lắm"})
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "Video Douyin hay" and r.json()["width"] == 360
    assert client.post("/api/capcut/fetch", json={"url": "không có link nào"}).status_code == 400


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_subtitles_come_out_as_srt_from_the_project_or_only_as_srt(client, drafts, capcut_storage, tmp_path, monkeypatch):
    """⬇ .srt reads the CapCut project as it is now (hand-edited words included); "chỉ file .srt" puts no subtitle texts in."""
    import time as _t

    from flowboard.services import media as media_service

    monkeypatch.setattr(media_service, "MEDIA_CACHE_DIR", tmp_path / "media")
    video = tmp_path / "own.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=360x640:d=6", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    client.post("/api/capcut/learn")
    with video.open("rb") as fh:
        up = client.post("/api/capcut/upload", files={"file": ("own.mp4", fh, "video/mp4")}).json()
    monkeypatch.setattr(auto, "_hear", lambda path, work, job, p0, p1: [auto.Line(0.5, 2.5, "Giá chỉ 99k thôi mọi người", [])])

    async def no_points(lines, duration):
        return []

    monkeypatch.setattr(auto, "pick_points", no_points)

    def run(**opts):
        r = client.post("/api/capcut/jobs", json={"source": {"kind": "upload", "id": up["media_id"], "title": "Của tôi"}, **opts})
        job = auto.JOBS[r.json()["id"]]
        for _ in range(200):
            if job.status in ("done", "error"):
                break
            _t.sleep(0.05)
        assert job.status == "done", job.error
        return job.result

    res = run(name="Có chữ")
    assert res["subtitles"] == 2 and res["srt_lines"] == 2
    # the seller fixes a word in CapCut → the .srt follows the project
    pdir = Path(res["folder"])
    tl = next(p for p in pdir.rglob("draft_content.json") if "Timelines" in str(p))
    d = json.loads(tl.read_text(encoding="utf-8"))
    m = d["materials"]["texts"][0]
    c = json.loads(m["content"])
    c["text"] = "Giá chỉ 89k"
    m["content"] = json.dumps(c, ensure_ascii=False)
    tl.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    r = client.get(f"/api/capcut/projects/{res['project_id']}/srt")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert r.text.startswith("1\n00:00:00,500 --> ") and "Giá chỉ 89k\n" in r.text and "\nmọi người\n" in r.text
    only = run(name="Chỉ srt", srt_only=True)
    assert only["subtitles"] == 0 and only["srt_lines"] == 2
    assert "Giá chỉ 99k" in client.get(f"/api/capcut/projects/{only['project_id']}/srt").text
    assert client.get("/api/capcut/projects/nope/srt").status_code == 404
