"""Sample prompts shipped in prompt_seeds.json."""
from flowboard.services import prompt_seeds
from flowboard.services.tts import parse_speakers


def test_seed_file_follows_the_app_conventions():
    seeds = prompt_seeds.load_seeds()["prompts"]
    kinds = {p["kind"] for p in seeds}
    assert kinds == {"image", "video", "narration"}
    assert len({(p["kind"], p["text"]) for p in seeds}) == len(seeds)  # no duplicates
    for p in seeds:
        assert p["title"].strip() and p["text"].strip()
        if p["kind"] == "image":
            assert "reference photo" in p["text"] and "9:16" in p["text"]
        if p["kind"] == "video":
            assert "0-3s" in p["text"] and "6-8s" in p["text"]
        if p["kind"] == "narration":
            words = " ".join(seg for _, seg in parse_speakers(p["text"])).split()
            assert len(words) <= 24, p["title"]  # one 8 s clip


def test_seeded_once_per_version_and_restorable(client):
    first = prompt_seeds.seed_on_start()
    total = len(prompt_seeds.load_seeds()["prompts"])
    assert first == total
    items = client.get("/api/prompt-library").json()
    assert len(items) == total and all(prompt_seeds.SAMPLE_TAG in p["tags"] for p in items)

    # a sample the user deletes stays deleted on the next start
    victim = items[0]
    assert client.delete(f"/api/prompt-library/{victim['id']}").status_code == 204
    assert prompt_seeds.seed_on_start() == 0
    assert len(client.get("/api/prompt-library").json()) == total - 1

    # until they ask for the samples back
    r = client.post("/api/prompt-library/samples")
    assert r.status_code == 200 and r.json() == {"added": 1}
    assert client.post("/api/prompt-library/samples").json() == {"added": 0}
