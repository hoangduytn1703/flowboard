"""FB-007: a Veo quality with no batch-path model is rendered as Lite, and
the worker says so instead of stamping the node with the quality it asked for."""
from __future__ import annotations

import pytest

from flowboard.db.models import Request
from flowboard.worker import processor as proc

_DOWNGRADE = {
    "requested_quality": "quality",
    "requested_model": "veo_3_1_i2v_s_portrait",
    "model": "veo_3_1_i2v_lite",
    "quality": "lite",
}


@pytest.mark.asyncio
async def test_gen_video_lifts_the_downgrade_into_the_result(client, monkeypatch):
    monkeypatch.setattr(proc, "VIDEO_POLL_INTERVAL_S", 0.01)

    async def _no_sync(ids, project_id, *, what):
        return list(ids), []

    monkeypatch.setattr(proc, "_sync_media_into_project", _no_sync)

    class _StubSdk:
        async def gen_video(self, **kwargs):
            return {
                "raw": {},
                "operation_names": ["op-1"],
                "model": "veo_3_1_i2v_lite",
                "model_downgrade": dict(_DOWNGRADE),
            }

        async def check_async(self, names, workflows=None):
            return {"operations": [
                {"name": "op-1", "done": True, "media_entries": [{"media_id": "v1"}]}
            ]}

    monkeypatch.setattr(proc, "get_flow_sdk", lambda: _StubSdk())
    out, err = await proc._handle_gen_video({
        "prompt": "wave", "project_id": "abcd1234", "start_media_id": "f1",
        "video_quality": "quality",
    })
    assert err is None
    assert out["model_downgrade"] == _DOWNGRADE


def test_node_stamp_names_the_model_that_rendered():
    req = Request(
        type="gen_video",
        params={"prompt": "p", "video_quality": "quality"},
        status="running",
    )
    patch = proc._node_completion_patch(
        req, {"media_ids": ["v1"], "model_downgrade": dict(_DOWNGRADE)}
    )
    assert patch["videoQuality"] == "lite"

    plain = proc._node_completion_patch(req, {"media_ids": ["v1"]})
    assert plain["videoQuality"] == "quality"
