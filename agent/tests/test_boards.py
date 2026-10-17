def test_create_list_get_board(client):
    r = client.post("/api/boards", json={"name": "Scene 01"})
    assert r.status_code == 200
    board = r.json()
    assert board["name"] == "Scene 01"
    assert isinstance(board["id"], int)

    r = client.get("/api/boards")
    assert r.status_code == 200
    listing = r.json()
    assert any(b["id"] == board["id"] for b in listing)

    r = client.get(f"/api/boards/{board['id']}")
    assert r.status_code == 200
    detail = r.json()
    assert detail["board"]["id"] == board["id"]
    assert detail["nodes"] == []
    assert detail["edges"] == []


def test_get_missing_board_returns_404(client):
    r = client.get("/api/boards/999")
    assert r.status_code == 404


def test_patch_board_rename(client):
    b = client.post("/api/boards", json={"name": "Old"}).json()
    r = client.patch(f"/api/boards/{b['id']}", json={"name": "New"})
    assert r.status_code == 200
    assert r.json()["name"] == "New"

    # persistence
    r = client.get(f"/api/boards/{b['id']}")
    assert r.json()["board"]["name"] == "New"


def test_patch_missing_board_returns_404(client):
    r = client.patch("/api/boards/999", json={"name": "x"})
    assert r.status_code == 404


def test_delete_board_cascades_children(client):
    """DELETE /api/boards/{id} must remove every child row that references
    the board so a re-create with the same id (sqlite autoincrement edge
    case) doesn't pull in orphan rows."""
    from flowboard.db import get_session
    from flowboard.db.models import (
        Asset,
        BoardFlowProject,
        ChatMessage,
        Edge,
        Node,
        PipelineRun,
        Plan,
        PlanRevision,
        Request,
    )
    from sqlmodel import select

    b = client.post("/api/boards", json={"name": "to-be-deleted"}).json()
    bid = b["id"]

    # Seed: 2 nodes + 1 edge + 1 request + 1 asset + 1 chat + 1 plan with
    # 1 revision + 1 pipeline run + Flow-project mapping.
    n1 = client.post("/api/nodes", json={"board_id": bid, "type": "image"}).json()
    n2 = client.post("/api/nodes", json={"board_id": bid, "type": "video"}).json()
    client.post(
        "/api/edges", json={"board_id": bid, "source_id": n1["id"], "target_id": n2["id"]}
    ).json()
    client.post(
        "/api/requests",
        json={
            "node_id": n1["id"],
            "type": "proxy",
            "params": {"url": "https://aisandbox-pa.googleapis.com/v1/x"},
        },
    ).json()
    with get_session() as s:
        s.add(Asset(uuid_media_id="11111111-2222-3333-4444-555555555555", node_id=n1["id"], kind="image"))
        s.add(ChatMessage(board_id=bid, role="user", content="hi"))
        plan = Plan(board_id=bid, spec={"k": "v"})
        s.add(plan)
        s.commit()
        s.refresh(plan)
        s.add(PlanRevision(plan_id=plan.id, rev_no=1, spec={}, edits={}))
        s.add(PipelineRun(plan_id=plan.id, status="pending"))
        s.add(BoardFlowProject(board_id=bid, flow_project_id="fpfpfpfp"))
        s.commit()

    # Delete.
    r = client.delete(f"/api/boards/{bid}")
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": bid}

    # Board itself gone.
    assert client.get(f"/api/boards/{bid}").status_code == 404

    # Every child table swept.
    with get_session() as s:
        for table, where in [
            (Node, Node.board_id == bid),
            (Edge, Edge.board_id == bid),
            (ChatMessage, ChatMessage.board_id == bid),
            (Plan, Plan.board_id == bid),
            (BoardFlowProject, BoardFlowProject.board_id == bid),
        ]:
            rows = s.exec(select(table).where(where)).all()
            assert rows == [], f"{table.__name__} not cleared: {rows}"
        # Asset / Request reference node_id, which no longer exists.
        assert s.exec(select(Asset).where(Asset.node_id.in_([n1["id"], n2["id"]]))).all() == []
        assert s.exec(select(Request).where(Request.node_id.in_([n1["id"], n2["id"]]))).all() == []


def test_delete_board_with_saved_reference_and_chat_run(client):
    """A ★ Saved reference points at its source board, and a chat run points
    at the board and a message. Both are FKs, so the delete answered 500 the
    first time anything had been saved. The reference is cross-board and
    must survive, detached; the chat rows go with the board."""
    from flowboard.db import get_session
    from flowboard.db.models import Asset, ChatAttachment, ChatMessage, ChatRun, Reference
    from sqlmodel import select

    bid = client.post("/api/boards", json={"name": "saved-from"}).json()["id"]
    media_id = "22222222-3333-4444-5555-666666666666"
    with get_session() as s:
        s.add(Reference(media_id=media_id, kind="character", source_board_id=bid))
        msg = ChatMessage(board_id=bid, role="user", content="làm video")
        asset = Asset(uuid_media_id="33333333-4444-5555-6666-777777777777", kind="image")
        s.add(msg)
        s.add(asset)
        s.commit()
        s.refresh(msg)
        s.refresh(asset)
        s.add(ChatAttachment(message_id=msg.id, asset_id=asset.id))
        s.add(ChatRun(board_id=bid, user_message_id=msg.id, status="done"))
        s.commit()

    r = client.delete(f"/api/boards/{bid}")
    assert r.status_code == 200, r.text

    with get_session() as s:
        ref = s.exec(select(Reference).where(Reference.media_id == media_id)).one()
        assert ref.source_board_id is None, "the saved reference must survive, detached"
        assert s.exec(select(ChatRun).where(ChatRun.board_id == bid)).all() == []
        assert s.exec(select(ChatAttachment)).all() == []
        assert s.exec(select(ChatMessage).where(ChatMessage.board_id == bid)).all() == []


def test_delete_missing_board_returns_404(client):
    r = client.delete("/api/boards/999")
    assert r.status_code == 404


def test_clear_media_keeps_nodes_and_prompts(client):
    """Renders go, intent stays: prompt / title / character picks / 60 fps
    toggle survive; references are kept unless asked for."""
    from flowboard.db import get_session
    from flowboard.db.models import Edge, Node
    from sqlmodel import select

    bid = client.post("/api/boards", json={"name": "clear-me"}).json()["id"]
    def mk(ntype, data, status="done"):
        n = client.post("/api/nodes", json={"board_id": bid, "type": ntype}).json()
        client.patch(f"/api/nodes/{n['id']}", json={"data": data, "status": status})
        return n["id"]
    model = mk("character", {"title": "Mẫu", "charGender": "female", "mediaId": "m-1", "aiBrief": "a woman"})
    scene = mk("image", {"title": "Cảnh 1", "prompt": "wide shot", "mediaId": "s-1",
                         "mediaIds": ["s-1", "s-2"], "renderedAt": "t", "aiBrief": "scene"})
    video = mk("video", {"title": "Video 1", "prompt": "0-3s …", "mediaId": "v-1", "videoQuality": "lite"})
    export = mk("export", {"smooth60": True, "mediaId": "x-1"})
    edge = client.post("/api/edges", json={"board_id": bid, "source_id": scene, "target_id": video}).json()
    with get_session() as s:
        e = s.get(Edge, edge["id"]); e.source_variant_idx = 1; s.add(e); s.commit()

    r = client.post(f"/api/boards/{bid}/clear-media", json={"include_refs": False})
    assert r.status_code == 200, r.text
    assert r.json()["cleared"] == 3

    with get_session() as s:
        by_id = {n.id: n for n in s.exec(select(Node).where(Node.board_id == bid)).all()}
        assert by_id[model].data["mediaId"] == "m-1" and by_id[model].status == "done"
        sc = by_id[scene]
        assert sc.status == "idle" and sc.data["prompt"] == "wide shot" and sc.data["title"] == "Cảnh 1"
        assert not any(k in sc.data for k in ("mediaId", "mediaIds", "renderedAt", "aiBrief"))
        assert by_id[video].data == {"title": "Video 1", "prompt": "0-3s …"}
        assert by_id[export].data == {"smooth60": True}
        assert s.get(Edge, edge["id"]).source_variant_idx is None

    r = client.post(f"/api/boards/{bid}/clear-media", json={"include_refs": True})
    assert r.json()["cleared"] == 1
    with get_session() as s:
        m = s.get(Node, model)
        assert m.status == "idle" and m.data == {"title": "Mẫu", "charGender": "female"}
