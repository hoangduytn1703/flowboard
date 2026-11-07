# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec of the desktop app's agent: one folder "agent" with dflow-agent.exe + _internal/.
#
#   cd agent
#   .venv\Scripts\python.exe -m PyInstaller packaging\dflow-agent.spec --noconfirm \
#       --distpath ..\desktop\src-tauri\resources --workpath ..\build\pyinstaller
#
# The console build is deliberate: DFlow.exe starts it with CREATE_NO_WINDOW, and the console programs it runs
# (ffmpeg…) then share that hidden console instead of flashing their own (dflow_agent also hides each child).
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

SPEC_DIR = os.path.abspath(SPECPATH)
AGENT = os.path.dirname(SPEC_DIR)
PKG = os.path.join(AGENT, "flowboard")
REPO = os.path.dirname(AGENT)
ICON = os.path.join(REPO, "desktop", "src-tauri", "icons", "icon.ico")

datas = [
    (os.path.join(PKG, "templates"), "flowboard/templates"),
    (os.path.join(PKG, "assets"), "flowboard/assets"),
    (os.path.join(PKG, "prompt_seeds.json"), "flowboard"),
    # run as scripts by pyvideotrans' Python (dub.RUNNER_PATH, video_clean.RUNNER_PATH): real files next to their modules
    (os.path.join(PKG, "services", "dub_runner.py"), "flowboard/services"),
    (os.path.join(PKG, "services", "video_clean_runner.py"), "flowboard/services"),
]
binaries = []
hiddenimports = (
    collect_submodules("flowboard")
    + collect_submodules("uvicorn")
    + collect_submodules("websockets")
    + collect_submodules("sqlalchemy.dialects")
)
for name in ("psycopg", "psycopg_binary", "edge_tts", "certifi"):
    d, b, h = collect_all(name)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(SPEC_DIR, "dflow_agent.py")],
    pathex=[AGENT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest", "moto", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="dflow-agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=ICON if os.path.isfile(ICON) else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="agent",
)
