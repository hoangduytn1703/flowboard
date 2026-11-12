"""The "Gói Remotion" add-on (services/remotion_addon) and the ffmpeg subtitle lettering (dub.normalize_subfont)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from flowboard.services import dub, dub_remotion, remotion_addon


@pytest.fixture
def addon(tmp_path, monkeypatch):
    root = tmp_path / "addons" / "remotion"
    monkeypatch.setenv("FLOWBOARD_REMOTION_ADDON_DIR", str(root))
    kit = tmp_path / "kit"
    (kit / "remotion").mkdir(parents=True)
    (kit / "src" / "remotion").mkdir(parents=True)
    (kit / "remotion" / "render.mjs").write_text("// render", encoding="utf-8")
    (kit / "src" / "remotion" / "index.ts").write_text("export {};", encoding="utf-8")
    monkeypatch.setattr(remotion_addon, "kit_dir", lambda: kit)
    return root, kit


def _fake_installed(root: Path) -> None:
    exe = remotion_addon.node_exe(root)
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("", encoding="utf-8")
    pkg = remotion_addon.app_dir(root) / "node_modules" / "@remotion" / "renderer"
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text("{}", encoding="utf-8")
    (root / "addon.json").write_text(json.dumps({"version": 1, "node": "22.12.0"}), encoding="utf-8")


def test_dub_remotion_uses_the_addon_when_the_repo_has_no_frontend(addon, monkeypatch):
    root, _kit = addon
    monkeypatch.setattr(dub_remotion, "FRONTEND", root / "no-frontend")
    ok, why = dub_remotion.available()
    assert not ok and "gói Remotion" in why
    st = dub.status()
    assert st["remotion"] is False and st["remotion_addon"]["installed"] is False
    _fake_installed(root)
    assert dub_remotion.available() == (True, "")
    node, project = dub_remotion.runtime()
    assert Path(node) == remotion_addon.node_exe(root) and project == remotion_addon.app_dir(root)


def test_sources_are_copied_refreshed_and_pruned(addon):
    root, kit = addon
    remotion_addon.sync_sources()
    app = remotion_addon.app_dir(root)
    assert (app / "remotion" / "render.mjs").read_text(encoding="utf-8") == "// render"
    (kit / "src" / "remotion" / "index.ts").write_text("export const v = 2;", encoding="utf-8")
    (app / "src" / "remotion" / "old.tsx").write_text("gone", encoding="utf-8")
    remotion_addon.sync_sources()
    assert "v = 2" in (app / "src" / "remotion" / "index.ts").read_text(encoding="utf-8")
    assert not (app / "src" / "remotion" / "old.tsx").exists()


def test_install_runs_the_steps_and_writes_addon_json_last(addon, monkeypatch):
    root, _kit = addon
    steps: list[str] = []

    def node(r):
        steps.append("node")
        _fake_installed(r)
        (r / "addon.json").unlink()  # only the end of the install writes it

    monkeypatch.setattr(remotion_addon, "_install_node", node)
    monkeypatch.setattr(remotion_addon, "_npm_install", lambda r: steps.append("npm"))
    monkeypatch.setattr(remotion_addon, "_prepare", lambda r: steps.append("prepare"))
    remotion_addon._install()
    assert steps == ["node", "npm", "prepare"]
    pkg = json.loads((remotion_addon.app_dir(root) / "package.json").read_text(encoding="utf-8"))
    assert pkg["dependencies"]["@remotion/renderer"] == remotion_addon.REMOTION_VERSION
    assert remotion_addon.ready() and remotion_addon.info()["remotion"] == remotion_addon.REMOTION_VERSION
    remotion_addon.remove()
    assert not root.exists() and not remotion_addon.ready()


def test_a_cancelled_install_says_so(addon, monkeypatch):
    def boom(_r):
        raise remotion_addon._Cancelled()

    monkeypatch.setattr(remotion_addon, "_install_node", boom)
    remotion_addon._set(running=True)
    remotion_addon._worker()
    st = remotion_addon.status()
    assert not st["running"] and "huỷ" in st["error"].lower() and not st["installed"]


def test_routes(client, addon):
    r = client.get("/api/dub/remotion-addon")
    assert r.status_code == 200 and r.json()["installed"] is False


def test_subfont_normalizes_and_drops_the_default():
    assert dub.normalize_subfont(None) is None
    assert dub.normalize_subfont({"bold": True, "border": 1}) is None
    sf = dub.normalize_subfont({"bold": False, "border": 9, "border_color": "#D81B60", "color": "nope"})
    assert sf == {"bold": False, "border": 2.5, "border_color": "#d81b60", "color": None}
    assert dub.normalize_layout({"subfont": sf})["subfont"] == sf
    assert dub.normalize_layout({})["subfont"] is None


def test_subfont_reaches_the_ass_style(tmp_path):
    cue = [(0.0, 2.0, "Xin chào")]
    out = tmp_path / "a.ass"
    dub.write_sub_ass(cue, out, width=720, height=1280, style="outline")
    base = next(l for l in out.read_text().splitlines() if l.startswith("Style: Sub")).split(",")
    dub.write_sub_ass(cue, out, width=720, height=1280, style="outline",
                      layout={"subfont": {"bold": False, "border": 0.5, "border_color": "#ff0000"}})
    thin = next(l for l in out.read_text().splitlines() if l.startswith("Style: Sub")).split(",")
    assert base[7] == "-1" and thin[7] == "0"            # Bold
    assert float(thin[16]) == pytest.approx(float(base[16]) / 2)  # Outline width
    assert thin[5] == "&H000000FF"                         # OutlineColour = red (&HAABBGGRR)
    dub.write_sub_ass(cue, out, width=720, height=1280, style="box_yellow",
                      layout={"subfont": {"border": 0, "border_color": "#0000ff", "color": "#ffffff"}})
    box = next(l for l in out.read_text().splitlines() if l.startswith("Style: Sub")).split(",")
    assert box[3] == "&H00FFFFFF" and box[5] == "&H00FF0000" and box[15] == "3" and int(box[16]) >= 2


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_a_thin_outline_burns(tmp_path):
    src = tmp_path / "in.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x240:d=1",
                    "-pix_fmt", "yuv420p", str(src)], check=True)
    ass = tmp_path / "s.ass"
    dub.write_sub_ass([(0, 1, "Chào")], ass, width=320, height=240, style="outline",
                      layout={"subfont": {"border": 0.4, "border_color": "#ff0000"}})
    png = tmp_path / "f.png"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", "0.5", "-i", str(src), "-vf", f"ass='{dub._filter_path(ass)}'", "-frames:v", "1",
                    str(png)], check=True)
    assert png.stat().st_size > 0
