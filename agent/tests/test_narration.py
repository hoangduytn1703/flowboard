"""Voice-over lines: board context → scripted LLM → one line per video node."""
import asyncio
from unittest.mock import patch

from flowboard.db import get_session
from flowboard.db.models import Board, Edge, Node
from flowboard.services import narration


def _board():
    with get_session() as s:
        b = Board(name="ad")
        s.add(b)
        s.commit()
        s.refresh(b)
        note = Node(board_id=b.id, short_id="note", type="note",
                    data={"title": "Kịch bản", "prompt": "Áo thun SAIGON — 189k\nĐiểm bán:\n- Cotton 100%"})
        product = Node(board_id=b.id, short_id="prod", type="visual_asset",
                       data={"title": "Sản phẩm", "aiBrief": "a white t-shirt with SAIGON print"})
        s1 = Node(board_id=b.id, short_id="s1", type="image", data={"title": "Cảnh 1", "prompt": "full body intro"})
        s2 = Node(board_id=b.id, short_id="s2", type="image", data={"title": "Cảnh 2", "prompt": "fabric close-up"})
        v1 = Node(board_id=b.id, short_id="v1", type="video", data={"title": "Video 1", "prompt": "0-3s wave"})
        v2 = Node(board_id=b.id, short_id="v2", type="video", data={"title": "Video 2", "prompt": "0-3s touch"})
        s.add_all([note, product, s1, s2, v1, v2])
        s.commit()
        for n in (s1, s2, v1, v2):
            s.refresh(n)
        s.add_all([Edge(board_id=b.id, source_id=s1.id, target_id=v1.id),
                   Edge(board_id=b.id, source_id=s2.id, target_id=v2.id)])
        s.commit()
        return b.id, v1.id, v2.id


def test_write_narrations_writes_one_line_per_clip_onto_the_nodes():
    board_id, v1, v2 = _board()
    seen = {}

    async def fake_llm(feature, user_prompt, *, system_prompt=None, **kw):
        seen["feature"], seen["user"], seen["system"] = feature, user_prompt, system_prompt
        return '```json\n["Mọi người ơi, áo thun SAIGON đây", "Cotton 100% mát lắm, ghé giỏ hàng nhé"]\n```'

    with patch.object(narration, "run_llm", fake_llm):
        out = asyncio.run(narration.write_narrations(board_id, [v1, v2], instructions="giọng vui"))
    assert out == {v1: "Mọi người ơi, áo thun SAIGON đây", v2: "Cotton 100% mát lắm, ghé giỏ hàng nhé"}
    assert seen["feature"] == "auto_prompt" and "Vietnamese" in seen["system"]
    assert "Cotton 100%" in seen["user"] and "fabric close-up" in seen["user"] and "giọng vui" in seen["user"]
    with get_session() as s:
        assert s.get(Node, v1).data["narration"] == out[v1]
        assert s.get(Node, v2).data["narration"] == out[v2]


def test_write_narrations_rejects_bad_output_and_non_video_nodes(client):
    board_id, v1, v2 = _board()

    async def short_llm(*a, **kw):
        return '["chỉ một dòng"]'

    with patch.object(narration, "run_llm", short_llm):
        r = client.post("/api/prompt/narration", json={"board_id": board_id, "node_ids": [v1, v2]})
    assert r.status_code == 502 and "1 lines for 2 clips" in r.text
    with get_session() as s:
        from sqlmodel import select
        note = s.exec(select(Node).where(Node.board_id == board_id, Node.type == "note")).first()
    r = client.post("/api/prompt/narration", json={"board_id": board_id, "node_ids": [note.id]})
    assert r.status_code == 502 and "not a video node" in r.text


def test_parse_lines_accepts_objects_and_strips_quotes():
    lines = narration._parse_lines('[{"line": "\\"một\\""}, " hai  ba ", "bốn"]', 2)
    assert lines == ["một", "hai ba"]
