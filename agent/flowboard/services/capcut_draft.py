"""Read and write CapCut desktop projects (Windows) — the file side of
"✂️ Edit auto CapCut" (``services/capcut_auto``, ``routes/capcut``).

Adapted from the JunOps skill (``.claude/skills/junops-edit-capcut/scripts/
junops_capcut.py``; its LICENSE allows use, copy and changes): every text
style, sound effect and even the JSON shape of a video / audio piece comes
from the user's OWN CapCut — learned from their projects (:func:`learn`) —
so a project written here opens in their CapCut version as if they had made it.

How CapCut keeps a project: a folder in the drafts root
(``%LOCALAPPDATA%\\CapCut\\User Data\\Projects\\com.lveditor.draft``) with
``draft_content.json`` (the timeline: tracks → segments → materials, keyframes;
newer CapCut keeps one per timeline in ``Timelines/<id>/`` and mirrors the open
one at the root), ``draft_meta_info.json`` (name, id, media library) and a few
small config files. The home screen lists what ``root_meta_info.json`` lists.

Rules: never write while CapCut runs (it saves over everything on exit); a
new project copies the skeleton of one of the user's projects with every id
renewed; times are microseconds; positions are -1…1 of half the canvas, y up.
"""
from __future__ import annotations

import copy
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Iterator, Optional

S = 1_000_000  # CapCut counts microseconds

#: segment refs that are per-segment state, cloned for every new segment
REF_KEEP = {"speeds", "placeholder_infos", "canvases", "sound_channel_mappings", "material_colors",
            "vocal_separations", "realtime_denoises"}
#: folders CapCut creates empty in every project
EMPTY_DIRS = ("Resources", "adjust_mask", "matting", "qr_upload", "smart_crop", "subdraft")
#: small config files copied as they are from the skeleton project
COPY_FILES = ("draft_agency_config.json", "draft_biz_config.json", "performance_opt_info.json",
              "attachment_pc_common.json", "draft.extra")
TIMELINE_NAME = "Timeline 01"


class CapcutError(RuntimeError):
    pass


# ── where CapCut is ────────────────────────────────────────────────────────

def drafts_root() -> Optional[Path]:
    """The drafts folder: ``FLOWBOARD_CAPCUT_DRAFTS`` / ``CAPCUT_DRAFTS``, else CapCut's default."""
    cands = [os.environ.get("FLOWBOARD_CAPCUT_DRAFTS"), os.environ.get("CAPCUT_DRAFTS")]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        cands.append(str(Path(local) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"))
    for c in cands:
        if c and Path(c).is_dir():
            return Path(c)
    return None


def capcut_running() -> bool:
    if sys.platform != "win32":
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CapCut.exe"], capture_output=True, text=True,
                             timeout=10).stdout
    except Exception:  # noqa: BLE001 — unknown means "not seen running"
        return False
    return "capcut.exe" in out.lower()


def new_id() -> str:
    """An id in CapCut's own spelling (``D1028591-2D0F-45e3-86B6-946968C53EB8``)."""
    u = str(uuid.uuid4()).split("-")
    return "-".join([u[0].upper(), u[1].upper(), u[2], u[3].upper(), u[4].upper()])


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump_json(path: Path, data: Any) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def timelines(pdir: Path) -> list[dict[str, Any]]:
    """The project's timelines ``[{no, id, name, path}]`` (a single root one for older CapCut)."""
    lay = pdir / "timeline_layout.json"
    if not lay.is_file():
        return [{"no": "01", "id": "", "name": pdir.name, "path": pdir / "draft_content.json"}]
    out = []
    for dock in load_json(lay).get("dockItems", []):
        for i, (tid, name) in enumerate(zip(dock.get("timelineIds", []), dock.get("timelineNames", []))):
            out.append({"no": f"{i + 1:02d}", "id": tid, "name": name, "path": pdir / "Timelines" / tid / "draft_content.json"})
    return out


def project_dirs(root: Path) -> list[Path]:
    """Project folders, most recently changed first."""
    dirs = [p for p in root.iterdir() if p.is_dir() and (p / "draft_content.json").is_file()]
    return sorted(dirs, key=lambda p: -p.stat().st_mtime)


def list_projects(root: Path) -> list[dict[str, Any]]:
    out = []
    for p in project_dirs(root):
        out.append({"name": p.name, "folder": str(p),
                    "modified": _dt.datetime.fromtimestamp(p.stat().st_mtime, tz=_dt.timezone.utc).isoformat()})
    return out


def _walk(root: Path, max_projects: int) -> Iterator[tuple[str, Path]]:
    for p in project_dirs(root)[:max_projects]:
        try:
            paths = [t["path"] for t in timelines(p)]
        except Exception:  # noqa: BLE001 — a damaged layout: the root timeline still counts
            paths = [p / "draft_content.json"]
        for path in paths:
            if Path(path).is_file():
                yield p.name, Path(path)


def index(d: dict) -> dict[str, tuple[str, dict]]:
    return {m["id"]: (k, m) for k, v in d.get("materials", {}).items() if isinstance(v, list)
            for m in v if isinstance(m, dict) and "id" in m}


def text_of(m: dict) -> str:
    try:
        return json.loads(m["content"])["text"]
    except Exception:  # noqa: BLE001
        return ""


def seg_range(s: dict) -> tuple[float, float]:
    t = s["target_timerange"]
    return t["start"] / S, (t["start"] + t["duration"]) / S


# ── learning the user's styles ─────────────────────────────────────────────

def _pack(track_type: str, s: dict, kind: str, m: dict, refs: list[tuple[str, dict]]) -> dict:
    seg = {k: v for k, v in s.items() if not k.startswith("_")}
    return {"track_type": track_type, "segment": copy.deepcopy(seg), "material": [kind, copy.deepcopy(m)],
            "refs": [[k, copy.deepcopy(r)] for k, r in refs]}


def _text_key(m: dict) -> tuple:
    fonts = m.get("fonts") or []
    font = (fonts[0].get("title") if fonts else "") or Path(m.get("font_path") or "").stem or "mặc định"
    boxed = bool(m.get("background_color")) and float(m.get("background_alpha") or 0) > 0
    return (font, round(float(m.get("font_size") or 0), 1), (m.get("text_color") or "").lower(),
            round(float(m.get("background_alpha") or 0), 1) if boxed else 0.0)


#: a sample text that names its use → that style gets the job (the guide asks for these words)
_ROLE_WORDS = {
    "subtitle": ("phụ đề", "phu de", "subtitle", "caption", "sub"),
    "emphasis": ("nhấn mạnh", "nhan manh", "nhấn", "emphasis", "highlight"),
    "title": ("tiêu đề", "tieu de", "title", "chữ to", "tựa"),
}


def _role_of(examples: list[str]) -> Optional[str]:
    for ex in examples:
        low = ex.lower().strip()
        for role in ("emphasis", "title", "subtitle"):  # "phụ đề nhấn mạnh" → emphasis
            if any(w in low for w in _ROLE_WORDS[role]):
                return role
    return None


def learn(root: Path, max_projects: int = 12) -> dict[str, Any]:
    """Scan the newest projects: text styles (``t1…``), downloaded sound
    effects (``s1…``), one video and one audio piece as shape templates, and
    which project lends its skeleton to new ones."""
    texts: dict[tuple, dict] = {}
    sounds: dict[str, dict] = {}
    video_tpl = audio_tpl = None
    base = None
    scanned = 0
    for name, path in _walk(root, max_projects):
        try:
            d = load_json(path)
        except Exception:  # noqa: BLE001 — a half-written project is skipped
            continue
        scanned += 1
        idx = index(d)
        for tr in d.get("tracks", []):
            for s in tr.get("segments", []):
                kind, m = idx.get(s.get("material_id"), ("?", {}))
                refs = [idx[r] for r in s.get("extra_material_refs", []) if r in idx]
                if tr.get("type") == "text" and kind == "texts":
                    e = texts.setdefault(_text_key(m), {"uses": 0, "examples": [], "project": name, "tpl": None})
                    e["uses"] += 1
                    t = text_of(m)
                    if t and len(e["examples"]) < 3 and t[:40] not in e["examples"]:
                        e["examples"].append(t[:40])
                    if e["tpl"] is None:
                        e["tpl"] = _pack("text", s, kind, m, refs)
                elif tr.get("type") == "audio" and kind == "audios":
                    if audio_tpl is None:
                        audio_tpl = _pack("audio", s, kind, m, refs)
                    if m.get("type") == "sound" and m.get("path") and os.path.exists(m["path"]):
                        nm = m.get("name") or Path(m["path"]).name
                        e = sounds.setdefault(nm, {"uses": 0, "project": name, "tpl": None})
                        e["uses"] += 1
                        if e["tpl"] is None:
                            e["tpl"] = _pack("audio", s, kind, m, refs)
                elif tr.get("type") == "video" and kind == "videos" and video_tpl is None and m.get("type") == "video":
                    video_tpl = _pack("video", s, kind, m, refs)
                    base = name
    kho: dict[str, Any] = {"learned_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                           "root": str(root), "scanned": scanned, "texts": {}, "sounds": {}, "aliases": {},
                           "video_tpl": video_tpl, "audio_tpl": audio_tpl, "base": base}
    for i, (key, e) in enumerate(sorted(texts.items(), key=lambda kv: -kv[1]["uses"]), 1):
        font, size, color, boxed = key
        e["label"] = f"{font} · cỡ {size:g} · {color or 'màu ?'}" + (" · có nền" if boxed else "")
        e["font"], e["size"], e["color"] = font, size, color
        e["role"] = _role_of(e["examples"])
        kho["texts"][f"t{i}"] = e
    for i, (nm, e) in enumerate(sorted(sounds.items(), key=lambda kv: -kv[1]["uses"]), 1):
        e["label"] = nm
        e["duration"] = round((e["tpl"]["material"][1].get("duration") or 0) / S, 2)
        kho["sounds"][f"s{i}"] = e
    kho["aliases"] = default_aliases(kho["texts"])
    return kho


def default_aliases(texts: dict[str, dict]) -> dict[str, str]:
    """subtitle / emphasis / title: a style whose sample names the job wins
    (``Phụ đề``, ``Nhấn mạnh``, ``Tiêu đề``), else the most used one for
    subtitles, a bigger one for emphasis, the biggest for titles."""
    ids = list(texts)
    if not ids:
        return {}
    out: dict[str, str] = {}
    for i in ids:
        role = texts[i].get("role")
        if role and role not in out:
            out[role] = i
    out.setdefault("subtitle", ids[0])
    size_sub = float(texts[out["subtitle"]].get("size") or 0)
    others = [i for i in ids if i != out["subtitle"]]
    if "emphasis" not in out:
        bigger = [i for i in others if float(texts[i].get("size") or 0) > size_sub and i != out.get("title")]
        out["emphasis"] = (bigger or [i for i in others if i != out.get("title")] or [out["subtitle"]])[0]
    if "title" not in out:
        out["title"] = max(ids, key=lambda i: float(texts[i].get("size") or 0))
    return out


# ── building a timeline ────────────────────────────────────────────────────

def _fresh_refs(d: dict, refs: list[list], keep: Optional[set[str]] = None, drop: tuple[str, ...] = ()) -> list[str]:
    ids = []
    for kind, ref in copy.deepcopy(refs):
        if kind in drop or (keep is not None and kind not in keep):
            continue
        ref["id"] = new_id()
        d["materials"].setdefault(kind, []).append(ref)
        ids.append(ref["id"])
    return ids


class DraftBuilder:
    """A new timeline on the skeleton of one of the user's own drafts:
    their tracks and materials emptied, the canvas set to the video's size."""

    def __init__(self, kho: dict, base_content: dict, width: int, height: int):
        if not kho.get("video_tpl"):
            raise CapcutError("Chưa có mẫu video từ CapCut của bạn — mở CapCut, kéo một video bất kỳ vào một dự án, "
                              "đóng CapCut rồi bấm \"Học từ CapCut\".")
        d = copy.deepcopy(base_content)
        d["tracks"] = []
        for k, v in list(d.get("materials", {}).items()):
            if isinstance(v, list):
                d["materials"][k] = []
        if isinstance(d.get("keyframes"), dict):
            for k, v in list(d["keyframes"].items()):
                if isinstance(v, list):
                    d["keyframes"][k] = []
        d["canvas_config"] = {**(d.get("canvas_config") or {}), "ratio": "original", "width": int(width), "height": int(height)}
        d["duration"] = 0
        d["id"] = new_id()
        for k, empty in (("relationships", []), ("keyframe_graph_list", []), ("time_marks", None), ("cover", None),
                         ("retouch_cover", None), ("static_cover_image_path", ""), ("name", ""), ("path", "")):
            if k in d:
                d[k] = empty
        self.d = d
        self.kho = kho
        self.width, self.height = int(width), int(height)
        self._materials: dict[str, str] = {}  # file path → material id (one material, many segments)
        self._tracks: dict[str, int] = {}  # named lanes: "video", "voice", "music"…
        self._overflow: dict[str, list[int]] = {}  # a lane's tracks, its own first
        self._sfx_turn: list[str] = []
        self.media: list[dict[str, Any]] = []  # for draft_meta_info's media library
        self.counts = {"video": 0, "audio": 0, "text": 0, "sfx": 0, "zoom": 0}

    # tracks
    def _new_track(self, ttype: str) -> int:
        self.d["tracks"].append({"id": new_id(), "type": ttype, "flag": 0, "attribute": 0, "name": "",
                                 "is_default_name": True, "segments": []})
        return len(self.d["tracks"]) - 1

    def _lane(self, name: str, ttype: str) -> int:
        if name not in self._tracks:
            self._tracks[name] = self._new_track(ttype)
        return self._tracks[name]

    def _is_free(self, ti: int, a: float, b: float) -> bool:
        return all(seg_range(s)[1] <= a + 1e-6 or seg_range(s)[0] >= b - 1e-6 for s in self.d["tracks"][ti]["segments"])

    def _lane_track(self, lane: str, ttype: str, a: float, b: float) -> int:
        """The lane's own track; where it is taken, an overflow track of the same lane —
        never a track of another lane (a subtitle never lands among the key words)."""
        for ti in self._overflow.setdefault(lane, [self._lane(lane, ttype)]):
            if self._is_free(ti, a, b):
                return ti
        ti = self._new_track(ttype)
        self._overflow[lane].append(ti)
        return ti

    def _put(self, ti: int, seg: dict) -> None:
        seg["track_render_index"] = ti
        segs = self.d["tracks"][ti]["segments"]
        segs.append(seg)
        segs.sort(key=lambda s: s["target_timerange"]["start"])
        end = seg["target_timerange"]["start"] + seg["target_timerange"]["duration"]
        self.d["duration"] = max(int(self.d["duration"]), int(end))

    # pieces
    def add_video(self, path: Path, *, duration_s: float, width: int, height: int, has_audio: bool,
                  start: float, src_start: float = 0.0, dur: Optional[float] = None, volume: float = 1.0) -> None:
        """A piece of ``path`` (``src_start`` … ``+dur``) at ``start`` on the main video track."""
        tpl = self.kho["video_tpl"]
        key = str(Path(path).resolve())
        mid = self._materials.get(key)
        if mid is None:
            kind, mat = copy.deepcopy(tpl["material"])
            mid = mat["id"] = new_id()
            local = str(uuid.uuid4())
            mat.update(unique_id=uuid.uuid4().hex, path=Path(path).resolve().as_posix(), media_path="", local_id="",
                       duration=int(round(duration_s * S)), width=int(width), height=int(height),
                       material_name=Path(path).name, has_audio=bool(has_audio), category_name="local",
                       category_id="", material_id="", material_url="", local_material_id=local,
                       origin_material_id="", request_id="", reverse_path="", intensifies_path="",
                       reverse_intensifies_path="", intensifies_audio_path="", cartoon_path="",
                       has_sound_separated=False, freeze=None, smart_motion=None, multi_camera_info=None)
            if isinstance(mat.get("crop"), dict):
                mat["crop"] = {"upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0, "upper_right_y": 0.0,
                               "lower_left_x": 0.0, "lower_left_y": 1.0, "lower_right_x": 1.0, "lower_right_y": 1.0}
            self.d["materials"].setdefault(kind, []).append(mat)
            self._materials[key] = mid
            self.media.append({"id": local, "path": Path(path).resolve().as_posix(), "duration": int(round(duration_s * S)),
                               "width": int(width), "height": int(height), "kind": "video", "name": Path(path).name})
        dur = duration_s - src_start if dur is None else dur
        seg = copy.deepcopy(tpl["segment"])
        seg.update(id=new_id(), material_id=mid, extra_material_refs=_fresh_refs(self.d, tpl["refs"], keep=REF_KEEP),
                   common_keyframes=[], keyframe_refs=[], speed=1.0, volume=volume, last_nonzero_volume=volume or 1.0,
                   source_timerange={"start": int(round(src_start * S)), "duration": int(round(dur * S))},
                   target_timerange={"start": int(round(start * S)), "duration": int(round(dur * S))},
                   visible=True, render_index=0)
        if isinstance(seg.get("clip"), dict):
            seg["clip"] = {**seg["clip"], "scale": {"x": 1.0, "y": 1.0}, "rotation": 0.0, "transform": {"x": 0.0, "y": 0.0},
                           "alpha": 1.0}
        self._put(self._lane("video", "video"), seg)
        self.counts["video"] += 1

    def add_audio(self, path: Path, *, duration_s: float, start: float = 0.0, volume: float = 1.0, lane: str = "voice") -> None:
        """A whole local audio file (the dubbed voice, the music) on its own lane."""
        tpl = self.kho.get("audio_tpl") or self._sound_tpl()
        kind, mat = copy.deepcopy(tpl["material"])
        mat["id"] = new_id()
        mat.update(type="extract_music", name=Path(path).name, path=str(Path(path).resolve()),
                   duration=int(round(duration_s * S)), music_id="", effect_id="", resource_id="", third_resource_id="",
                   category_name="local", category_id="", request_id="", query="", search_id="", app_id=0,
                   wave_points=[], source_platform=0, local_material_id="", team_id="", text_id="", video_id="")
        self.d["materials"].setdefault(kind, []).append(mat)
        seg = copy.deepcopy(tpl["segment"])
        seg.update(id=new_id(), material_id=mat["id"],
                   extra_material_refs=_fresh_refs(self.d, tpl["refs"], keep=REF_KEEP),
                   common_keyframes=[], keyframe_refs=[], speed=1.0, volume=volume, last_nonzero_volume=volume or 1.0,
                   source_timerange={"start": 0, "duration": int(round(duration_s * S))},
                   target_timerange={"start": int(round(start * S)), "duration": int(round(duration_s * S))})
        self._put(self._lane(lane, "audio"), seg)
        self.counts["audio"] += 1

    def _sound_tpl(self) -> dict:
        snd = next(iter(self.kho.get("sounds", {}).values()), None)
        if not snd:
            raise CapcutError("Chưa có mẫu âm thanh từ CapCut của bạn — thêm vài hiệu ứng âm thanh vào một dự án, "
                              "đóng CapCut rồi bấm \"Học từ CapCut\".")
        return snd["tpl"]

    def text_style(self, style: str) -> str:
        sid = self.kho.get("aliases", {}).get(style, style)
        if sid not in self.kho.get("texts", {}):
            raise CapcutError(f"Không có kiểu chữ {style!r} — bấm \"Học từ CapCut\" lại.")
        return sid

    def add_text(self, style: str, start: float, dur: float, text: str, *, x: Optional[float] = None,
                 y: Optional[float] = None, lane: Optional[str] = None) -> None:
        tpl = self.kho["texts"][self.text_style(style)]["tpl"]
        seg = copy.deepcopy(tpl["segment"])
        kind, mat = copy.deepcopy(tpl["material"])
        mat["id"] = new_id()
        content = json.loads(mat["content"])
        content["text"] = text
        st = content["styles"][0]
        st["range"] = [0, len(text.encode("utf-16-le")) // 2]
        content["styles"] = [st]
        mat["content"] = json.dumps(content, ensure_ascii=False)
        for k in ("words", "current_words"):
            if isinstance(mat.get(k), dict):
                mat[k] = {"start_time": [], "end_time": [], "text": []}
        mat["recognize_text"] = ""
        self.d["materials"].setdefault(kind, []).append(mat)
        seg.update(id=new_id(), material_id=mat["id"], extra_material_refs=_fresh_refs(self.d, tpl["refs"]),
                   common_keyframes=[], keyframe_refs=[],
                   target_timerange={"start": int(round(start * S)), "duration": int(round(dur * S))})
        if seg.get("source_timerange"):
            seg["source_timerange"]["duration"] = int(round(dur * S))
        clip = seg.get("clip")
        if isinstance(clip, dict):
            if x is not None:
                clip["transform"]["x"] = max(-1.0, min(1.0, x))
            if y is not None:
                clip["transform"]["y"] = max(-1.0, min(1.0, y))
        self._put(self._lane_track(lane or "text", "text", start, start + dur), seg)
        self.counts["text"] += 1

    def add_sfx(self, at: float, *, sound: str = "auto", volume: float = 0.3, max_dur: float = 2.5) -> Optional[str]:
        """One sound effect at ``at``; ``auto`` takes the user's sounds in turn, never the same one twice in a row."""
        sounds = self.kho.get("sounds") or {}
        if not sounds:
            return None
        if sound == "auto":
            # every sound of the user's, in turn (a long one is cut to max_dur), never the same one twice running
            ids = list(sounds)
            recent = self._sfx_turn[-max(1, min(3, len(ids) - 1)):] if len(ids) > 1 else []
            fresh = [i for i in ids if i not in recent] or ids
            sound = min(fresh, key=lambda i: (self._sfx_turn.count(i), ids.index(i)))
            self._sfx_turn.append(sound)
        tpl = sounds[sound]["tpl"]
        full = (tpl["material"][1].get("duration") or S) / S
        dur = max(0.2, min(full, max_dur))
        kind, mat = copy.deepcopy(tpl["material"])
        mat["id"] = new_id()
        self.d["materials"].setdefault(kind, []).append(mat)
        seg = copy.deepcopy(tpl["segment"])
        seg.update(id=new_id(), material_id=mat["id"], extra_material_refs=_fresh_refs(self.d, tpl["refs"], drop=("audio_fades",)),
                   common_keyframes=[], keyframe_refs=[], volume=volume, last_nonzero_volume=volume,
                   source_timerange={"start": 0, "duration": int(round(dur * S))},
                   target_timerange={"start": int(round(at * S)), "duration": int(round(dur * S))})
        self._put(self._lane_track("sfx", "audio", at, at + dur), seg)
        self.counts["sfx"] += 1
        return sound

    def add_zoom(self, at: float, *, level: float = 1.15, rise: float = 0.3, hold: float = 1.0, fall: float = 0.4) -> bool:
        """Push in on the main video at ``at`` and back out (scale keyframes on the piece playing then)."""
        vt = self._tracks.get("video")
        if vt is None:
            return False
        points = [(0.0, 1.0), (rise, level), (rise + hold, level), (rise + hold + fall, 1.0)]
        for s in self.d["tracks"][vt]["segments"]:
            x0, x1 = seg_range(s)
            if not (x0 <= at < x1):
                continue
            src0 = (s.get("source_timerange") or {}).get("start", 0)
            base = src0 + int((at - x0) * S)
            kfs = [{"id": new_id(), "curveType": "FreeCurveInOut", "time_offset": base + int(t * S),
                    "left_control": {"x": 0.0, "y": 0.0}, "right_control": {"x": 0.0, "y": 0.0},
                    "values": [float(v)], "string_value": "", "graphID": ""} for t, v in points]
            ck = s.get("common_keyframes") or []
            s["common_keyframes"] = ck
            # scale X alone, as the JunOps skill writes it: with uniform scale on, CapCut scales both ways
            lane = next((k for k in ck if k["property_type"] == "KFTypeScaleX"), None)
            if lane is None:
                lane = {"id": new_id(), "material_id": "", "property_type": "KFTypeScaleX", "keyframe_list": []}
                ck.append(lane)
            lo, hi = kfs[0]["time_offset"], kfs[-1]["time_offset"]
            if any(lo - 50_000 <= k["time_offset"] <= hi + 50_000 for k in lane["keyframe_list"]):
                return False
            lane["keyframe_list"] = sorted(lane["keyframe_list"] + kfs, key=lambda k: k["time_offset"])
            self.counts["zoom"] += 1
            return True
        return False


# ── reading subtitles back ─────────────────────────────────────────────────

def read_subtitles(pdir: Path) -> list[tuple[float, float, str]]:
    """The subtitles of a project as they are now (after any hand edits): the text track
    with the most pieces — key words / titles are few — in time order."""
    tls = timelines(pdir)
    path = Path(tls[0]["path"]) if tls and Path(tls[0]["path"]).is_file() else pdir / "draft_content.json"
    d = load_json(path)
    idx = index(d)
    tracks = [t for t in d.get("tracks", []) if t.get("type") == "text" and t.get("segments")]
    if not tracks:
        return []
    main = max(tracks, key=lambda t: len(t["segments"]))
    out = []
    for s in main["segments"]:
        kind, m = idx.get(s.get("material_id"), ("?", {}))
        text = text_of(m).strip() if kind == "texts" else ""
        if text:
            a, b = seg_range(s)
            out.append((a, b, text))
    return sorted(out)


def _srt_time(t: float) -> str:
    ms = max(0, int(round(t * 1000)))
    return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def to_srt(cues: list[tuple[float, float, str]]) -> str:
    """SubRip, for CapCut's Captions → Import (real captions: move one, they all move)."""
    blocks = [f"{i}\n{_srt_time(a)} --> {_srt_time(b)}\n{text.replace(chr(10), ' ').strip()}\n"
              for i, (a, b, text) in enumerate(cues, 1) if text.strip()]
    return "\n".join(blocks)


# ── writing a project ──────────────────────────────────────────────────────

_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def safe_name(name: str) -> str:
    n = _BAD_NAME.sub(" ", name or "").strip().strip(".")
    return re.sub(r"\s+", " ", n)[:60] or "Flowboard"


def unique_name(root: Path, name: str) -> str:
    base = safe_name(name)
    n, i = base, 2
    while (root / n).exists():
        n = f"{base} ({i})"
        i += 1
    return n


def base_project(root: Path, kho: dict) -> Path:
    """The project lending its skeleton: the one the video template came from,
    else the newest project that still exists."""
    if kho.get("base") and (root / kho["base"] / "draft_content.json").is_file():
        return root / kho["base"]
    dirs = project_dirs(root)
    if not dirs:
        raise CapcutError("CapCut chưa có dự án nào để làm khung — mở CapCut, tạo một dự án có video, đóng CapCut rồi thử lại.")
    return dirs[0]


def base_content(pdir: Path) -> dict:
    tls = timelines(pdir)
    path = tls[0]["path"] if tls and Path(tls[0]["path"]).is_file() else pdir / "draft_content.json"
    return load_json(path)


def create_project(root: Path, name: str, builder: DraftBuilder, base: Path,
                   cover: Optional[Path] = None) -> dict[str, Any]:
    """Write ``builder``'s timeline as a new project next to the user's, and list it on CapCut's home screen."""
    if capcut_running():
        raise CapcutError("CapCut đang mở — đóng hẳn CapCut (cả biểu tượng ở khay góc phải), chờ vài giây rồi thử lại. "
                          "CapCut đang mở sẽ ghi đè lên dự án mới khi tắt.")
    name = unique_name(root, name)
    pdir = root / name
    pdir.mkdir(parents=True)
    try:
        return _write_project(root, pdir, builder, base, cover)
    except BaseException:
        shutil.rmtree(pdir, ignore_errors=True)
        raise


def _write_project(root: Path, pdir: Path, b: DraftBuilder, base: Path, cover: Optional[Path]) -> dict[str, Any]:
    now = time.time()
    now_us = int(now * S)
    draft_id = new_id()
    content = b.d
    tid = content["id"]
    for f in COPY_FILES:
        if (base / f).is_file():
            shutil.copy2(base / f, pdir / f)
    for d in EMPTY_DIRS:
        (pdir / d).mkdir(exist_ok=True)
    _attachments(pdir, base)
    dump_json(pdir / "draft_content.json", content)
    if (base / "timeline_layout.json").is_file():  # CapCut with several timelines per project
        dump_json(pdir / "timeline_layout.json", {"dockItems": [{"dockIndex": 0, "ratio": 1, "timelineIds": [tid],
                                                                 "timelineNames": [TIMELINE_NAME]}], "layoutOrientation": 1})
        tdir = pdir / "Timelines" / tid
        tdir.mkdir(parents=True)
        try:
            proj = load_json(base / "Timelines" / "project.json")
        except Exception:  # noqa: BLE001 — rebuilt from what CapCut writes
            proj = {"config": {"color_space": -1, "hdr_vivid": False, "mixed_track_mode_on": False,
                               "render_index_track_mode_on": False, "use_float_render": False}, "version": 0}
        proj.update(id=new_id(), main_timeline_id=tid, create_time=now_us, update_time=now_us,
                    timelines=[{"create_time": now_us, "id": tid, "is_marked_delete": False, "name": TIMELINE_NAME,
                                "update_time": now_us}])
        dump_json(pdir / "Timelines" / "project.json", proj)
        btl = timelines(base)
        bdir = Path(btl[0]["path"]).parent if btl and btl[0]["id"] else base
        for f in ("attachment_pc_common.json", "draft.extra"):
            if (bdir / f).is_file():
                shutil.copy2(bdir / f, tdir / f)
        _attachments(tdir, bdir)
        dump_json(tdir / "draft_content.json", content)
        if cover is not None and cover.is_file():
            shutil.copy2(cover, tdir / "draft_cover.jpg")
    if cover is not None and cover.is_file():
        shutil.copy2(cover, pdir / "draft_cover.jpg")
    _meta(pdir, b, base, draft_id, now, now_us)
    (pdir / "draft_settings").write_text(
        f"[General]\ndraft_create_time={int(now)}\ndraft_last_edit_time={int(now)}\nreal_edit_seconds=0\nreal_edit_keys=0\n",
        encoding="utf-8")
    dump_json(pdir / "draft_virtual_store.json", {
        "draft_materials": [],
        "draft_virtual_store": [
            {"type": 0, "value": [{"creation_time": 0, "display_name": "", "filter_type": 0, "id": "", "import_time": 0,
                                   "import_time_us": 0, "material_color_tag": "", "sort_sub_type": 0, "sort_type": 0,
                                   "subdraft_filter_type": 0}]},
            {"type": 1, "value": [{"child_id": m["id"], "parent_id": ""} for m in b.media]},
            {"type": 2, "value": []}]})
    dump_json(pdir / "key_value.json", {})
    _register(root, pdir, draft_id, now_us, int(content["duration"]))
    return {"name": pdir.name, "folder": str(pdir), "draft_id": draft_id, "duration_s": round(content["duration"] / S, 2),
            "counts": dict(b.counts)}


def _attachments(dst: Path, src: Path) -> None:
    (dst / "common_attachment").mkdir(exist_ok=True)
    tl = src / "common_attachment" / "attachment_pc_timeline.json"
    if tl.is_file():
        shutil.copy2(tl, dst / "common_attachment" / tl.name)
    dump_json(dst / "common_attachment" / "attachment_id_mapping.json",
              {"id_mapping": {"mapping": [], "next_index": 1000, "version": "1.0.0"}})


def _meta(pdir: Path, b: DraftBuilder, base: Path, draft_id: str, now: float, now_us: int) -> None:
    try:
        meta = load_json(base / "draft_meta_info.json")
    except Exception:  # noqa: BLE001
        meta = {}
    lib = []
    for m in b.media:
        lib.append({"ai_group_type": "", "create_time": int(now), "duration": m["duration"], "enter_from": 0,
                    "extra_info": m["name"], "file_Path": m["path"], "height": m["height"], "id": m["id"],
                    "import_time": int(now), "import_time_ms": now_us, "item_source": 1, "material_color_tag": "",
                    "md5": "", "metetype": m["kind"], "roughcut_time_range": {"duration": m["duration"], "start": 0},
                    "sub_time_range": {"duration": -1, "start": -1}, "type": 0, "width": m["width"]})
    groups = meta.get("draft_materials") or [{"type": t, "value": []} for t in (0, 1, 2, 3, 6, 7, 8)]
    meta["draft_materials"] = [{"type": g.get("type"), "value": lib if g.get("type") == 0 else []} for g in groups]
    meta.update(draft_id=draft_id, draft_name=pdir.name, draft_fold_path=pdir.as_posix(), draft_root_path=str(pdir.parent),
                draft_cover="draft_cover.jpg", tm_draft_create=now_us, tm_draft_modified=now_us, tm_draft_removed=0,
                tm_duration=int(b.d["duration"]), draft_materials_copied_info=[], draft_segment_extra_info=[],
                draft_need_rename_folder=False, draft_timeline_materials_size_=0, cloud_draft_sync=False,
                cloud_draft_cover=False, draft_is_invisible=False)
    dump_json(pdir / "draft_meta_info.json", meta)


def _register(root: Path, pdir: Path, draft_id: str, now_us: int, duration: int) -> None:
    """Put the project on CapCut's home screen (``root_meta_info.json``), newest first."""
    path = root / "root_meta_info.json"
    try:
        reg = load_json(path)
    except Exception:  # noqa: BLE001 — CapCut rebuilds a missing registry from the folders
        reg = {"all_draft_store": [], "draft_ids": 0, "root_path": root.as_posix()}
    if path.is_file():
        shutil.copy2(path, root / "root_meta_info.json.flowboard.bak")
    store = reg.get("all_draft_store") or []
    entry = copy.deepcopy(store[0]) if store else {}
    folder = pdir.as_posix()
    entry.update(draft_cover=f"{folder}\\draft_cover.jpg", draft_fold_path=folder, draft_id=draft_id,
                 draft_json_file=f"{folder}\\draft_content.json", draft_name=pdir.name,
                 draft_root_path=str(root), draft_timeline_materials_size=0, tm_draft_create=now_us,
                 tm_draft_modified=now_us, tm_draft_removed=0, tm_duration=duration, cloud_draft_sync=False,
                 cloud_draft_cover=False, draft_is_invisible=False, draft_type="")
    reg["all_draft_store"] = [entry] + [e for e in store if e.get("draft_fold_path") != folder]
    if isinstance(reg.get("draft_ids"), int):
        reg["draft_ids"] = int(reg["draft_ids"]) + 1
    dump_json(path, reg)


def remove_project(root: Path, folder: str) -> bool:
    """Delete a project this tool made (folder + home-screen entry). CapCut must be closed."""
    if capcut_running():
        raise CapcutError("CapCut đang mở — đóng CapCut rồi xoá.")
    p = Path(folder)
    if p.parent.resolve() != root.resolve() or not (p / "draft_meta_info.json").is_file():
        return False
    shutil.rmtree(p, ignore_errors=True)
    path = root / "root_meta_info.json"
    try:
        reg = load_json(path)
        before = len(reg.get("all_draft_store") or [])
        reg["all_draft_store"] = [e for e in reg.get("all_draft_store") or [] if e.get("draft_fold_path") != p.as_posix()]
        if isinstance(reg.get("draft_ids"), int) and len(reg["all_draft_store"]) < before:
            reg["draft_ids"] = max(0, int(reg["draft_ids"]) - 1)
        dump_json(path, reg)
    except Exception:  # noqa: BLE001 — the folder is gone; CapCut drops a dangling entry itself
        pass
    return True
