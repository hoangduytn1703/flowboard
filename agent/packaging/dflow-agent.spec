# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec of the desktop app's agent: one folder "agent" with dflow-agent.exe + _internal/.
#
#   cd agent
#   .venv\Scripts\python.exe -m PyInstaller packaging\dflow-agent.spec --noconfirm \
#       --distpath ..\desktop\src-tauri\resources --workpath ..\build\pyinstaller
#
# The console build is deliberate: DFlow.exe starts it with CREATE_NO_WINDOW, and the console programs it runs
# (ffmpeg…) then share that hidden console instead of flashing their own (dflow_agent also hides each child).
#
# Release builds ship the agent's own code (the flowboard package) compiled to machine code by Nuitka, not as Python
# bytecode (which decompiles back to readable source in minutes — the licence checks would be one edit away):
#   python -m nuitka --module flowboard --include-package=flowboard --output-dir=../build/nuitka ...
#   set DFLOW_COMPILED=<path of build/nuitka/flowboard.cp311-win_amd64.pyd>   (CI does both, .github/workflows/desktop.yml)
# The analysis still reads the sources (to find every library to bundle); then every flowboard module is dropped from
# the archive and the compiled extension goes in instead. Without DFLOW_COMPILED the build ships bytecode (local tests).
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
COMPILED = os.environ.get("DFLOW_COMPILED", "").strip()
if COMPILED:
    if not os.path.isfile(COMPILED):
        raise SystemExit(f"DFLOW_COMPILED points to a missing file: {COMPILED}")
    before = len(a.pure)
    a.pure = [e for e in a.pure if not (e[0] == "flowboard" or e[0].startswith("flowboard."))]
    a.binaries += [(os.path.basename(COMPILED), COMPILED, "EXTENSION")]
    print(f"dflow-agent.spec: {before - len(a.pure)} flowboard modules replaced by {os.path.basename(COMPILED)}")
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
