import json
from fastapi.testclient import TestClient

from server.app import app

client = TestClient(app)


def _payload(model: str = "openai/gpt-oss-20b"):
    return {
        "subject": "Kvóta teszt",
        "params": {
            "model": model,
            "temperature": 0.1,
            "top_p": 1.0,
            "max_tokens": 8000,
            "language": "hu",
            "include_intro": False,
            "include_conclusion": False,
            "depth": 2,
        },
    }


def _mock_structure(monkeypatch):
    from server.services import llm_service

    def fake_generate(subject, params, client=None):
        return (
            {
                "model_name": params.model,
                "input_time": 0.0,
                "output_time": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_time": 0.0,
            },
            {"Fejezet": "Leírás"},
        )

    monkeypatch.setattr(llm_service, "generate_book_structure_service", fake_generate)


def test_quota_decrements_and_limits(monkeypatch):
    _mock_structure(monkeypatch)

    token = "TESTKEY_QUOTA_A"
    headers = {"Authorization": f"Bearer {token}"}

    # Initial state: should be 3 remaining
    r = client.get("/api/quota", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["per_day"] >= 3
    start_remaining = data["remaining"]
    # We assume default is 3, but if env differs, still enforce limit behavior

    # 1st attempt
    r = client.post("/api/structure", json=_payload(), headers=headers)
    assert r.status_code == 200
    r = client.get("/api/quota", headers=headers)
    assert r.status_code == 200
    rem1 = r.json()["remaining"]
    assert rem1 == max(0, start_remaining - 1)

    # 2nd attempt
    r = client.post("/api/structure", json=_payload(), headers=headers)
    assert r.status_code == 200
    r = client.get("/api/quota", headers=headers)
    assert r.status_code == 200
    rem2 = r.json()["remaining"]
    assert rem2 == max(0, start_remaining - 2)

    # 3rd attempt
    r = client.post("/api/structure", json=_payload(), headers=headers)
    assert r.status_code == 200
    r = client.get("/api/quota", headers=headers)
    assert r.status_code == 200
    rem3 = r.json()["remaining"]
    assert rem3 == max(0, start_remaining - 3)

    # 4th attempt should be blocked with 429
    r = client.post("/api/structure", json=_payload(), headers=headers)
    assert r.status_code == 429

    # Ensure quota doesn't go negative
    r = client.get("/api/quota", headers=headers)
    assert r.status_code == 200
    assert r.json()["remaining"] >= 0


def test_quota_isolated_per_token(monkeypatch):
    _mock_structure(monkeypatch)

    token_a = "TESTKEY_QUOTA_B1"
    token_b = "TESTKEY_QUOTA_B2"
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Consume 1 for A
    r = client.post("/api/structure", json=_payload(), headers=headers_a)
    assert r.status_code == 200

    # Check B remains unaffected
    r = client.get("/api/quota", headers=headers_b)
    assert r.status_code == 200
    d_b = r.json()
    assert d_b["remaining"] == d_b["per_day"]

    # A should have one fewer than B
    r = client.get("/api/quota", headers=headers_a)
    assert r.status_code == 200
    d_a = r.json()
    assert d_a["remaining"] == max(0, d_a["per_day"] - 1)
