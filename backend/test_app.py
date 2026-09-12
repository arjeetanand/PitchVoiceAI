import io
import wave

from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient

import app
from routes import pitch as pitch_routes


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


def test_markdown_upload_accepts_generic_content_type() -> None:
    response = client.post(
        "/api/pitch/file",
        files={"file": ("pitch.md", b"# The pitch\nIt helps teams rehearse demos.", "application/octet-stream")},
    )

    assert response.status_code == 200
    assert "rehearse demos" in client.get("/api/pitch").json()["text"]


def test_unsupported_file_type_is_rejected() -> None:
    response = client.post(
        "/api/pitch/file",
        files={"file": ("pitch.zip", b"not a pitch", "application/zip")},
    )

    assert response.status_code == 415


def test_speak_requires_provider_configuration(monkeypatch) -> None:
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    monkeypatch.delenv("HUGGINGFACE_API_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("HUGGINGFACE_TTS_MODE", "api")

    response = client.post("/api/voice/speak", json={"text": "Read this pitch."})

    assert response.status_code == 503


def _wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 16)
    return buffer.getvalue()


def test_sarvam_speech_response_advertises_wav(monkeypatch) -> None:
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    monkeypatch.setattr(pitch_routes, "_sarvam_audio", lambda text: _wav_bytes())

    response = client.post("/api/voice/speak", json={"text": "Read this pitch."})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content.startswith(b"RIFF")


def test_openai_is_used_when_local_huggingface_tts_is_unavailable(monkeypatch) -> None:
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    monkeypatch.delenv("HUGGINGFACE_API_TOKEN", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("HUGGINGFACE_TTS_MODE", "local")
    monkeypatch.setattr(
        pitch_routes,
        "_local_huggingface_audio",
        lambda text: (_ for _ in ()).throw(RuntimeError("local provider unavailable")),
    )
    monkeypatch.setattr(pitch_routes, "_openai_audio", lambda text, voice: b"ID3-test-audio")

    response = client.post("/api/voice/speak", json={"text": "Read this pitch."})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert response.content == b"ID3-test-audio"


def test_invalid_huggingface_transcription_response_is_a_service_error(monkeypatch) -> None:
    monkeypatch.setenv("HUGGINGFACE_API_TOKEN", "test-token")
    monkeypatch.setattr(pitch_routes, "_huggingface_request", lambda model, payload, content_type: b"not-json")

    response = client.post(
        "/api/voice/transcribe",
        files={"file": ("question.wav", b"RIFF", "audio/wav")},
    )

    assert response.status_code == 503
    assert "invalid transcription" in response.json()["detail"]


def test_huggingface_text_accepts_object_response(monkeypatch) -> None:
    monkeypatch.setenv("HUGGINGFACE_API_TOKEN", "test-token")
    monkeypatch.setattr(
        pitch_routes,
        "_huggingface_request",
        lambda model, payload, content_type: b'{"generated_text":"A concise answer."}',
    )

    assert pitch_routes._huggingface_text("What is it?", ["It is a pitch assistant."]) == "A concise answer."


def test_huggingface_timeout_is_a_service_error(monkeypatch) -> None:
    monkeypatch.setenv("HUGGINGFACE_API_TOKEN", "test-token")
    monkeypatch.setattr(
        pitch_routes.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()),
    )

    response = client.post(
        "/api/voice/transcribe",
        files={"file": ("question.wav", b"RIFF", "audio/wav")},
    )

    assert response.status_code == 503
    assert "could not be reached" in response.json()["detail"]
