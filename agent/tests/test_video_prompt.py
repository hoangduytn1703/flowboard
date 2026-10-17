from flowboard.services.video_prompt import REALTIME_CLAUSE, ensure_realtime, mentions_speed


def test_realtime_clause_is_appended_by_default():
    out = ensure_realtime("0-3s: the model smiles. 3-6s: she waves.")
    assert out.endswith(REALTIME_CLAUSE)
    assert out.startswith("0-3s: the model smiles.")


def test_explicit_speed_requests_are_left_alone():
    for prompt in (
        "hair flying in slow motion",
        "a dramatic slow-mo splash",
        "slomo water drops",
        "a time-lapse of the sunset",
        "played at 2x speed",
        "speed ramp into the turn",
    ):
        assert mentions_speed(prompt)
        assert ensure_realtime(prompt) == prompt


def test_idempotent_and_empty_safe():
    once = ensure_realtime("the model turns")
    assert ensure_realtime(once) == once
    assert ensure_realtime("   ") == ""
    assert "slowly" not in REALTIME_CLAUSE  # "slowly" in a prompt is fine; only effects count
    assert not mentions_speed("fingers slowly run along the fabric")
