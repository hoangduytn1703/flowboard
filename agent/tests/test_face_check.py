"""services/face_check — counts faces so the UI can warn about shop photos."""
from pathlib import Path

import numpy as np

from flowboard.services import face_check


def test_model_ships_with_the_agent():
    assert face_check.MODEL_PATH.exists() and face_check.MODEL_PATH.stat().st_size > 100_000


def test_plain_product_shot_has_no_face(tmp_path: Path):
    import cv2

    img = np.full((600, 600, 3), 235, np.uint8)
    cv2.rectangle(img, (180, 120), (420, 520), (90, 140, 220), -1)  # "a dress"
    p = tmp_path / "dress.jpg"
    cv2.imwrite(str(p), img)
    assert face_check.count_faces(p) == 0


def test_unreadable_file_is_none_not_an_error(tmp_path: Path):
    p = tmp_path / "x.jpg"
    p.write_bytes(b"not an image")
    assert face_check.count_faces(p) in (0, None)
    assert face_check.count_faces(tmp_path / "missing.jpg") is None
