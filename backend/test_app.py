from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient

import app


client = TestClient(app.app)


def setup_function() -> None:
    app.store.path = Path("missing-pitch.txt")
    app.store.text = ""
    app.store.source = "test"


def test_document_upload_and_grounded_answer() -> None:
    upload = client.post(
        "/api/pitch/document",
        json={"document": "The product helps founders prepare for investor meetings."},
    )
    assert upload.status_code == 200

    response = client.post("/api/voice/answer", json={"question": "Who does the product help?"})

    assert response.status_code == 200
    assert response.json()["grounded"] is True
    assert "founders" in response.json()["answer"]


def test_answer_declines_unknown_question() -> None:
    client.post("/api/pitch/document", json={"document": "The product helps founders prepare for investor meetings."})

    response = client.post("/api/voice/answer", json={"question": "What is the launch date?"})

    assert response.status_code == 200
    assert response.json()["grounded"] is False
    assert "could not find" in response.json()["answer"]


def test_pdf_upload_extracts_text() -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "The pitch supports customer demos.")
    pdf_bytes = document.tobytes()
    document.close()

    response = client.post(
        "/api/pitch/file",
        files={"file": ("pitch.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    pitch = client.get("/api/pitch").json()
    assert "customer demos" in pitch["text"]


def test_speak_requires_provider_configuration() -> None:
    response = client.post("/api/voice/speak", json={"text": "Read this pitch."})

    assert response.status_code == 503
