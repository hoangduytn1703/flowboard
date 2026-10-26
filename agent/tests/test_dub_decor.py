"""Frame + dancing mascot of the dubbing editor (services/dub_decor), burned
with real ffmpeg in the same graph as the blur band and the subtitles."""
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from flowboard.services import dub, dub_decor

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")


def test_layout_keeps_frame_and_mascot_and_clamps_them():
    lay = dub.normalize_layout({"x": 0.5, "y": 0.8, "scale": 1,
                                "frame": {"scale": 0.3, "bg": "weird", "color": "red", "border": 0.5},
                                "mascot": {"media_id": "abc", "size": 2, "motion": "moonwalk", "shape": "star"}})
    assert lay["frame"] == {"scale": 0.6, "bg": "blur", "bg_image": "", "color": "#111111", "border": 0.03, "border_color": "#ffd814"}
    assert lay["mascot"]["size"] == 0.6 and lay["mascot"]["motion"] == "dance" and lay["mascot"]["shape"] == "circle"
    off = dub.normalize_layout({"frame": None, "mascot": {"media_id": ""}})
    assert off["frame"] is None and off["mascot"] is None


def test_filter_graph_order_is_frame_blur_mascot_subtitles(tmp_path):
    lay = {"frame": {"scale": 0.8}, "blur": {"x": 0.1, "y": 0.6, "w": 0.8, "h": 0.07, "amount": 5},
           "mascot": {"media_id": "m", "motion": "bounce"}}
    g = dub.video_filter(tmp_path / "s.ass", 720, 1280, lay, mascot_index=2)
    assert g.index("[fr_a]") < g.index("[vb_base]") < g.index("[2:v]") < g.index("ass=")
    assert g.endswith("[v]") and "abs(sin(" in g
    # no decoration: the old graph (subtitles only)
    assert dub.video_filter(tmp_path / "s.ass", 720, 1280, {}).startswith("[0:v]ass=")


def _portrait(path: Path) -> Path:
    img = Image.new("RGB", (400, 600), (30, 120, 200))
    img.paste((240, 200, 160), (120, 60, 280, 260))  # a "face" near the top
    img.save(path)
    return path


def test_circle_mascot_is_cropped_from_the_top_with_a_transparent_corner(tmp_path, monkeypatch):
    from flowboard.services import media as media_service

    src = _portrait(tmp_path / "model.jpg")
    monkeypatch.setattr(media_service, "cached_path", lambda mid: src)
    out, animated = dub_decor.prepare_mascot({"media_id": "x", "size": 0.25, "shape": "circle"}, 1280, tmp_path)
    img = Image.open(out)
    assert not animated and img.size == (320, 320) and img.mode == "RGBA"
    assert img.getpixel((2, 2))[3] == 0 and img.getpixel((160, 160))[3] == 255  # corner clear, centre opaque
    plain, _ = dub_decor.prepare_mascot({"media_id": "x", "size": 0.25, "shape": "plain"}, 1280, tmp_path)
    assert Image.open(plain).size[1] == 320


@needs_ffmpeg
@pytest.mark.parametrize("animated", [False, True])
def test_full_render_graph_runs_with_ffmpeg(tmp_path, monkeypatch, animated):
    from flowboard.services import media as media_service

    src = tmp_path / "src.mp4"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=720x1280:rate=30:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-shortest", "-pix_fmt", "yuv420p", str(src)], check=True)
    voice = tmp_path / "voice.wav"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=660:duration=3", str(voice)], check=True)
    if animated:
        frames = [Image.new("RGB", (200, 300), c) for c in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
        sticker = tmp_path / "dance.gif"
        frames[0].save(sticker, save_all=True, append_images=frames[1:], duration=120, loop=0)
        shape = "plain"
    else:
        sticker, shape = _portrait(tmp_path / "model.jpg"), "circle"
    monkeypatch.setattr(media_service, "cached_path", lambda mid: sticker)
    layout = {"x": 0.5, "y": 0.8, "scale": 1, "blur": {"x": 0.1, "y": 0.62, "w": 0.8, "h": 0.07, "amount": 5},
              "frame": {"scale": 0.82, "bg": "blur", "border": 0.008},
              "mascot": {"media_id": "m", "x": 0.82, "y": 0.92, "size": 0.25, "motion": "dance", "shape": shape}}
    ass = dub.write_sub_ass([(0.2, 2.5, "Xin chào các mẹ bầu")], tmp_path / "s.ass", width=720, height=1280, layout=dub.normalize_layout(layout))
    mascot = dub_decor.prepare_mascot(dub.normalize_layout(layout)["mascot"], 1280, tmp_path)
    assert mascot is not None and mascot[1] is animated
    out = tmp_path / "out.mp4"
    cmd = [FFMPEG, "-y", "-v", "error", "-i", str(src), "-i", str(voice), *dub_decor.mascot_input_args(*mascot),
           "-filter_complex", dub.video_filter(ass, 720, 1280, layout, 2, mascot[1]),
           "-map", "[v]", "-map", "1:a:0", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-shortest", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-600:]
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
                            "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.split()
    assert probe[0].startswith("720,1280") and 2.5 <= float(probe[-1]) <= 3.5  # the endless sticker does not stretch the video


# ── AI chat, cutout, favourites, picture background ─────────────────────────

def test_ai_chat_turns_a_wish_into_frame_and_sticker_changes(client, monkeypatch):
    import json as _json

    from flowboard.services import decor_ai

    seen = {}

    async def fake_llm(feature, prompt, *, system_prompt=None, timeout=0):
        seen["prompt"], seen["system"] = prompt, system_prompt
        return _json.dumps({"reply": "Đã làm khung hoa đào và bé chibi bầu.",
                            "frame": {"scale": 0.8, "bg": "image", "border": 0.01, "border_color": "#ffffff",
                                      "bg_prompt": "Pink peach blossom border artwork, empty pastel centre, no text"},
                            "mascot": {"image_prompt": "Cute 3D chibi pregnant woman waving, plain pure white background",
                                       "shape": "plain", "motion": "dance", "size": 0.3, "corner": "bottom_left"}})

    monkeypatch.setattr(decor_ai, "run_llm", fake_llm)
    client.post("/api/dub/decor/presets", json={"kind": "frame", "name": "Khung vàng", "data": {"scale": 0.9, "bg": "color", "color": "#ffee00"}})
    out = client.post("/api/dub/decor/chat", json={"message": "khung hoa đào, thêm bé chibi bầu vẫy tay góc trái",
                                                   "frame": None, "mascot": None, "orientation": "portrait"}).json()
    assert out["frame"]["bg"] == "image" and out["frame"]["bg_image"] == "" and out["frame"]["scale"] == 0.8
    assert out["bg_prompt"].startswith("Pink peach") and out["image_prompt"].startswith("Cute 3D chibi")
    assert out["mascot"]["shape"] == "plain" and (out["mascot"]["x"], out["mascot"]["y"]) == (0.17, 0.9)
    assert "only" in seen["system"].lower() and "SAVED" in seen["prompt"] and "Khung vàng" in seen["prompt"]


def test_ai_chat_can_switch_things_off_and_keep_the_rest(monkeypatch):
    import asyncio
    import json as _json

    from flowboard.services import decor_ai

    async def fake_llm(*a, **k):
        return _json.dumps({"reply": "Đã bỏ khung.", "frame": "off", "mascot": {"motion": "sway", "image_prompt": ""}})

    monkeypatch.setattr(decor_ai, "run_llm", fake_llm)
    cur = {"media_id": "abc", "x": 0.8, "y": 0.9, "size": 0.25, "motion": "dance", "shape": "circle"}
    out = asyncio.run(decor_ai.chat("bỏ khung, cho bé lắc lư thôi", frame={"scale": 0.8}, mascot=cur))
    assert out["frame"] == "off" and out["mascot"]["media_id"] == "abc" and out["mascot"]["motion"] == "sway"
    assert out["image_prompt"] == ""


def test_cutout_clears_a_plain_white_background(tmp_path):
    img = Image.new("RGB", (200, 300), (255, 255, 255))
    img.paste((200, 40, 90), (60, 50, 140, 260))  # the character
    src = tmp_path / "ai.png"
    img.save(src)
    out = Image.open(dub_decor.cutout(src, tmp_path / "cut.png"))
    assert out.mode == "RGBA" and out.size[0] <= 90 and out.size[1] <= 215  # cropped to the character
    assert out.getpixel((out.size[0] // 2, out.size[1] // 2))[3] == 255
    # a photo with a busy border is left alone
    busy = Image.effect_noise((120, 120), 90).convert("RGB")
    busy.save(tmp_path / "busy.png")
    assert Image.open(dub_decor.cutout(tmp_path / "busy.png", tmp_path / "busy_cut.png")).size == (120, 120)


def test_presets_are_saved_normalised_listed_used_and_deleted(client):
    r = client.post("/api/dub/decor/presets", json={"kind": "mascot", "name": "Bé chibi",
                                                    "data": {"media_id": "m1", "motion": "dance", "shape": "plain", "size": 9}})
    p = r.json()
    assert r.status_code == 201 and p["data"]["size"] == 0.6 and p["thumb"] == "m1"
    assert client.post("/api/dub/decor/presets", json={"kind": "mascot", "data": {"media_id": ""}}).status_code == 400
    client.post(f"/api/dub/decor/presets/{p['id']}/use")
    assert client.get("/api/dub/decor/presets", params={"kind": "mascot"}).json()[0]["uses"] == 1
    assert client.delete(f"/api/dub/decor/presets/{p['id']}").json() == {"ok": True}
    assert client.get("/api/dub/decor/presets").json() == []


@needs_ffmpeg
def test_frame_with_a_picture_background_renders(tmp_path, monkeypatch):
    from flowboard.services import media as media_service

    src = tmp_path / "src.mp4"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=720x1280:rate=30:duration=2",
                    "-pix_fmt", "yuv420p", str(src)], check=True)
    voice = tmp_path / "voice.wav"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=500:duration=2", str(voice)], check=True)
    art = tmp_path / "art.png"
    Image.new("RGB", (900, 1600), (250, 200, 220)).save(art)
    monkeypatch.setattr(media_service, "cached_path", lambda mid: art)
    layout = {"frame": {"scale": 0.8, "bg": "image", "bg_image": "art1", "border": 0.01}}
    frame = dub.normalize_layout(layout)["frame"]
    assert frame["bg"] == "image" and dub_decor.frame_bg_path(frame) == art
    ass = dub.write_sub_ass([(0.1, 1.8, "Xin chào")], tmp_path / "s.ass", width=720, height=1280, layout=dub.normalize_layout(layout))
    out = tmp_path / "out.mp4"
    cmd = [FFMPEG, "-y", "-v", "error", "-i", str(src), "-i", str(voice), "-loop", "1", "-framerate", "30", "-i", str(art),
           "-filter_complex", dub.video_filter(ass, 720, 1280, layout, frame_bg_index=2),
           "-map", "[v]", "-map", "1:a:0", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-shortest", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-600:]
    frame_png = tmp_path / "f.png"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-ss", "1", "-i", str(out), "-frames:v", "1", str(frame_png)], check=True)
    corner = Image.open(frame_png).convert("RGB").getpixel((10, 10))
    assert abs(corner[0] - 250) < 20 and abs(corner[1] - 200) < 20  # the picture shows around the video
