"""The AI writes a product's English description when the seller left it empty or typed Vietnamese."""
from __future__ import annotations

import pytest

from flowboard.services import product_describe
from flowboard.services.llm import LLMError


@pytest.fixture()
def ai(monkeypatch):
    box = {"answer": "a grey work jacket with two small built-in fans at the lower back", "asked": []}

    async def run_llm(feature, prompt, **kw):
        box["asked"].append(prompt)
        if isinstance(box["answer"], Exception):
            raise box["answer"]
        return box["answer"]

    import flowboard.services.llm as llm
    monkeypatch.setattr(llm, "run_llm", run_llm)
    return box


def test_an_empty_description_is_written_from_what_the_seller_gave(client, ai):
    made = client.post("/api/products", json={"name": "Áo điều hoà có quạt", "category": "fashion",
                                              "selling_points": "2 quạt sau lưng\nPin 8 tiếng"}).json()
    got = client.get(f"/api/products/{made['id']}").json()
    assert got["description"].startswith("a grey work jacket") and "Pin 8 tiếng" in ai["asked"][0]
    # an English one is the seller's: not touched, the AI is not asked
    client.patch(f"/api/products/{made['id']}", json={"description": "a blue jacket"})
    assert client.get(f"/api/products/{made['id']}").json()["description"] == "a blue jacket" and len(ai["asked"]) == 1


def test_vietnamese_typed_in_the_field_is_turned_into_english(client, ai):
    made = client.post("/api/products", json={"name": "Cơm cháy", "description": "cơm cháy giòn rắc chà bông"}).json()
    assert "cơm cháy giòn" in ai["asked"][0]
    assert client.get(f"/api/products/{made['id']}").json()["description"].startswith("a grey work jacket")


def test_no_ai_or_a_strange_answer_leaves_the_product_alone(client, ai):
    ai["answer"] = LLMError("no provider")
    made = client.post("/api/products", json={"name": "Ốp lưng"}).json()
    assert client.get(f"/api/products/{made['id']}").json()["description"] == ""
    for bad in ('{"description": "x"}', "Xin lỗi, tôi không thể", "word " * 80, "ok"):
        ai["answer"] = bad
        client.patch(f"/api/products/{made['id']}", json={"price": "99k"})
        assert client.get(f"/api/products/{made['id']}").json()["description"] == ""
    assert product_describe.clean('"A white mug with a bamboo lid."') == "A white mug with a bamboo lid"
    assert product_describe.is_vietnamese("áo thun") and not product_describe.is_vietnamese("cotton t-shirt, 100%")
