"""Does a photo show people's faces? (shop photos with a real model).

Flow drops video made from a face it takes for a real / famous person — and
product photos taken from a shop page usually are a real model (measured
26/10: the shop photo of the maternity dress, two faces, was dropped on the
first try and passed on the second, 33 s each; an AI-drawn woman passed).
Worse, the photo is the product reference for every scene image, so the
model's real face leaks into the scenes and from there into every clip.

This only counts faces (OpenCV's YuNet, ~230 KB model in ``assets/``, ~20 ms
an image on CPU) so the UI can warn and offer a clean product-only image.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).resolve().parent.parent / "assets" / "face_detection_yunet_2023mar.onnx"
#: Detector confidence; 0.7 found 2 of 3 phone-covered faces and no false hits
#: on product-only shots.
SCORE = 0.7
#: Faces smaller than this share of the image's short side are ignored (a
#: tiny face in a crowd backdrop is not what Flow reacts to).
MIN_FACE_SHARE = 0.04
_WORK_SIZE = 640


def _detector(width: int, height: int):
    import cv2  # local: keeps agent start-up light

    return cv2.FaceDetectorYN.create(str(MODEL_PATH), "", (width, height), SCORE)


@lru_cache(maxsize=512)
def _count_cached(path: str, mtime: float, size: int) -> int:
    import cv2

    img = cv2.imread(path)
    if img is None:
        return 0
    h, w = img.shape[:2]
    scale = min(1.0, _WORK_SIZE / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))))
    h2, w2 = img.shape[:2]
    _, faces = _detector(w2, h2).detect(img)
    if faces is None:
        return 0
    floor = MIN_FACE_SHARE * min(h2, w2)
    return sum(1 for f in faces if min(f[2], f[3]) >= floor)


def count_faces(path: Path) -> Optional[int]:
    """Faces in the image at ``path``; None when it cannot be read."""
    try:
        st = path.stat()
        return _count_cached(str(path), st.st_mtime, st.st_size)
    except Exception as exc:  # noqa: BLE001 — a check, never a blocker
        logger.warning("face_check: %s: %s", path.name, exc)
        return None
