"""★ Mẫu chỉnh sửa: a clip's whole look (layout, style, engine, key-moment settings) saved under a name, listed apart
from frames / stickers, one of them the default, and a new job starting with it."""
from __future__ import annotations

import pytest

from flowboard.services import dub


def test_a_look_is_normalized_without_the_points():
    look = dub.normalize_look_preset({"layout": {"x": 0.3, "canvas": {"aspect": "1:1"}, "blurs": [{"x": 0.1, "y": 0.2}]},
                                      "style": "box_white", "engine": "ass",
                                      "highlights": {"on": True, "points": [{"at": 1, "words": "x"}], "picked": "ai"}})
    assert look["layout"]["x"] == 0.3 and look["layout"]["canvas"]["aspect"] == "1:1" and len(look["layout"]["blurs"]) == 1
    assert look["style"] == "box_white" and look["engine"] == "ass"
    assert look["highlights"]["on"] and look["highlights"]["points"] == [] and look["highlights"]["picked"] == ""
    assert dub.normalize_look_preset(None)["style"] == "box_yellow"


def test_look_presets_are_saved_listed_defaulted_and_start_a_job(client, monkeypatch):
    r = client.post("/api/dub/decor/presets", json={"kind": "look", "name": "Page vũ trụ",
                                                    "data": {"layout": {"y": 0.9, "scale": 1.3}, "style": "outline", "engine": "ass",
                                                             "highlights": {"on": True, "points": [{"at": 2, "words": "a"}]}}})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["data"]["highlights"]["points"] == []
    assert [p["id"] for p in client.get("/api/dub/decor/presets?kind=look").json()] == [pid]
    assert client.get("/api/dub/decor/presets").json() == []  # the decor panel (frames / stickers) does not see looks
    assert client.get("/api/dub/decor/presets/default").json() == {"id": None}
    assert client.put("/api/dub/decor/presets/default", json={"id": pid}).status_code == 200
    assert client.get("/api/dub/decor/presets/default").json() == {"id": pid}
    assert client.put("/api/dub/decor/presets/default", json={"id": 9999}).status_code == 404
    # the services (the cut page's parts start from these too)
    assert dub.default_look_id() == pid
    assert dub.look_preset(pid, count=False)["style"] == "outline" and dub.look_preset(None) is None
    with pytest.raises(dub.DubError):
        dub.look_preset(9999)

    monkeypatch.setattr(dub, "status", lambda: {"available": True, "separate": False, "remotion": False})
    monkeypatch.setattr(dub, "_pump", lambda: None)
    r = client.post("/api/dub/jobs", json={"url": "https://v.douyin.com/abc", "voice": dub.tts.DEFAULT_VOICE, "keep_bgm": False,
                                           "style": "box_yellow", "engine": "ass", "auto_render": True, "look_preset_id": pid})
    j = r.json()
    try:
        assert r.status_code == 201, r.text
        assert j["style"] == "outline" and j["layout"]["y"] == 0.9 and j["layout"]["scale"] == 1.3
        assert j["highlights"]["on"] and j["highlights"]["points"] == []
        assert client.get("/api/dub/decor/presets?kind=look").json()[0]["uses"] == 1
        bad = client.post("/api/dub/jobs", json={"url": "https://v.douyin.com/abc", "voice": dub.tts.DEFAULT_VOICE, "keep_bgm": False,
                                                 "style": "box_yellow", "auto_render": True, "look_preset_id": 9999})
        assert bad.status_code == 404
    finally:
        dub.JOBS.pop(j.get("job_id"), None)
    # deleting the default leaves no default
    assert client.delete(f"/api/dub/decor/presets/{pid}").status_code == 200
    assert client.get("/api/dub/decor/presets/default").json() == {"id": None}


def test_a_template_is_renamed_starred_first_and_overwritten(client):
    def save(name: str) -> int:
        r = client.post("/api/dub/decor/presets", json={"kind": "look", "name": name,
                                                        "data": {"layout": {"y": 0.8}, "style": "outline", "engine": "ass"}})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    a, b = save("A"), save("B")
    listed = client.get("/api/dub/decor/presets?kind=look").json()
    assert [p["id"] for p in listed] == [b, a] and not any(p["favorite"] for p in listed)
    # ★ puts a template first
    r = client.patch(f"/api/dub/decor/presets/{a}", json={"favorite": True})
    assert r.status_code == 200 and r.json()["favorite"] is True
    assert [p["id"] for p in client.get("/api/dub/decor/presets?kind=look").json()] == [a, b]
    # rename (blank is refused)
    assert client.patch(f"/api/dub/decor/presets/{a}", json={"name": "  Page vũ trụ  "}).json()["name"] == "Page vũ trụ"
    assert client.patch(f"/api/dub/decor/presets/{a}", json={"name": "  "}).status_code == 400
    # overwrite the look with the editor's current one: normalised, points dropped, name / star kept
    r = client.patch(f"/api/dub/decor/presets/{a}", json={"data": {"layout": {"y": 0.5, "canvas": {"aspect": "9:16"}}, "style": "box_white",
                                                                     "engine": "ass", "highlights": {"on": True, "points": [{"at": 1, "words": "x"}]}}})
    p = r.json()
    assert r.status_code == 200 and p["data"]["layout"]["y"] == 0.5 and p["data"]["style"] == "box_white"
    assert p["data"]["highlights"]["points"] == [] and p["name"] == "Page vũ trụ" and p["favorite"] is True
    assert client.patch("/api/dub/decor/presets/9999", json={"favorite": True}).status_code == 404
    for pid in (a, b):
        client.delete(f"/api/dub/decor/presets/{pid}")
