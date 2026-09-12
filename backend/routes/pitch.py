from __future__ import annotations

import json
import io
import base64
import os
import re
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Any

import pymupdf
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field


BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DOCUMENT = BACKEND_DIR / "data" / "pitch.txt"
STOP_WORDS = {
    "a", "an", "and", "are", "does", "how", "in", "is", "it", "of",
    "the", "to", "what", "when", "where", "who", "why",
}
router = APIRouter()


def _setting(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


class DocumentStore:
    def __init__(self, path: Path = DEFAULT_DOCUMENT) -> None:
        self.path = path
        self.text = ""
        self.source = str(path)
        self.load()

    def load(self) -> str:
        if self.path.exists():
            self.text = self.path.read_text(encoding="utf-8").strip()
        else:
            self.text = ""
        return self.text

    def replace(self, text: str, source: str = "uploaded document") -> None:
        normalized = re.sub(r"\s+", " ", text).strip()
        max_chars = int(_setting("MAX_DOCUMENT_CHARS", "50000"))
        if not normalized:
            raise ValueError("The document must contain text.")
        if len(normalized) > max_chars:
            raise ValueError(f"The document exceeds the {max_chars} character limit.")
        self.text = normalized
        self.source = source

    def chunks(self) -> list[str]:
        return [chunk.strip() for chunk in re.split(r"(?<=[.!?])\s+", self.text) if chunk.strip()]


class QuestionRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)


class DocumentRequest(BaseModel):
    document: str = Field(min_length=1, max_length=50000)


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    voice: str | None = Field(default=None, max_length=40)


store = DocumentStore(Path(_setting("PITCH_DOCUMENT_PATH", str(DEFAULT_DOCUMENT))))


def _relevant_chunks(question: str, chunks: list[str]) -> list[str]:
    words = {
        word.lower()
        for word in re.findall(r"[a-zA-Z0-9']+", question)
        if len(word) > 2 and word.lower() not in STOP_WORDS
    }
    scored = sorted(
        ((sum(word in chunk.lower() for word in words), index, chunk) for index, chunk in enumerate(chunks)),
        key=lambda item: (-item[0], item[1]),
    )
    return [chunk for score, _, chunk in scored[:4] if score > 0]


def _huggingface_request(model: str, payload: bytes, content_type: str) -> bytes:
    token = _setting("HUGGINGFACE_API_TOKEN", "")
    if not token:
        raise RuntimeError("HUGGINGFACE_API_TOKEN is not configured")
    url = _setting("HUGGINGFACE_BASE_URL", "https://router.huggingface.co/hf-inference") + f"/models/{model}"
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": content_type},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Hugging Face inference failed: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("The Hugging Face inference service could not be reached.") from exc


def _huggingface_text(question: str, context: list[str]) -> str:
    model = _setting("HUGGINGFACE_TEXT_MODEL", "Qwen/Qwen2.5-7B-Instruct")
    prompt = (
        "You are a pitch assistant. Answer only from the supplied pitch context. "
        "If the context does not answer the question, say exactly that the pitch document does not provide enough information.\n\n"
        f"PITCH CONTEXT:\n{' '.join(context)}\n\nQUESTION:\n{question}\n\nANSWER:"
    )
    result = json.loads(_huggingface_request(model, json.dumps({"inputs": prompt, "parameters": {"max_new_tokens": 180, "return_full_text": False}}).encode(), "application/json"))
    if isinstance(result, list) and result and "generated_text" in result[0]:
        return result[0]["generated_text"].strip()
    raise RuntimeError("Hugging Face returned an unexpected text response.")


def _answer_with_provider(question: str, context: list[str]) -> tuple[str, str]:
    if not _setting("HUGGINGFACE_API_TOKEN", ""):
        raise RuntimeError("HUGGINGFACE_API_TOKEN is not configured")
    return _huggingface_text(question, context), "huggingface"


def _fallback_answer(context: list[str]) -> str:
    if not context:
        return "I could not find that in the pitch document."
    return "According to the pitch document: " + " ".join(context)


def _openai_audio(text: str, voice: str) -> bytes:
    url = _setting("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/audio/speech"
    request = urllib.request.Request(
        url,
        data=json.dumps({"model": _setting("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"), "voice": voice, "input": text, "response_format": "mp3"}).encode("utf-8"),
        headers={"Authorization": f"Bearer {_setting('OPENAI_API_KEY', '')}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError("The text-to-speech provider could not be reached.") from exc


def _huggingface_audio(text: str) -> bytes:
    model = _setting("HUGGINGFACE_TTS_MODEL", "facebook/mms-tts-eng")
    return _huggingface_request(model, json.dumps({"inputs": text}).encode(), "application/json")


def _sarvam_audio(text: str) -> bytes:
    api_key = _setting("SARVAM_API_KEY", "")
    if not api_key:
        raise RuntimeError("SARVAM_API_KEY is not configured")
    chunks = [text[index:index + 2500] for index in range(0, len(text), 2500)]
    audio_parts: list[bytes] = []
    for chunk in chunks:
        payload = {
            "text": chunk,
            "target_language_code": _setting("SARVAM_LANGUAGE_CODE", "en-IN"),
            "speaker": _setting("SARVAM_SPEAKER", "shubh"),
            "model": _setting("SARVAM_TTS_MODEL", "bulbul:v3"),
            "speech_sample_rate": 24000,
            "output_audio_codec": "wav",
        }
        request = urllib.request.Request(
            "https://api.sarvam.ai/text-to-speech",
            data=json.dumps(payload).encode("utf-8"),
            headers={"api-subscription-key": api_key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                result = json.loads(response.read().decode("utf-8"))
                audio_parts.append(base64.b64decode(result["audios"][0]))
        except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, KeyError, ValueError) as exc:
            raise RuntimeError("Sarvam text-to-speech failed. Check SARVAM_API_KEY and voice settings.") from exc

    if len(audio_parts) == 1:
        return audio_parts[0]
    output = io.BytesIO()
    with wave.open(io.BytesIO(audio_parts[0]), "rb") as first:
        params = first.getparams()
        frames = [first.readframes(first.getnframes())]
    for part in audio_parts[1:]:
        with wave.open(io.BytesIO(part), "rb") as current:
            frames.append(current.readframes(current.getnframes()))
    with wave.open(output, "wb") as combined:
        combined.setparams(params)
        combined.writeframes(b"".join(frames))
    return output.getvalue()


def _local_huggingface_audio(text: str) -> bytes:
    try:
        import numpy as np
        import torch
        from scipy.io import wavfile
        from transformers import AutoProcessor, AutoTokenizer, BarkModel, VitsModel
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            "Local Hugging Face TTS dependencies are unavailable or PyTorch is corrupted. "
            "Reinstall CPU-only PyTorch, then install backend requirements.txt."
        ) from exc

    model_name = _setting("HUGGINGFACE_TTS_MODEL", "facebook/mms-tts-eng")
    if model_name.lower().startswith("suno/bark"):
        processor = AutoProcessor.from_pretrained(model_name)
        model = BarkModel.from_pretrained(model_name)
        inputs = processor(
            text,
            voice_preset=_setting("HUGGINGFACE_TTS_VOICE", "v2/en_speaker_6"),
            return_tensors="pt",
        )
        with torch.no_grad():
            waveform = model.generate(**inputs)
        sample_rate = model.generation_config.sample_rate
    else:
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = VitsModel.from_pretrained(model_name)
        inputs = tokenizer(text, return_tensors="pt")
        with torch.no_grad():
            waveform = model(**inputs).waveform
        sample_rate = model.config.sampling_rate
    audio = waveform.squeeze().cpu().numpy()
    audio = np.clip(audio, -1, 1)
    buffer = io.BytesIO()
    wavfile.write(buffer, sample_rate, (audio * 32767).astype(np.int16))
    return buffer.getvalue()


def _huggingface_transcription(audio: bytes, content_type: str) -> str:
    model = _setting("HUGGINGFACE_ASR_MODEL", "openai/whisper-large-v3-turbo")
    result = json.loads(_huggingface_request(model, audio, content_type))
    text = result.get("text", "").strip()
    if not text:
        raise RuntimeError("Hugging Face did not detect speech in the recording.")
    return text


def _speech_audio(text: str, voice: str | None = None) -> bytes:
    if _setting("SARVAM_API_KEY", ""):
        return _sarvam_audio(text)
    if _setting("HUGGINGFACE_TTS_MODE", "local") == "local":
        return _local_huggingface_audio(text)
    if _setting("HUGGINGFACE_API_TOKEN", ""):
        return _huggingface_audio(text)
    if _setting("OPENAI_API_KEY", ""):
        return _openai_audio(text, voice or _setting("OPENAI_TTS_VOICE", "alloy"))
    raise RuntimeError(
        "No speech provider is configured. Set HUGGINGFACE_API_TOKEN in .env."
    )


def _speech_media_type() -> str:
    if _setting("SARVAM_API_KEY", "") or (_setting("HUGGINGFACE_TTS_MODE", "local") == "local"):
        return "audio/wav"
    return "audio/mpeg"


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "document_loaded": bool(store.text),
        "document_source": store.source,
        "huggingface_configured": bool(_setting("HUGGINGFACE_API_TOKEN", "")),
        "sarvam_configured": bool(_setting("SARVAM_API_KEY", "")),
    }


@router.get("/api/pitch")
def get_pitch() -> dict[str, Any]:
    if not store.text:
        raise HTTPException(status_code=404, detail="No pitch document has been loaded.")
    return {"source": store.source, "text": store.text, "chunks": store.chunks()}


@router.post("/api/pitch/document")
def upload_document(request: DocumentRequest) -> dict[str, Any]:
    try:
        store.replace(request.document, "request body")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"source": store.source, "characters": len(store.text), "chunks": len(store.chunks())}


@router.post("/api/pitch/file")
async def upload_pitch_file(file: UploadFile = File(...)) -> dict[str, Any]:
    accepted_types = {"text/plain", "text/markdown", "application/octet-stream", "application/pdf"}
    if file.content_type not in accepted_types:
        raise HTTPException(status_code=415, detail="Upload a PDF, plain-text, or Markdown document.")
    raw = await file.read()
    try:
        if file.content_type == "application/pdf" or (file.filename or "").lower().endswith(".pdf"):
            with pymupdf.open(stream=raw, filetype="pdf") as document:
                text = "\n".join(page.get_text("text") for page in document)
        else:
            text = raw.decode("utf-8")
        store.replace(text, file.filename or "uploaded document")
    except (UnicodeDecodeError, ValueError, pymupdf.FileDataError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"source": store.source, "characters": len(store.text), "chunks": len(store.chunks())}


@router.post("/api/voice/answer")
def answer_question(request: QuestionRequest) -> dict[str, Any]:
    if not store.text:
        raise HTTPException(status_code=404, detail="No pitch document has been loaded.")
    context = _relevant_chunks(request.question, store.chunks())
    try:
        answer, provider = _answer_with_provider(request.question, context) if context else (_fallback_answer(context), "extractive")
    except RuntimeError:
        answer = _fallback_answer(context)
        provider = "extractive"
    return {"question": request.question, "answer": answer, "grounded": bool(context), "provider": provider, "sources": context}


@router.post("/api/voice/transcribe")
async def transcribe_audio(file: UploadFile = File(...)) -> dict[str, str]:
    if not _setting("HUGGINGFACE_API_TOKEN", ""):
        raise HTTPException(status_code=503, detail="Set HUGGINGFACE_API_TOKEN in .env to transcribe audio.")
    try:
        text = _huggingface_transcription(await file.read(), file.content_type or "audio/wav")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"text": text, "provider": "huggingface"}


@router.post("/api/voice/speak")
def speak(request: SpeakRequest) -> Response:
    try:
        audio = _speech_audio(request.text, request.voice)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=audio, media_type=_speech_media_type())


@router.post("/api/pitch/read")
def read_pitch() -> Response:
    if not store.text:
        raise HTTPException(status_code=404, detail="No pitch document has been loaded.")
    try:
        audio = _speech_audio(store.text)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=audio, media_type=_speech_media_type())
