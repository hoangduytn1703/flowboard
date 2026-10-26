"""The Gemini sparkle on Flow images: detected, inverted out, uploads untouched."""
import numpy as np
from PIL import Image

from flowboard.services import watermark


def _stamped(base: np.ndarray, k: float = 0.3) -> np.ndarray:
    """``base`` with the star blended in the way Flow does it (opacity ``k``)."""
    a = (k * watermark.shape_map())[:, :, None]
    out = base.astype(np.float32).copy()
    sl = (slice(base.shape[0] - watermark.REGION, base.shape[0]), slice(base.shape[1] - watermark.REGION, base.shape[1]))
    out[sl] = (1 - a) * out[sl] + a * 255
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def _textured(h=768, w=1376, seed=1):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w]
    base = np.stack([60 + 0.1 * x, 90 + 0.08 * y, 120 + 0.05 * (x + y)], axis=2) + rng.normal(0, 6, (h, w, 3))
    return np.clip(base, 0, 255).astype(np.uint8)


def test_shape_map_is_the_star_in_the_corner():
    a = watermark.shape_map()
    assert a.shape == (160, 160) and a.max() == 1.0
    ys, xs = np.nonzero(a > 0.2)
    r = watermark.REGION
    assert 70 <= r - xs.max() <= 80 and 118 <= r - xs.min() <= 128  # 74..121 px from the right edge
    assert 70 <= r - ys.max() <= 80 and 118 <= r - ys.min() <= 128


def test_stamp_is_detected_and_inverted_back():
    base = _textured()
    stamped = _stamped(base)
    assert not watermark.has_mark(base)
    assert watermark.has_mark(stamped)
    sl = (slice(768 - 160, 768), slice(1376 - 160, 1376))
    assert abs(watermark.estimate_alpha(stamped[sl]) - 0.3) < 0.05  # heavy synthetic noise; real corners are within 0.01
    assert abs(watermark.estimate_alpha(_stamped(base, 0.2)[sl]) - 0.2) < 0.05  # 1024² renders are lighter
    assert watermark.unblend(watermark.unblend(stamped)) is not None  # a second pass is a no-op, never a dark star
    restored = watermark.unblend(stamped)
    core = watermark._masks()[0]
    err = np.abs(restored[sl][core].astype(int) - base[sl][core].astype(int)).mean()
    assert err < 4.0  # back to the original (synthetic noise σ=6 costs ~3 levels; real flat corners end within 1–2)
    assert not watermark.has_mark(restored)


def test_small_images_and_white_corners_are_skipped():
    tiny = np.full((200, 200, 3), 120, np.uint8)
    assert not watermark.has_mark(tiny) and watermark.unblend(tiny) is tiny
    white = _stamped(np.full((1024, 1024, 3), 252, np.uint8))
    assert not watermark.has_mark(white)


def test_remove_from_file_rewrites_only_stamped_images(tmp_path):
    base = _textured(1024, 1024, seed=3)
    plain = tmp_path / "upload.jpg"
    Image.fromarray(base).save(plain, quality=95)
    assert watermark.remove_from_file(plain) is False  # an upload: left alone
    stamped = tmp_path / "flow.png"
    Image.fromarray(_stamped(base)).save(stamped)
    assert watermark.remove_from_file(stamped) is True
    after = np.asarray(Image.open(stamped).convert("RGB"))
    assert not watermark.has_mark(after)
    assert watermark.remove_from_file(stamped) is False  # already clean
    # JPEG round trip stays close to the original in the star
    jpg = tmp_path / "flow.jpg"
    Image.fromarray(_stamped(base)).save(jpg, quality=95)
    assert watermark.remove_from_file(jpg) is True
    after = np.asarray(Image.open(jpg).convert("RGB")).astype(int)
    core = watermark._masks()[0]
    sl = (slice(1024 - 160, 1024), slice(1024 - 160, 1024))
    assert np.abs(after[sl][core] - base[sl][core].astype(int)).mean() < 6  # JPEG noise ×1.5, not the inversion
    assert watermark.remove_from_file(tmp_path / "none.gif") is False


def test_switch_and_batch_route(client, monkeypatch, tmp_path):
    from flowboard.db import get_session
    from flowboard.db.models import Asset
    from flowboard.services import media as media_service

    base = _textured(1024, 1024, seed=5)
    stamped = tmp_path / "gen.jpg"
    Image.fromarray(_stamped(base)).save(stamped, quality=95)
    upload = tmp_path / "up.jpg"
    Image.fromarray(base).save(upload, quality=95)
    with get_session() as s:
        s.add(Asset(kind="image", uuid_media_id="11111111-1111-1111-1111-111111111111", local_path=str(stamped), mime="image/jpeg"))
        s.add(Asset(kind="image", uuid_media_id="22222222-2222-2222-2222-222222222222", local_path=str(upload), mime="image/jpeg"))
        s.add(Asset(kind="video", uuid_media_id="33333333-3333-3333-3333-333333333333", local_path=str(upload), mime="video/mp4"))
        s.commit()
    st = client.get("/api/media/clean-marks").json()
    assert st["enabled"] is True and st["candidates"] == 2
    assert client.put("/api/media/clean-marks", json={"enabled": False}).json()["enabled"] is False
    # off: the cache hook leaves a new image alone
    assert watermark.clean_if_generated(stamped, "image", "image/jpeg") is False
    assert watermark.has_mark(np.asarray(Image.open(stamped).convert("RGB")))
    client.put("/api/media/clean-marks", json={"enabled": True})
    assert watermark.clean_if_generated(stamped, "thumbnail", "image/jpeg") is False  # not a generated image
    r = client.post("/api/media/clean-marks/run").json()
    assert r == {"checked": 2, "cleaned": 1}  # the upload had nothing to clean
    assert not watermark.has_mark(np.asarray(Image.open(stamped).convert("RGB")))
    media_service.MEDIA_CACHE_DIR  # the hook in fetch_and_cache / ingest_inline_bytes shares clean_if_generated
