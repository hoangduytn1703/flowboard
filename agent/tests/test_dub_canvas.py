"""Dub editor 29/10: several blur boxes instead of one, and the output format ("Khung xuất": 9:16, 16:9, 4:3,
1:1, 4:5, 3:4) — the source goes into the format first (blurred copy behind / black bars / cropped), then every
overlay is placed on the format's picture."""
from __future__ import annotations

import shutil
import subprocess

import pytest

from flowboard.services import dub
from flowboard.services.video_export import probe_clip


def test_an_old_single_blur_reads_as_a_list_and_boxes_are_capped():
    old = dub.normalize_layout({"blur": {"x": 0.1, "y": 0.6, "w": 0.8, "h": 0.07, "amount": 4}})
    assert old["blurs"] == [old["blur"]] and old["blur"]["amount"] == 4
    many = dub.normalize_layout({"blurs": [{"x": 0.1, "y": i / 20, "w": 0.3, "h": 0.04} for i in range(12)] + [None, {}]})
    assert len(many["blurs"]) == dub.MAX_BLURS and many["blur"] == many["blurs"][0]
    # an explicit empty list wins over a stale single box
    assert dub.normalize_layout({"blurs": [], "blur": {"x": 0.1, "y": 0.6}})["blurs"] == []


def test_the_canvas_is_normalized_and_sized_from_the_long_side():
    assert dub.normalize_canvas({"aspect": "9:16"}) == {"aspect": "9:16", "fit": "blur", "pos": 0.5}
    assert dub.normalize_canvas({"aspect": "2:1"}) is None and dub.normalize_canvas(None) is None
    assert dub.normalize_canvas({"aspect": "1:1", "fit": "crop", "pos": 3})["pos"] == 1.0
    lay = lambda a: {"canvas": {"aspect": a}}  # noqa: E731
    assert dub.canvas_size(1280, 720, lay("9:16")) == (720, 1280)
    assert dub.canvas_size(1280, 720, lay("1:1")) == (1280, 1280)
    assert dub.canvas_size(1280, 720, lay("4:3")) == (1280, 960)
    assert dub.canvas_size(1280, 720, lay("4:5")) == (1024, 1280)
    assert dub.canvas_size(1280, 720, lay("16:9")) == (1280, 720)  # already that shape
    assert dub.canvas_size(720, 1280, None) == (720, 1280)


def test_the_graph_fits_the_format_then_chains_every_blur_box():
    lay = {"canvas": {"aspect": "9:16", "fit": "blur"},
           "blurs": [{"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.06}, {"x": 0.1, "y": 0.7, "w": 0.8, "h": 0.06}]}
    g = dub.video_filter(dub.Path("s.ass"), 720, 1280, lay, source=(1280, 720))
    assert g.index("[cv_bg]") < g.index("[vb0_base]") < g.index("[vb1_base]") < g.index("ass=")
    assert "[vc]split[vb0_base]" in g and "[vb0]split[vb1_base]" in g and "[vb1]ass=" in g
    assert "crop=" in dub.canvas_filter({"fit": "crop", "pos": 0.2}, 1280, 720, 720, 1280)
    assert "pad=720:1280" in dub.canvas_filter({"fit": "black"}, 1280, 720, 720, 1280)
    assert dub.canvas_filter({"fit": "blur"}, 720, 1280, 720, 1280) == ""
    # without a format nothing changes: one box keeps the old labels
    one = dub.video_filter(dub.Path("s.ass"), 1280, 720, {"blur": {"x": 0.1, "y": 0.7}}, source=(1280, 720))
    assert one.startswith("[0:v]split[vb_base]") and "[vc]" not in one


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
@pytest.mark.parametrize("fit", ["blur", "black", "crop"])
def test_a_landscape_clip_comes_out_portrait(tmp_path, fit):
    ffmpeg = shutil.which("ffmpeg")
    src = tmp_path / "src.mp4"
    subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)], check=True)
    lay = {"canvas": {"aspect": "9:16", "fit": fit},
           "blurs": [{"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.06}, {"x": 0.1, "y": 0.7, "w": 0.8, "h": 0.06}]}
    w, h = dub.canvas_size(320, 180, lay)
    ass = dub.write_sub_ass([(0.0, 0.9, "Xin chào")], tmp_path / "s.ass", width=w, height=h, layout=lay)
    out = tmp_path / "out.mp4"
    graph = dub.video_filter(ass, w, h, lay, source=(320, 180))
    r = subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(src), "-filter_complex", graph, "-map", "[v]",
                        "-pix_fmt", "yuv420p", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    info = probe_clip(out)
    assert (info.width, info.height) == (180, 320)


def test_the_remotion_spec_carries_every_blur_box_and_the_format(tmp_path):
    from flowboard.services import dub_remotion

    lay = dub.normalize_layout({"canvas": {"aspect": "16:9"}, "blurs": [{"x": 0.1, "y": 0.1}, {"x": 0.1, "y": 0.7}]})
    spec = dub_remotion.build_spec(src=tmp_path / "a.mp4", out=tmp_path / "b.mp4", cues=[], layout=lay, style="rm_box",
                                   width=1024, height=576, duration_s=4)
    got = spec["props"]["layout"]
    assert len(got["blurs"]) == 2 and got["canvas"]["aspect"] == "16:9" and spec["props"]["width"] == 1024
