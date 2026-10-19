"""Cross-project media sync for gen_image / edit_image / gen_video (FB-008).

Flow scopes a media id to the project that created it. After the user
switches Flow project (or Google account) a ref / start frame from the old
project comes back `[5]` NOT_FOUND, so every Flow handler re-homes its input
media through `media_project_sync` before dispatch — the same path
`_handle_gen_video_omni` has used since the cross-board Reference library.
"""
from __future__ import annotations

import pytest
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import MediaProjectMapping
from flowboard.services import media as media_service
from flowboard.services import media_project_sync as sync_mod
from flowboard.worker import processor as proc

PID = "abcd1234"


def _stub_sync(monkeypatch, mapping: dict[str, str], *, fail: tuple = ()):
    """Replace the per-id sync with a lookup table; ids in `fail` raise."""
    calls: list[tuple[str, str]] = []

    async def _ensure(mid, project_id):
        calls.append((mid, project_id))
        if mid in fail:
            raise sync_mod.MediaSyncError(f"no bytes for {mid}")
        return mapping.get(mid, mid)

    monkeypatch.setattr(sync_mod, "ensure_media_in_project", _ensure)
    return calls


def _mapped_ids(project_id: str) -> dict[str, str]:
    with get_session() as s:
        rows = s.exec(
            select(MediaProjectMapping).where(
                MediaProjectMapping.project_id == project_id
            )
        ).all()
        return {r.original_media_id: r.project_local_media_id for r in rows}


# ── gen_image ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gen_image_syncs_refs_into_the_target_project(client, monkeypatch):
    calls = _stub_sync(monkeypatch, {"ref-old-a": "ref-new-a", "ref-old-b": "ref-new-b"})
    captured: dict = {}

    class _StubSdk:
        async def gen_image(self, **kwargs):
            captured.update(kwargs)
            return {"raw": {}, "media_ids": ["aa11"], "media_entries": [{"media_id": "aa11"}]}

    monkeypatch.setattr(proc, "get_flow_sdk", lambda: _StubSdk())

    out, err = await proc._handle_gen_image({
        "prompt": "a cat",
        "project_id": PID,
        "ref_media_ids": ["ref-old-a", "ref-old-b"],
    })
    assert err is None, out
    assert captured["ref_media_ids"] == ["ref-new-a", "ref-new-b"]
    assert calls == [("ref-old-a", PID), ("ref-old-b", PID)]
    assert "sync_failures" not in out
    # The fresh render is recorded as native to this project, so using it
    # as a ref here later is a cache hit rather than a re-upload.
    assert _mapped_ids(PID) == {"aa11": "aa11"}


@pytest.mark.asyncio
async def test_gen_image_passes_an_unsyncable_ref_through(client, monkeypatch):
    """No local bytes is also the normal state of a ref that already lives
    in this project — send the original rather than silently dropping it."""
    _stub_sync(monkeypatch, {"ref-a": "ref-a-local"}, fail=("ref-b",))
    captured: dict = {}

    class _StubSdk:
        async def gen_image(self, **kwargs):
            captured.update(kwargs)
            return {"raw": {}, "media_ids": ["bb22"]}

    monkeypatch.setattr(proc, "get_flow_sdk", lambda: _StubSdk())

    out, err = await proc._handle_gen_image({
        "prompt": "a cat",
        "project_id": PID,
        "ref_media_ids": ["ref-a", "ref-b"],
    })
    assert err is None
    assert captured["ref_media_ids"] == ["ref-a-local", "ref-b"]
    assert [f["media_id"] for f in out["sync_failures"]] == ["ref-b"]


@pytest.mark.asyncio
async def test_gen_image_without_refs_does_not_sync(client, monkeypatch):
    calls = _stub_sync(monkeypatch, {})

    class _StubSdk:
        async def gen_image(self, **kwargs):
            assert kwargs["ref_media_ids"] is None
            return {"raw": {}, "media_ids": ["cc33"]}

    monkeypatch.setattr(proc, "get_flow_sdk", lambda: _StubSdk())
    _out, err = await proc._handle_gen_image({"prompt": "a cat", "project_id": PID})
    assert err is None
    assert calls == []


@pytest.mark.asyncio
async def test_gen_image_muse_path_never_syncs(client, monkeypatch):
    calls = _stub_sync(monkeypatch, {})

    async def fake_run_muse_media(**kwargs):
        return {"media_ids": ["m1"]}, None

    monkeypatch.setattr(
        "flowboard.services.muse_media.run_muse_media", fake_run_muse_media
    )
    _out, err = await proc._handle_gen_image({
        "prompt": "a cat", "media_provider": "muse", "ref_media_ids": ["r1"],
    })
    assert err is None
    assert calls == []


# ── edit_image ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_edit_image_syncs_source_and_refs(client, monkeypatch):
    calls = _stub_sync(
        monkeypatch, {"src-old": "src-new", "ref-old": "ref-new"}
    )
    captured: dict = {}

    class _StubSdk:
        async def edit_image(self, **kwargs):
            captured.update(kwargs)
            return {"raw": {}, "media_ids": ["dd44"]}

    monkeypatch.setattr(proc, "get_flow_sdk", lambda: _StubSdk())

    out, err = await proc._handle_edit_image({
        "prompt": "make it red",
        "project_id": PID,
        "source_media_id": "src-old",
        "ref_media_ids": ["ref-old"],
    })
    assert err is None, out
    assert captured["source_media_id"] == "src-new"
    assert captured["ref_media_ids"] == ["ref-new"]
    assert calls == [("src-old", PID), ("ref-old", PID)]


@pytest.mark.asyncio
async def test_edit_image_without_refs_keeps_refs_none(client, monkeypatch):
    _stub_sync(monkeypatch, {"src-old": "src-new"})
    captured: dict = {}

    class _StubSdk:
        async def edit_image(self, **kwargs):
            captured.update(kwargs)
            return {"raw": {}, "media_ids": ["ee55"]}

    monkeypatch.setattr(proc, "get_flow_sdk", lambda: _StubSdk())
    _out, err = await proc._handle_edit_image({
        "prompt": "x", "project_id": PID, "source_media_id": "src-old",
    })
    assert err is None
    assert captured["source_media_id"] == "src-new"
    assert captured["ref_media_ids"] is None


# ── gen_video (Veo i2v) ───────────────────────────────────────────────────


class _VideoSdk:
    """Dispatch returns one op per start frame; first poll finishes them all."""

    def __init__(self):
        self.captured: dict = {}

    async def gen_video(self, **kwargs):
        self.captured.update(kwargs)
        n = len(kwargs.get("start_media_ids") or [kwargs.get("start_media_id")])
        return {"raw": {}, "operation_names": [f"op-{i}" for i in range(n)]}

    async def check_async(self, names, workflows=None):
        return {
            "raw": {},
            "operations": [
                {
                    "name": name,
                    "done": True,
                    "media_entries": [{"media_id": f"vid{i}"}],
                }
                for i, name in enumerate(names)
            ],
        }


@pytest.mark.asyncio
async def test_gen_video_syncs_the_single_start_frame(client, monkeypatch):
    monkeypatch.setattr(proc, "VIDEO_POLL_INTERVAL_S", 0.01)
    _stub_sync(monkeypatch, {"frame-old": "frame-new"})
    sdk = _VideoSdk()
    monkeypatch.setattr(proc, "get_flow_sdk", lambda: sdk)

    out, err = await proc._handle_gen_video({
        "prompt": "wave",
        "project_id": PID,
        "start_media_id": "frame-old",
    })
    assert err is None, out
    assert sdk.captured["start_media_id"] == "frame-new"
    assert sdk.captured["start_media_ids"] is None
    assert _mapped_ids(PID) == {"vid0": "vid0"}


@pytest.mark.asyncio
async def test_gen_video_multi_start_keeps_slot_alignment(client, monkeypatch):
    """A frame that can't be synced is sent as-is, in its own slot, so
    start frame i still lines up with clip slot i."""
    monkeypatch.setattr(proc, "VIDEO_POLL_INTERVAL_S", 0.01)
    _stub_sync(monkeypatch, {"f1": "f1-new", "f3": "f3-new"}, fail=("f2",))
    sdk = _VideoSdk()
    monkeypatch.setattr(proc, "get_flow_sdk", lambda: sdk)

    out, err = await proc._handle_gen_video({
        "prompt": "wave",
        "project_id": PID,
        "start_media_ids": ["f1", "f2", "f3"],
    })
    assert err is None, out
    assert sdk.captured["start_media_ids"] == ["f1-new", "f2", "f3-new"]
    assert out["media_ids"] == ["vid0", "vid1", "vid2"]
    assert [f["media_id"] for f in out["raw_dispatch"]["sync_failures"]] == ["f2"]


# ── the sync service itself ───────────────────────────────────────────────


class _UploadSdk:
    def __init__(self, new_id: str = "ff66"):
        self.uploads: list[dict] = []
        self.new_id = new_id

    async def upload_image(self, **kwargs):
        self.uploads.append(kwargs)
        return {"media_id": self.new_id}


@pytest.mark.asyncio
async def test_ensure_media_reuploads_once_then_hits_the_cache(client, monkeypatch):
    original = "0123abcd"
    (media_service.MEDIA_CACHE_DIR / f"{original}.png").write_bytes(b"\x89PNG-old")
    sdk = _UploadSdk("9876fedc")
    monkeypatch.setattr(sync_mod, "get_flow_sdk", lambda: sdk)

    first = await sync_mod.ensure_media_in_project(original, "proj-b")
    second = await sync_mod.ensure_media_in_project(original, "proj-b")
    assert first == second == "9876fedc"
    assert len(sdk.uploads) == 1
    assert sdk.uploads[0]["project_id"] == "proj-b"


@pytest.mark.asyncio
async def test_remembered_media_is_not_reuploaded_in_its_own_project(client, monkeypatch):
    sdk = _UploadSdk()
    monkeypatch.setattr(sync_mod, "get_flow_sdk", lambda: sdk)

    assert sync_mod.remember_media_in_project(["aa11", "aa11", None], PID) == 1
    # Idempotent.
    assert sync_mod.remember_media_in_project(["aa11"], PID) == 0

    assert await sync_mod.ensure_media_in_project("aa11", PID) == "aa11"
    assert sdk.uploads == []


def test_upload_route_remembers_the_upload_as_native(client, monkeypatch):
    from flowboard.services import flow_sdk as flow_sdk_module
    from tests.test_upload import _png_bytes

    media_uuid = "22222222-3333-4444-5555-666666666666"

    async def stub_upload(self, image_base64, mime_type, project_id, file_name):
        return {"raw": {}, "media_id": media_uuid}

    monkeypatch.setattr(flow_sdk_module.FlowSDK, "upload_image", stub_upload)
    monkeypatch.setattr(flow_sdk_module, "_sdk", None)
    r = client.post(
        "/api/upload",
        data={"project_id": PID},
        files={"file": ("x.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 200, r.text
    assert _mapped_ids(PID) == {media_uuid: media_uuid}


def test_backfill_records_old_generations_under_their_project():
    from flowboard.db.models import Request

    with get_session() as s:
        s.add(Request(type="gen_image", status="done", params={"project_id": PID},
                      result={"media_ids": ["m-old-1", "m-old-2"]}))
        s.add(Request(type="gen_video", status="done", params={"project_id": "other"},
                      result={"media_ids": ["m-vid"]}))
        # not generations born in a project: skipped
        s.add(Request(type="gen_image", status="failed", params={"project_id": PID},
                      result={"media_ids": ["m-failed"]}))
        s.add(Request(type="export_video", status="done", params={},
                      result={"media_ids": ["m-export"]}))
        s.commit()

    assert sync_mod.backfill_identity_mappings() == 3
    assert _mapped_ids(PID) == {"m-old-1": "m-old-1", "m-old-2": "m-old-2"}
    assert _mapped_ids("other") == {"m-vid": "m-vid"}
    assert sync_mod.backfill_identity_mappings() == 0  # idempotent
