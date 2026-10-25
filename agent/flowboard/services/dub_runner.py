"""Runs inside pyvideotrans' virtualenv (torch / faster-whisper / sherpa-onnx
live there, not in flowboard's). Called by ``services/dub.py``:

  python dub_runner.py transcribe <audio.wav> <out.json> [language]
      → {"language": "zh", "segments": [{"start", "end", "text"}]}
  python dub_runner.py separate <audio.wav> <vocals.wav> <bgm.wav>
      → {"ok": true}

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


def transcribe(audio: str, out: str, language: str | None) -> None:
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
    )
    total = max(float(getattr(info, "duration", 0.0) or 0.0), 0.1)
    rows = []
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        rows.append({"start": round(float(seg.start), 3), "end": round(float(seg.end), 3), "text": text})
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


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[0] == "transcribe":
        transcribe(argv[1], argv[2], argv[3] if len(argv) > 3 and argv[3] not in ("", "auto") else None)
        return 0
    if len(argv) == 4 and argv[0] == "separate":
        separate(argv[1], argv[2], argv[3])
        return 0
    sys.stderr.write(__doc__ or "")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
