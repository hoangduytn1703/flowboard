"""chat_agent ReAct loop — scripted LLM, mocked Flow dispatch.

``run_llm`` is scripted per test; ``_dispatch_flow`` (the worker Request
round-trip to Google Flow) is mocked, and the board's Flow project is
pinned by patching ``_flow_project_id``. ``record_activity`` runs for real
(Request rows).
"""
import asyncio
import json
from unittest.mock import AsyncMock, patch

from flowboard.db import get_session
from flowboard.db.models import Asset, Board, ChatMessage, ChatRun, Edge, Node
from flowboard.services import chat_agent
from flowboard.services.llm.base import LLMError

PROJECT = "e22fe3ef-902d-4248-8a65-f95d8b84f1b7"


def _pinned():
    return patch.object(chat_agent, "_flow_project_id", lambda board_id: PROJECT)


def _mk_run(board_name="T", message="do it"):
    with get_session() as s:
        b = Board(name=board_name)
        s.add(b)
        s.commit()
        s.refresh(b)
        m = ChatMessage(board_id=b.id, role="user", content=message, mentions=[])
        s.add(m)
        s.commit()
        s.refresh(m)
        run = ChatRun(board_id=b.id, user_message_id=m.id, status="running")
        s.add(run)
        s.commit()
        s.refresh(run)
        return b.id, run.id


def _short_ids(board_id):
    with get_session() as s:
        from sqlmodel import select

        nodes = s.exec(
            select(Node).where(Node.board_id == board_id).order_by(Node.id)
        ).all()
        return [n.short_id for n in nodes]


def _run_row(run_id):
    with get_session() as s:
        return s.get(ChatRun, run_id)


def _assistant_messages(board_id):
    with get_session() as s:
        from sqlmodel import select

        return s.exec(
            select(ChatMessage).where(
                ChatMessage.board_id == board_id,
                ChatMessage.role == "assistant",
            )
        ).all()


def test_full_scripted_run_create_edge_gen_image():
    board_id, run_id = _mk_run()

    plan = [
        lambda: json.dumps(
            {"tool": "create_node",
             "args": {"type": "image", "x": 0, "y": 0, "data": {"prompt": "cat"}}}
        ),
        lambda: json.dumps(
            {"tool": "create_node", "args": {"type": "video"}}
        ),
        lambda: json.dumps(
            {
                "tool": "add_edge",
                "args": {
                    "from_short_id": _short_ids(board_id)[0],
                    "to_short_id": _short_ids(board_id)[1],
                    "kind": "ref",
                },
            }
        ),
        lambda: json.dumps(
            {
                "tool": "gen_image",
                "args": {
                    "prompt": "a red cat",
                    "node_short_id": _short_ids(board_id)[0],
                },
            }
        ),
        lambda: json.dumps({"done": True, "reply": "xong"}),
    ]

    async def fake_llm(*args, **kwargs):
        return plan.pop(0)()

    async def fake_dispatch(node_id, req_type, params):
        assert req_type == "gen_image"
        assert params["prompt"] == "a red cat"
        assert params["project_id"] == PROJECT
        assert params["aspect_ratio"] == "IMAGE_ASPECT_RATIO_PORTRAIT"
        assert params["variant_count"] == 1
        return ["mid_cat"]

    with (
        patch.object(chat_agent, "run_llm", fake_llm),
        patch.object(chat_agent, "_dispatch_flow", fake_dispatch),
        _pinned(),
    ):
        asyncio.run(
            chat_agent.run_chat_agent(board_id, run_id, "do it", [], [])
        )

    assert plan == []
    shorts = _short_ids(board_id)
    assert len(shorts) == 2

    with get_session() as s:
        from sqlmodel import select

        img = s.exec(
            select(Node).where(Node.short_id == shorts[0])
        ).first()
        assert img.data["mediaIds"] == ["mid_cat"]
        assert img.data["mediaId"] == "mid_cat"
        assert img.status == "done"
        edges = s.exec(select(Edge).where(Edge.board_id == board_id)).all()
        assert len(edges) == 1
        # activity rows: one per turn (4 tool turns)
        from flowboard.db.models import Request

        reqs = s.exec(
            select(Request).where(Request.type == "chat_agent")
        ).all()
        assert len(reqs) == 4
        assert all(r.status == "done" for r in reqs)

    run = _run_row(run_id)
    assert run.status == "done"
    msgs = _assistant_messages(board_id)
    assert len(msgs) == 1 and msgs[0].content == "xong"


def test_gen_video_binds_to_new_video_node():
    """The start frame is an image node's media; the clip renders on Flow
    through the worker with the cheapest quality unless told otherwise."""
    board_id, run_id = _mk_run()
    with get_session() as s:
        src = Node(board_id=board_id, short_id="img1", type="image", x=0, y=0,
                   data={"mediaId": "srcmid1", "mediaIds": ["srcmid1"]}, status="done")
        s.add(src)
        s.commit()

    async def fake_llm(*args, **kwargs):
        calls = getattr(fake_llm, "n", 0)
        fake_llm.n = calls + 1
        if calls == 0:
            return json.dumps(
                {
                    "tool": "gen_video",
                    "args": {"prompt": "slow push-in", "source_node_short_id": "img1"},
                }
            )
        return json.dumps({"done": True, "reply": "video xong"})

    seen = {}

    async def fake_dispatch(node_id, req_type, params):
        seen.update(params, req_type=req_type)
        return ["vid1"]

    with (
        patch.object(chat_agent, "run_llm", fake_llm),
        patch.object(chat_agent, "_dispatch_flow", fake_dispatch),
        _pinned(),
    ):
        asyncio.run(chat_agent.run_chat_agent(board_id, run_id, "do it", [], []))

    assert seen["req_type"] == "gen_video"
    assert seen["start_media_id"] == "srcmid1"
    assert seen["project_id"] == PROJECT
    assert seen["video_quality"] == "lite"
    assert seen["aspect_ratio"] == "VIDEO_ASPECT_RATIO_PORTRAIT"
    with get_session() as s:
        from sqlmodel import select

        vids = s.exec(
            select(Node).where(Node.board_id == board_id, Node.type == "video")
        ).all()
        assert len(vids) == 1
        assert vids[0].data["mediaIds"] == ["vid1"]
    assert _run_row(run_id).status == "done"


def test_concat_videos_creates_merge_node(monkeypatch):
    board_id, run_id = _mk_run()
    with get_session() as s:
        vids = [
            Asset(kind="video", uuid_media_id=f"cvmid{i}",
                  local_path=f"/tmp/v{i}.mp4", mime="video/mp4")
            for i in range(2)
        ]
        s.add_all(vids)
        s.commit()
        for v in vids:
            s.refresh(v)
        aids = [v.id for v in vids]
        out = Asset(kind="video", uuid_media_id="concatmid",
                    local_path="/tmp/out.mp4", mime="video/mp4")
        s.add(out)
        s.commit()
        s.refresh(out)
        out_id = out.id

    monkeypatch.setattr(
        "flowboard.services.video_concat.concat_video_assets",
        lambda ids: (out_id, None),
    )

    async def fake_llm(*args, **kwargs):
        calls = getattr(fake_llm, "n", 0)
        fake_llm.n = calls + 1
        if calls == 0:
            return json.dumps(
                {"tool": "concat_videos",
                 "args": {"video_asset_ids": aids}}
            )
        return json.dumps({"done": True, "reply": "ghép xong"})

    async def fake_dispatch(*args, **kwargs):  # pragma: no cover — not used here
        raise AssertionError("concat must not render anything on Flow")

    with (
        patch.object(chat_agent, "run_llm", fake_llm),
        patch.object(chat_agent, "_dispatch_flow", fake_dispatch),
    ):
        asyncio.run(chat_agent.run_chat_agent(board_id, run_id, "do it", [], []))

    with get_session() as s:
        from sqlmodel import select

        # A video node, not "merge": the canvas renders video nodes (preview,
        # download); it has no renderer for merge.
        outs = s.exec(
            select(Node).where(Node.board_id == board_id, Node.type == "video")
        ).all()
        assert len(outs) == 1
        assert outs[0].data["mediaIds"] == ["concatmid"]
    assert _run_row(run_id).status == "done"


def test_llm_error_fails_run_with_message():
    board_id, run_id = _mk_run()

    async def boom(*args, **kwargs):
        raise LLMError("boom")

    with patch.object(chat_agent, "run_llm", boom):
        asyncio.run(chat_agent.run_chat_agent(board_id, run_id, "do it", [], []))

    run = _run_row(run_id)
    assert run.status == "failed"
    msgs = _assistant_messages(board_id)
    assert len(msgs) == 1 and "boom" in msgs[0].content


def test_chat_uses_its_own_pin_else_the_planners():
    """Chat AI is an optional feature: with no pin of its own it thinks with
    the planner's provider; once pinned, the planner is not consulted."""
    seen: list[str] = []

    def scripted(unpinned: set[str]):
        async def fake_llm(feature, *args, **kwargs):
            seen.append(feature)
            if feature in unpinned:
                raise LLMError(f"No AI provider configured for {feature}; open settings")
            return json.dumps({"done": True, "reply": "ok"})
        return fake_llm

    board_id, run_id = _mk_run()
    with patch.object(chat_agent, "run_llm", scripted({"chat_agent"})):
        asyncio.run(chat_agent.run_chat_agent(board_id, run_id, "do it", [], []))
    assert seen == ["chat_agent", "planner"]
    assert _run_row(run_id).status == "done"

    seen.clear()
    board_id, run_id = _mk_run()
    with patch.object(chat_agent, "run_llm", scripted(set())):
        asyncio.run(chat_agent.run_chat_agent(board_id, run_id, "do it", [], []))
    assert seen == ["chat_agent"]

    seen.clear()
    board_id, run_id = _mk_run()
    with patch.object(chat_agent, "run_llm", scripted({"chat_agent", "planner"})):
        asyncio.run(chat_agent.run_chat_agent(board_id, run_id, "do it", [], []))
    assert _run_row(run_id).status == "failed"
    assert "Chat AI" in _assistant_messages(board_id)[0].content


def test_unparseable_and_unknown_tool_recover():
    board_id, run_id = _mk_run()
    script = [
        "this is not json at all",
        json.dumps({"tool": "nope", "args": {}}),
        json.dumps({"done": True, "reply": "recovered"}),
    ]

    async def fake_llm(*args, **kwargs):
        return script.pop(0)

    with patch.object(chat_agent, "run_llm", fake_llm):
        asyncio.run(chat_agent.run_chat_agent(board_id, run_id, "do it", [], []))

    assert script == []
    assert _run_row(run_id).status == "done"
    msgs = _assistant_messages(board_id)
    assert msgs[0].content == "recovered"


def test_update_node_and_refresh_tools():
    board_id, run_id = _mk_run()
    script = [
        json.dumps(
            {"tool": "create_node",
             "args": {"type": "note", "data": {"title": "draft"}}}
        ),
        lambda: json.dumps(
            {
                "tool": "update_node",
                "args": {
                    "short_id": _short_ids(board_id)[0],
                    "data_patch": {"title": "final", "gone": None},
                },
            }
        ),
        lambda: json.dumps({"tool": "refresh", "args": {}}),
        lambda: json.dumps({"done": True, "reply": "ok"}),
    ]

    async def fake_llm(*args, **kwargs):
        step = script.pop(0)
        return step() if callable(step) else step

    with patch.object(chat_agent, "run_llm", fake_llm):
        asyncio.run(chat_agent.run_chat_agent(board_id, run_id, "do it", [], []))

    with get_session() as s:
        from sqlmodel import select

        node = s.exec(select(Node).where(Node.board_id == board_id)).first()
        assert node.data["title"] == "final"
        assert "gone" not in node.data
    assert _run_row(run_id).status == "done"


def test_build_board_context_includes_history_and_nodes():
    board_id, run_id = _mk_run(message="first")
    with get_session() as s:
        s.add(
            ChatMessage(
                board_id=board_id, role="assistant",
                content="previous reply", mentions=[],
            )
        )
        s.add(
            Node(board_id=board_id, short_id="ab12", type="image",
                 data={"prompt": "a cat", "mediaIds": ["m1", "m2"]})
        )
        s.commit()
    ctx = chat_agent.build_board_context(board_id, "second", [], [])
    assert "first" in ctx
    assert "previous reply" in ctx
    assert "#ab12" in ctx and "media=2" in ctx


def _ad_board():
    """What a draft for a 2-scene ad looks like: refs → images → videos."""
    return {
        "nodes": [
            {"key": "script", "type": "note", "data": {"title": "Kịch bản", "prompt": "..."}},
            {"key": "model", "type": "character",
             "data": {"title": "Người mẫu", "charGender": "female", "charCountry": "kr",
                      "charVibe": "clean", "charExtras": "long black hair"}},
            {"key": "product", "type": "visual_asset", "data": {"title": "Sản phẩm"}},
            {"key": "s1", "type": "image", "data": {"title": "Cảnh 1", "prompt": "wide shot"}},
            {"key": "s2", "type": "image", "data": {"title": "Cảnh 2", "prompt": "close-up"}},
            {"key": "v1", "type": "video", "data": {"title": "Video 1", "prompt": "0-3s ..."}},
            {"key": "v2", "type": "video", "data": {"title": "Video 2", "prompt": "0-3s ..."}},
        ],
        "edges": [["model", "s1"], ["product", "s1"], ["model", "s2"], ["product", "s2"],
                  ["s1", "v1"], ["s2", "v2"]],
    }


def test_build_board_drafts_a_whole_ad_in_one_turn():
    """Draft mode: one build_board call, then done — nothing is rendered."""
    board_id, run_id = _mk_run()
    script = [
        json.dumps({"tool": "build_board", "args": _ad_board()}),
        json.dumps({"done": True, "reply": "Đã dựng board, review rồi bấm Generate."}),
    ]

    async def fake_llm(*args, **kwargs):
        return script.pop(0)

    async def no_render(*args, **kwargs):  # pragma: no cover
        raise AssertionError("draft mode must not render")

    with (
        patch.object(chat_agent, "run_llm", fake_llm),
        patch.object(chat_agent, "_dispatch_flow", no_render),
    ):
        asyncio.run(chat_agent.run_chat_agent(board_id, run_id, "tạo kịch bản", [], []))

    assert script == [] and _run_row(run_id).status == "done"
    with get_session() as s:
        from sqlmodel import select

        nodes = {n.data.get("title"): n for n in
                 s.exec(select(Node).where(Node.board_id == board_id)).all()}
        edges = s.exec(select(Edge).where(Edge.board_id == board_id)).all()
    assert len(nodes) == 7 and len(edges) == 6
    assert nodes["Người mẫu"].type == "character"
    assert nodes["Người mẫu"].data["charCountry"] == "kr"
    assert nodes["Sản phẩm"].type == "visual_asset"
    assert all(n.status == "idle" for n in nodes.values())
    # Columns follow the graph: references, then scene images, then videos.
    assert nodes["Người mẫu"].x < nodes["Cảnh 1"].x < nodes["Video 1"].x
    assert nodes["Cảnh 1"].x == nodes["Cảnh 2"].x and nodes["Cảnh 1"].y != nodes["Cảnh 2"].y
    by_id = {n.id: n.data["title"] for n in nodes.values()}
    pairs = {(by_id[e.source_id], by_id[e.target_id]) for e in edges}
    assert ("Cảnh 1", "Video 1") in pairs and ("Sản phẩm", "Cảnh 2") in pairs


def test_build_board_rejects_a_bad_edge_and_writes_nothing():
    board_id, _ = _mk_run()
    spec = _ad_board()
    spec["edges"].append(["s1", "nope"])
    obs = asyncio.run(chat_agent._execute_tool(board_id, "build_board", spec))
    assert obs["ok"] is False and "nope" in obs["error"]
    with get_session() as s:
        from sqlmodel import select

        assert s.exec(select(Node).where(Node.board_id == board_id)).all() == []
