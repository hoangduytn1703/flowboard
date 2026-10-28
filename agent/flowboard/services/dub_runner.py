"""Runs inside pyvideotrans' virtualenv (torch / faster-whisper / sherpa-onnx
live there, not in flowboard's). Called by ``services/dub.py``:

  python dub_runner.py transcribe <audio.wav> <out.json> [language] [words]
      → {"language": "zh", "segments": [{"start", "end", "text"[, "words": [{"start", "end", "word"}]]}]}
      ("words" as the 4th argument adds each word's timing — Edit auto CapCut cuts subtitles on them)
  python dub_runner.py separate <audio.wav> <vocals.wav> <bgm.wav>
      → {"ok": true}
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


def _load_whisper():
    from faster_whisper import WhisperModel

    local_dir = str(_root() / "models" / WHISPER_DIR)
    if not Path(local_dir, "model.bin").is_file():
        raise SystemExit(f"whisper model missing: {local_dir}")
    try:
        import torch

        cuda = torch.cuda.is_available()
    except Exception:  # noqa: BLE001 — torch is optional for CPU runs
        cuda = False
    attempts = [("cuda", "float16"), ("cuda", "int8_float16")] if cuda else []
    attempts += [("cpu", "int8"), ("cpu", "float32")]
    last = None
    for device, compute in attempts:
        try:
            return WhisperModel(local_dir, device=device, compute_type=compute)
        except Exception as exc:  # noqa: BLE001 — try the next precision / device
            last = exc
    raise SystemExit(f"could not load whisper: {last}")


def transcribe(audio: str, out: str, language: str | None, words: bool = False) -> None:
    _progress(5)
    model = _load_whisper()
    _progress(15)
    segments, info = model.transcribe(
        audio,
        language=language or None,
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 350},
        condition_on_previous_text=False,
        word_timestamps=words,
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
    for i, item in enumerate(lines):
        text = str(item.get("text") or "").strip()
        out = str(item["out"])
        if not text:
            continue
        wav = tts.infer(text, voice=voice)
        if getattr(wav, "size", 0) == 0:
            raise SystemExit(f"vieneu returned no audio for line {i + 1}")
        tts.save(wav, out)
        done += 1
        _progress(10 + int(88 * (i + 1) / len(lines)))
    _progress(100)
    print(json.dumps({"ok": True, "done": done}))


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "vieneu":
        vieneu(argv[1], argv[2])
        return 0
    if len(argv) >= 3 and argv[0] == "transcribe":
        transcribe(argv[1], argv[2], argv[3] if len(argv) > 3 and argv[3] not in ("", "auto") else None,
                   words=len(argv) > 4 and argv[4] == "words")
        return 0
    if len(argv) == 4 and argv[0] == "separate":
        separate(argv[1], argv[2], argv[3])
        return 0
    sys.stderr.write(__doc__ or "")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
