import json
from io import BytesIO
from typing import Iterator
from fastapi.testclient import TestClient

from server.app import app

client = TestClient(app)


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_structure_success(monkeypatch):
    from server.services import llm_service

    def fake_generate(subject, params):
        stats = {
            "model_name": "openai/gpt-oss-120b",
            "input_time": 0.1,
            "output_time": 0.2,
            "input_tokens": 10,
            "output_tokens": 20,
            "total_time": 0.3,
        }
        structure = {"Fejezet 1": "Leírás"}
        return stats, structure

    monkeypatch.setattr(llm_service, "generate_book_structure_service", fake_generate)

    payload = {
        "subject": "Teszt téma",
        "params": {
            "model": "openai/gpt-oss-120b",
            "temperature": 0.3,
            "top_p": 1.0,
            "max_tokens": 8000,
            "language": "hu",
            "include_intro": False,
            "include_conclusion": False,
            "depth": 2,
        },
    }
    r = client.post("/api/structure", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert "statistics" in body and "structure" in body
    assert body["structure"] == {"Fejezet 1": "Leírás"}


def test_structure_with_extra_instructions(monkeypatch):
    from server.services import llm_service

    captured = {}

    def fake_generate(subject, params):
        # Verify extra instructions forwarded
        captured["subject"] = subject
        captured["extra"] = params.extra_instructions
        stats = {
            "model_name": params.model,
            "input_time": 0.0,
            "output_time": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_time": 0.0,
        }
        structure = {"Fejezet 1": "Leírás"}
        return stats, structure

    monkeypatch.setattr(llm_service, "generate_book_structure_service", fake_generate)

    payload = {
        "subject": "Teszt téma",
        "params": {
            "model": "openai/gpt-oss-20b",
            "temperature": 0.3,
            "top_p": 1.0,
            "max_tokens": 8000,
            "language": "hu",
            "include_intro": False,
            "include_conclusion": False,
            "depth": 2,
            "extra_instructions": "Kötelező: hivatkozások\nKérdések: Mi, Hogyan?\nCél: oktatás",
        },
    }
    r = client.post("/api/structure", json=payload)
    assert r.status_code == 200
    assert captured["extra"] and "hivatkozások" in captured["extra"]


def test_sections_stream(monkeypatch):
    from server.services import llm_service

    def fake_iter(structure, params) -> Iterator[dict]:
        yield {"type": "section_start", "title": "Fejezet 1"}
        yield {"type": "token", "title": "Fejezet 1", "delta": "Első "}
        yield {"type": "token", "title": "Fejezet 1", "delta": "token"}
        yield {
            "type": "stats",
            "title": "Fejezet 1",
            "statistics": {
                "model_name": "openai/gpt-oss-20b",
                "input_time": 0.1,
                "output_time": 0.2,
                "input_tokens": 10,
                "output_tokens": 20,
                "total_time": 0.3,
            },
        }
        yield {"type": "section_end", "title": "Fejezet 1"}
        yield {"type": "done"}

    monkeypatch.setattr(llm_service, "iter_sections_stream", fake_iter)

    payload = {
        "structure": {"Fejezet 1": "Leírás"},
        "params": {
            "model": "openai/gpt-oss-20b",
            "temperature": 0.3,
            "top_p": 1.0,
            "max_tokens": 8000,
            "language": "hu",
            "style": "közérthető",
            "reading_level": "közép",
            "target_length": 1200,
            "parallelism": 1,
        },
    }

    with client.stream("POST", "/api/sections/stream", json=payload) as r:
        assert r.status_code == 200
        lines = [json.loads(line) for line in r.iter_lines() if line]

    # Order and types
    assert lines[0]["type"] == "section_start"
    assert lines[1]["type"] == "token"
    assert lines[2]["type"] == "token"
    assert lines[3]["type"] == "stats"
    assert lines[4]["type"] == "section_end"
    assert lines[-1]["type"] == "done"


def test_sections_stream_aborted(monkeypatch):
    from server.services import llm_service

    # Fake iterator that supports optional is_cancelled and yields an aborted event
    def fake_iter_cancel(structure, params, is_cancelled=None):
        yield {"type": "section_start", "title": "Fejezet 1"}
        # simulate early cancellation
        yield {"type": "aborted"}

    monkeypatch.setattr(llm_service, "iter_sections_stream", fake_iter_cancel)

    payload = {
        "structure": {"Fejezet 1": "Leírás"},
        "params": {
            "model": "openai/gpt-oss-20b",
            "temperature": 0.3,
            "top_p": 1.0,
            "max_tokens": 8000,
            "language": "hu",
            "style": "közérthető",
            "reading_level": "közép",
            "target_length": 1200,
            "parallelism": 1,
        },
    }

    with client.stream("POST", "/api/sections/stream", json=payload) as r:
        assert r.status_code == 200
        lines = [json.loads(line) for line in r.iter_lines() if line]

    assert lines[0]["type"] == "section_start"
    assert lines[-1]["type"] == "aborted"


def test_sections_stream_with_extra_instructions(monkeypatch):
    from server.services import llm_service

    seen = {"extra": None}

    def fake_iter(structure, params):
        seen["extra"] = params.extra_instructions
        yield {"type": "section_start", "title": "Fejezet 1"}
        yield {"type": "section_end", "title": "Fejezet 1"}
        yield {"type": "done"}

    monkeypatch.setattr(llm_service, "iter_sections_stream", fake_iter)

    payload = {
        "structure": {"Fejezet 1": "Leírás"},
        "params": {
            "model": "openai/gpt-oss-20b",
            "temperature": 0.3,
            "top_p": 1.0,
            "max_tokens": 8000,
            "language": "hu",
            "style": "közérthető",
            "reading_level": "közép",
            "target_length": 900,
            "parallelism": 1,
            "extra_instructions": "Kérlek sorolj fel esettanulmányokat is.",
        },
    }

    with client.stream("POST", "/api/sections/stream", json=payload) as r:
        assert r.status_code == 200
        lines = [json.loads(line) for line in r.iter_lines() if line]

    assert lines[-1]["type"] == "done"
    assert seen["extra"] and "esettanulmány" in seen["extra"]


def test_export_markdown(monkeypatch):
    # Avoid filesystem deps by relying on in-memory BytesIO
    r = client.post(
        "/api/export/markdown",
        json={"content": "Hello", "filename": "test_out"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert r.headers["content-disposition"].endswith("test_out.txt")
    assert r.content == b"Hello"


def test_export_pdf(monkeypatch):
    # Stub PDF to avoid OS-level lib issues in CI/local
    import server.routers.generation as generation

    def fake_pdf(content: str) -> BytesIO:
        return BytesIO(b"%PDF-1.4\n%stub")

    monkeypatch.setattr(generation, "create_pdf_file", fake_pdf)

    r = client.post(
        "/api/export/pdf",
        json={"content": "# Cím", "filename": "test_pdf"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.headers["content-disposition"].endswith("test_pdf.pdf")
    assert r.content.startswith(b"%PDF")
