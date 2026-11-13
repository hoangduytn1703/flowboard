"""Runs inside pyvideotrans' virtualenv (torch / faster-whisper / sherpa-onnx
live there, not in flowboard's). Called by ``services/dub.py``:

  python dub_runner.py transcribe <audio.wav> <out.json> [language] [words]
      → {"language": "zh", "segments": [{"start", "end", "text"[, "words": [{"start", "end", "word"}]]}]}
      ("words" as the 4th argument adds each word's timing — Edit auto CapCut cuts subtitles on them)
  python dub_runner.py separate <audio.wav> <vocals.wav> <bgm.wav>
      → {"ok": true}
  python dub_runner.py check
      → {"ok": true, "cuda": bool, "device": "cuda"|"cpu"} after loading Whisper and hearing two seconds of noise
      (the "gói lồng tiếng" add-on runs it once installed)
  python dub_runner.py detect <video>
      → {"bands": [{"y0", "y1", "hits"}], "info": "…"} — where burnt-in subtitles sit (RapidOCR on ~24–48 frames;
      the editor's "Tự tìm chữ gốc" on machines with the add-on instead of VieDub)
  python dub_runner.py vieneu <voice> <lines.json>
      lines.json = [{"text": …, "out": "<file.wav>"}, …] → {"ok": true, "done": n}
      (VieNeu-TTS v3 Turbo, the ``vieneu`` package of VieDub: 25 Vietnamese
      voices, ONNX on the CPU, the model in the HuggingFace cache ~580 MB)

Progress goes to stderr as ``PROGRESS <0-100>`` lines; the result JSON is the
last stdout line. ``FLOWBOARD_ERASE_ROOT`` is pyvideotrans' folder (the
Whisper model and the spleeter ONNX files sit under its ``models/``).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

WHISPER_DIR = "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"


def _root() -> Path:
    return Path(os.environ.get("FLOWBOARD_ERASE_ROOT") or Path(__file__).resolve().parents[3] / "pyvideotrans")


def _progress(p: int) -> None:
    sys.stderr.write(f"PROGRESS {int(p)}\n")
    sys.stderr.flush()


#: the CUDA libraries ctranslate2 looks up by name (the add-on gets them as pip wheels: nvidia/*/bin)
_CUDA_DLLS = ("cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll")


def _nvidia_dlls() -> None:
    """Put the add-on's cuBLAS / cuDNN (``site-packages/nvidia/*/bin``) within reach of ctranslate2: on the DLL
    path, on PATH, and loaded once by full path so a later load by name finds them."""
    if sys.platform != "win32":
        return
    try:
        import nvidia  # namespace package of the nvidia-*-cu12 wheels
    except ImportError:
        return
    import ctypes

    for base in list(getattr(nvidia, "__path__", [])):
        for bin_dir in sorted(Path(base).glob("*/bin")):
            try:
                os.add_dll_directory(str(bin_dir))
            except (OSError, AttributeError):
                pass
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
            for name in _CUDA_DLLS:
                dll = bin_dir / name
                if dll.is_file():
                    try:
                        ctypes.CDLL(str(dll))
                    except OSError:
                        pass


def _cuda() -> bool:
    """Whisper on the card? VieDub's venv answers through torch (importing it also loads its CUDA DLLs); the
    add-on has no torch and asks ctranslate2 after loading the nvidia wheels."""
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001 — no torch: the add-on
        pass
    _nvidia_dlls()
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001
        return False


def _load_whisper(cpu: bool = False):
    """``(model, device)``: on the card in float16 when there is one, else int8 on the CPU."""
    from faster_whisper import WhisperModel

    local_dir = str(_root() / "models" / WHISPER_DIR)
    if not Path(local_dir, "model.bin").is_file():
        raise SystemExit(f"whisper model missing: {local_dir}")
    attempts = [("cuda", "float16"), ("cuda", "int8_float16")] if not cpu and _cuda() else []
    attempts += [("cpu", "int8"), ("cpu", "float32")]
    last = None
    # on the CPU faster-whisper takes 4 threads unless told: a machine without a card has all its cores to give
    # (physical ones — hyper-threads slow ctranslate2 down)
    threads = max(4, min(16, (os.cpu_count() or 8) // 2))
    for device, compute in attempts:
        try:
            extra = {"cpu_threads": threads} if device == "cpu" else {}
            return WhisperModel(local_dir, device=device, compute_type=compute, **extra), device
        except Exception as exc:  # noqa: BLE001 — try the next precision / device
            last = exc
    raise SystemExit(f"could not load whisper: {last}")


def _gpu_failed(exc: Exception) -> bool:
    """A CUDA library that loads but fails at the first real work (missing cuDNN piece, old driver)."""
    text = f"{type(exc).__name__} {exc}".lower()
    return any(k in text for k in ("cuda", "cublas", "cudnn", "gpu", "dll", "driver"))


def transcribe(audio: str, out: str, language: str | None, words: bool = False, hint: str | None = None) -> None:
    """``hint`` = names / words the video is about (its title + hashtags) → faster-whisper ``hotwords``, which is
    put in front of EVERY 30 s window (``initial_prompt`` only reaches the first one with
    condition_on_previous_text off) — Whisper hears 爱因斯坦 instead of 安音斯坦."""
    _progress(5)
    model, device = _load_whisper()
    _progress(15)

    def hear(m, dev):
        segments, info = m.transcribe(
            audio,
            language=language or None,
            beam_size=5 if dev == "cuda" else 2,  # the CPU is 5–10× slower: a narrower search is most of the gain left
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 350},
            condition_on_previous_text=False,
            word_timestamps=words,
            hotwords=hint or None,
        )
        total = max(float(getattr(info, "duration", 0.0) or 0.0), 0.1)
        rows = []
        for seg in segments:
            text = (seg.text or "").strip()
            if not text:
                continue
            row = {"start": round(float(seg.start), 3), "end": round(float(seg.end), 3), "text": text}
            if words:
                row["words"] = [{"start": round(float(w.start), 3), "end": round(float(w.end), 3), "word": (w.word or "").strip()}
                                for w in (getattr(seg, "words", None) or []) if (w.word or "").strip()]
            rows.append(row)
            _progress(15 + min(80, int(80 * float(seg.end) / total)))
        return rows, info, total

    try:
        rows, info, total = hear(model, device)
    except Exception as exc:  # noqa: BLE001 — the card failed mid-way: hear it again on the CPU
        if device != "cuda" or not _gpu_failed(exc):
            raise
        sys.stderr.write(f"whisper on the GPU failed ({exc}); retrying on the CPU\n")
        del model
        model, device = _load_whisper(cpu=True)
        rows, info, total = hear(model, device)
    lang = getattr(info, "language", None) or language or ""
    if lang in ("zh", "yue"):
        try:
            import zhconv

            for r in rows:
                r["text"] = zhconv.convert(r["text"], "zh-hans")
        except Exception:  # noqa: BLE001 — simplified/traditional unification is a nicety
            pass
    Path(out).write_text(json.dumps({"language": lang, "duration": total, "segments": rows}, ensure_ascii=False), encoding="utf-8")
    _progress(100)
    print(json.dumps({"ok": True, "language": lang, "count": len(rows)}))


def separate(audio: str, vocals_out: str, bgm_out: str) -> None:
    import numpy as np
    import sherpa_onnx
    import soundfile as sf

    root = _root() / "models" / "onnx"
    vocals_m, acc_m = root / "vocals.fp16.onnx", root / "accompaniment.fp16.onnx"
    if not (vocals_m.is_file() and acc_m.is_file()):
        raise SystemExit(f"spleeter models missing in {root}")
    _progress(5)
    config = sherpa_onnx.OfflineSourceSeparationConfig(
        model=sherpa_onnx.OfflineSourceSeparationModelConfig(
            spleeter=sherpa_onnx.OfflineSourceSeparationSpleeterModelConfig(vocals=str(vocals_m), accompaniment=str(acc_m)),
            num_threads=4, debug=False, provider="cpu",
        )
    )
    if not config.validate():
        raise SystemExit("spleeter config invalid")
    sp = sherpa_onnx.OfflineSourceSeparation(config)
    samples, rate = sf.read(audio, dtype="float32", always_2d=True)
    samples = np.ascontiguousarray(np.transpose(samples))
    _progress(20)
    output = sp.process(sample_rate=rate, samples=samples)
    # sherpa-onnx spleeter: stems[0] = vocals, stems[1] = accompaniment
    # (VieDub has them the other way round — its "background" kept the speech).
    vocals, non_vocals = output.stems[0].data, output.stems[1].data
    sf.write(vocals_out, np.transpose(vocals), samplerate=output.sample_rate)
    sf.write(bgm_out, np.transpose(non_vocals), samplerate=output.sample_rate)
    _progress(100)
    print(json.dumps({"ok": True}))


def vieneu(voice: str, lines_json: str) -> None:
    """Speak every line of ``lines_json`` with one loaded VieNeu model (loading
    it is the slow part: a few seconds; a line takes ~0.5 s per second of
    speech on the CPU). Writes 48 kHz mono WAV files."""
    lines = json.loads(Path(lines_json).read_text(encoding="utf-8"))
    if not lines:
        print(json.dumps({"ok": True, "done": 0}))
        return
    _progress(2)
    try:
        from vieneu import Vieneu
    except ImportError as exc:
        raise SystemExit(f"vieneu package missing in this venv: {exc}")
    # ONNX / CPU like VieDub: the GPU path wants a newer torch, and the GPU is Whisper's.
    tts = Vieneu(mode="v3turbo", backend="onnx")
    _progress(10)
    done = 0
    missing: list[int] = []
    for i, item in enumerate(lines):
        text = str(item.get("text") or "").strip()
        out = str(item["out"])
        if not text:
            continue
        wav = tts.infer(text, voice=voice)
        if getattr(wav, "size", 0) == 0:
            # a line it cannot read (Chinese left untranslated, only symbols…): the others still get their voice,
            # the caller decides about this one (14/11: one such line used to end a whole 82-line dub)
            missing.append(i + 1)
            continue
        tts.save(wav, out)
        done += 1
        _progress(10 + int(88 * (i + 1) / len(lines)))
    _progress(100)
    print(json.dumps({"ok": True, "done": done, "missing": missing}))


def check() -> None:
    """After installing the add-on: load Whisper like a job would and make it hear two seconds of noise, so a
    broken CUDA library shows now (and the CPU fallback is proven) rather than in the middle of a video."""
    import numpy as np

    out: dict = {"ok": False, "cuda": False, "device": ""}
    noise = (np.random.default_rng(0).standard_normal(32000) * 0.01).astype("float32")
    try:
        model, device = _load_whisper()
        out["cuda"] = device == "cuda"
        try:
            segments, _info = model.transcribe(noise, language="en", beam_size=1, vad_filter=False)
            list(segments)
        except Exception as exc:  # noqa: BLE001
            if device != "cuda":
                raise
            out["cuda"] = False
            out["cuda_error"] = str(exc)[:300]
            del model
            model, device = _load_whisper(cpu=True)
            segments, _info = model.transcribe(noise, language="en", beam_size=1, vad_filter=False)
            list(segments)
        out.update(ok=True, device=device)
    except BaseException as exc:  # noqa: BLE001 — SystemExit from _load_whisper too
        out["error"] = str(exc)[:500]
    print(json.dumps(out, ensure_ascii=False))


def sub_like(box: tuple, w: int, h: int) -> bool:
    """A detected text line that could be a subtitle: wide, not tiny, not huge, roughly centred."""
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    if bh <= 0 or bw <= 0:
        return False
    cx = (x0 + x1) / 2
    return bw / bh >= 1.8 and 0.012 * h <= bh <= 0.12 * h and bw >= 0.12 * w and 0.15 * w <= cx <= 0.85 * w


def bands_from_lines(lines: list, h: int, min_frames: int) -> list[dict]:
    """``lines`` = (top, bottom, frame index) in pixels → the heights where text comes back in many frames,
    as ``{y0, y1, hits}`` fractions of the height, the most frequent first."""
    groups: list[dict] = []
    for top, bottom, i in sorted(lines):
        for g in groups:
            overlap = min(bottom, g["y1"]) - max(top, g["y0"])
            if overlap >= 0.5 * min(bottom - top, g["y1"] - g["y0"]):
                g["tops"].append(top)
                g["bottoms"].append(bottom)
                g["frames"].add(i)
                g["y0"], g["y1"] = min(g["y0"], top), max(g["y1"], bottom)
                break
        else:
            groups.append({"y0": top, "y1": bottom, "tops": [top], "bottoms": [bottom], "frames": {i}})
    out = []
    for g in groups:
        if len(g["frames"]) < min_frames:
            continue
        tops, bottoms = sorted(g["tops"]), sorted(g["bottoms"])
        y0 = tops[int(0.1 * (len(tops) - 1))] - 0.01 * h
        y1 = bottoms[min(len(bottoms) - 1, int(0.9 * (len(bottoms) - 1) + 0.999))] + 0.01 * h
        out.append({"y0": round(max(0.0, y0 / h), 4), "y1": round(min(1.0, y1 / h), 4), "hits": len(g["frames"])})
    out.sort(key=lambda b: -b["hits"])
    return out


def detect(src: str) -> None:
    import subprocess

    import cv2
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR

    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", src],
                           capture_output=True, text=True, timeout=60)
    try:
        dur = float((probe.stdout or "0").strip().splitlines()[0])
    except (ValueError, IndexError):
        dur = 0.0
    if dur <= 0:
        print(json.dumps({"bands": [], "info": "Không đọc được video."}, ensure_ascii=False))
        return
    n = int(min(48, max(24, dur / 5)))
    times = [dur * (0.03 + 0.94 * i / max(1, n - 1)) for i in range(n)]
    ocr = RapidOCR(det_limit_type="max", det_limit_side_len=1280)
    lines: list = []
    h = 0
    for i, t in enumerate(times):
        grab = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", src, "-frames:v", "1",
                               "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, timeout=60)
        if not grab.stdout:
            continue
        img = cv2.imdecode(np.frombuffer(grab.stdout, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        h, w = img.shape[:2]
        result, _ = ocr(img, use_det=True, use_cls=False, use_rec=False)
        for item in result or []:
            pts = item[0] if len(item) and np.ndim(item[0]) == 2 else item
            pts = np.asarray(pts, dtype=float).reshape(-1, 2)
            box = (pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max())
            if sub_like(box, w, h):
                lines.append((box[1], box[3], i))
        _progress(int(95 * (i + 1) / n))
    bands = bands_from_lines(lines, h, max(3, int(0.12 * n))) if h else []
    if bands:
        desc = ", ".join(f"{b['y0'] * 100:.0f}–{b['y1'] * 100:.0f}%" for b in bands)
        info = f"Tìm thấy phụ đề gốc ở {desc} (quét {n} khung)."
    else:
        info = f"Không thấy phụ đề cứng nào (quét {n} khung)."
    print(json.dumps({"bands": bands, "info": info}, ensure_ascii=False))


def main(argv: list[str]) -> int:
    if argv == ["check"]:
        check()
        return 0
    if len(argv) == 2 and argv[0] == "detect":
        detect(argv[1])
        return 0
    if len(argv) == 3 and argv[0] == "vieneu":
        vieneu(argv[1], argv[2])
        return 0
    if len(argv) >= 3 and argv[0] == "transcribe":
        transcribe(argv[1], argv[2], argv[3] if len(argv) > 3 and argv[3] not in ("", "auto") else None,
                   words=len(argv) > 4 and argv[4] == "words", hint=argv[5] if len(argv) > 5 and argv[5] else None)
        return 0
    if len(argv) == 4 and argv[0] == "separate":
        separate(argv[1], argv[2], argv[3])
        return 0
    sys.stderr.write(__doc__ or "")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
