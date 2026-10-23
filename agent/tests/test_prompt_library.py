"""The prompt library routes: save, list by kind / search, edit, use, delete."""


def _mount():
    from flowboard.main import app
    from flowboard.routes import prompt_library
    if not any(getattr(r, "path", "").startswith("/api/prompt-library") for r in app.routes):
        app.include_router(prompt_library.router)


def test_save_list_use_and_delete(client):
    _mount()
    r = client.post("/api/prompt-library", json={"kind": "image", "text": "  Close-up of the serum bottle on wet stone, soft daylight  ", "source_board_id": 7})
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["title"] == "Close-up of the serum bottle on wet stone,…" and row["uses"] == 0 and row["source_board_id"] == 7
    # Same text again → the same row, not a duplicate.
    again = client.post("/api/prompt-library", json={"kind": "image", "text": "Close-up of the serum bottle on wet stone, soft daylight"})
    assert again.status_code == 201 and again.json()["id"] == row["id"]
    client.post("/api/prompt-library", json={"kind": "narration", "text": "Mọi người ơi, hôm nay mình thử serum này nha", "title": "Mở đầu serum"})
    client.post("/api/prompt-library", json={"kind": "video", "text": "slow push-in, hands turn the bottle"})

    assert [p["kind"] for p in client.get("/api/prompt-library").json()] == ["image", "narration", "video"] or len(client.get("/api/prompt-library").json()) == 3
    assert [p["id"] for p in client.get("/api/prompt-library?kind=image").json()] == [row["id"]]
    assert client.get("/api/prompt-library?q=serum").json().__len__() == 2
    assert client.get("/api/prompt-library?kind=nope").status_code == 400
    assert client.post("/api/prompt-library", json={"kind": "image", "text": "   "}).status_code in (400, 422)

    used = client.post(f"/api/prompt-library/{row['id']}/use").json()
    assert used["uses"] == 1
    # Most used first.
    assert client.get("/api/prompt-library").json()[0]["id"] == row["id"]

    patched = client.patch(f"/api/prompt-library/{row['id']}", json={"title": "Serum trên đá", "tags": ["serum", " mỹ phẩm "]}).json()
    assert patched["title"] == "Serum trên đá" and patched["tags"] == ["serum", "mỹ phẩm"]
    assert client.delete(f"/api/prompt-library/{row['id']}").status_code == 204
    assert client.delete(f"/api/prompt-library/{row['id']}").status_code == 404
    assert client.post("/api/prompt-library/999999/use").status_code == 404


def test_saving_the_same_text_again_adds_the_new_labels(client):
    first = client.post("/api/prompt-library", json={"kind": "image", "text": "a red dress on a model", "tags": ["thời trang"]}).json()
    again = client.post("/api/prompt-library", json={"kind": "image", "text": "a red dress on a model", "tags": ["thời trang", "hook"]})
    assert again.json()["id"] == first["id"]
    assert again.json()["tags"] == ["thời trang", "hook"]
    assert len(client.get("/api/prompt-library?kind=image").json()) == 1
    # labels are edited on the page with PATCH
    r = client.patch(f"/api/prompt-library/{first['id']}", json={"tags": ["mọi ngành", "chốt đơn"]})
    assert r.json()["tags"] == ["mọi ngành", "chốt đơn"]
