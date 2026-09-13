from __future__ import annotations

import json
import io
import base64
import binascii
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
# Keep tokens lexical rather than possessive.  Treating "AI's" as one token
# can make a repeated product name look like evidence for an unsupported fact.
WORD_PATTERN = re.compile(r"[a-zA-Z0-9]+")
AUDIO_UPLOAD_EXTENSIONS = {
    ".aac", ".flac", ".m4a", ".mp3", ".mp4", ".mpeg", ".mpga",
    ".oga", ".ogg", ".wav", ".webm",
}
AUDIO_UPLOAD_VIDEO_TYPES = {"video/mp4", "video/webm"}
DEFAULT_MAX_AUDIO_BYTES = 10 * 1024 * 1024
router = APIRouter()


def _setting(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _document_path() -> Path:
    configured = Path(_setting("PITCH_DOCUMENT_PATH", str(DEFAULT_DOCUMENT))).expanduser()
    if configured.is_absolute():
        return configured
    for candidate in (Path.cwd() / configured, BACKEND_DIR / configured, BACKEND_DIR.parent / configured):
        if candidate.exists():
            return candidate.resolve()
    return Path.cwd() / configured


def _answer_generation_provider() -> str:
    """Return an explicitly enabled answer-generation provider, if any.

    The extractive answer is intentionally the default: it is fast, grounded in
    the uploaded pitch, and does not depend on a remote model during a demo.
    Set ANSWER_GENERATION_PROVIDER=huggingface to opt into generated answers.
    """
    configured = _setting("ANSWER_GENERATION_PROVIDER", "extractive").lower()
    return "huggingface" if configured in {"huggingface", "hf"} else "extractive"


def _audio_upload_limit() -> int:
    try:
        configured = int(_setting("MAX_AUDIO_BYTES", str(DEFAULT_MAX_AUDIO_BYTES)))
    except ValueError:
        return DEFAULT_MAX_AUDIO_BYTES
    return configured if configured > 0 else DEFAULT_MAX_AUDIO_BYTES


def _audio_content_type(file: UploadFile) -> str:
    return (file.content_type or "audio/wav").split(";", 1)[0].strip().lower() or "audio/wav"


def _is_supported_audio_upload(file: UploadFile) -> bool:
    content_type = _audio_content_type(file)
    extension = Path(file.filename or "").suffix.lower()
    return (
        content_type.startswith("audio/")
        or content_type in AUDIO_UPLOAD_VIDEO_TYPES
        or extension in AUDIO_UPLOAD_EXTENSIONS
    )


async def _read_limited_audio_upload(file: UploadFile, max_bytes: int) -> bytes:
    declared_size = getattr(file, "size", None)
    if isinstance(declared_size, int) and declared_size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Audio uploads must be at most {max_bytes:,} bytes.",
        )

    audio = bytearray()
    while True:
        # Read one extra byte beyond the remaining allowance so a streamed
        # upload cannot bypass the limit when its size metadata is absent.
        chunk_size = min(1024 * 1024, max_bytes - len(audio) + 1)
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        audio.extend(chunk)
        if len(audio) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Audio uploads must be at most {max_bytes:,} bytes.",
            )

    if not audio:
        raise HTTPException(status_code=400, detail="Upload a non-empty audio recording.")
    return bytes(audio)


class DocumentStore:
    def __init__(self, path: Path = DEFAULT_DOCUMENT) -> None:
        self.path = path
        self.text = ""
        # A source label is user-facing.  Keep it readable for a presenter and
        # avoid exposing a server filesystem path in the public live room.
        self.source = path.name or "approved source"
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


store = DocumentStore(_document_path())


def _relevant_chunks(question: str, chunks: list[str]) -> list[str]:
    question_words = {
        word.lower()
        for word in WORD_PATTERN.findall(question)
        if len(word) > 2 and word.lower() not in STOP_WORDS
    }
    if not question_words:
        return []

    chunk_words = [
        {word.lower() for word in WORD_PATTERN.findall(chunk) if len(word) > 2}
        for chunk in chunks
    ]
    document_frequency = {
        word: sum(word in words for words in chunk_words)
        for word in question_words
    }
    common_in_document = max(2, (len(chunks) + 1) // 2)
    distinctive_words = {
        word for word in question_words if document_frequency[word] < common_in_document
    }
    # A broad question such as "What is Pitchroom?" can legitimately contain
    # only common subject terms. Keep that case answerable, but never let a
    # repeated brand name make an unsupported specific claim appear grounded.
    words = distinctive_words or question_words
    scored = sorted(
        ((len(words.intersection(chunk_word_set)), index, chunk) for index, (chunk, chunk_word_set) in enumerate(zip(chunks, chunk_words))),
        key=lambda item: (-item[0], item[1]),
    )
    if not scored or scored[0][0] <= 0:
        return []

    # An extractive answer is read aloud during the demo. Keep the context
    # focused on the strongest evidence instead of stitching together every
    # loosely related sentence that shares one generic word.
    top_score = scored[0][0]
    minimum_score = max(1, (top_score * 3 + 4) // 5)  # ceiling(top_score * 0.6)
    return [chunk for score, _, chunk in scored[:4] if score >= minimum_score]


def _huggingface_request(model: str, payload: bytes, content_type: str) -> bytes:
    token = _setting("HUGGINGFACE_API_TOKEN", "")
    if not token:
        raise RuntimeError("HUGGINGFACE_API_TOKEN is not configured")
    base_url = _setting("HUGGINGFACE_BASE_URL", "https://router.huggingface.co/hf-inference").rstrip("/")
    url = f"{base_url}/models/{model}"
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
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("The Hugging Face inference service could not be reached.") from exc


def _decode_json(payload: bytes, error_message: str) -> Any:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(error_message) from exc


def _huggingface_text(question: str, context: list[str]) -> str:
    model = _setting("HUGGINGFACE_TEXT_MODEL", "Qwen/Qwen2.5-7B-Instruct")
    prompt = (
        "You are a pitch assistant. Answer only from the supplied pitch context. "
        "If the context does not answer the question, say exactly that the pitch document does not provide enough information.\n\n"
        f"PITCH CONTEXT:\n{' '.join(context)}\n\nQUESTION:\n{question}\n\nANSWER:"
    )
    result = _decode_json(
        _huggingface_request(
            model,
            json.dumps(
                {
                    "inputs": prompt,
                    "parameters": {"max_new_tokens": 180, "return_full_text": False},
                }
            ).encode(),
            "application/json",
        ),
        "Hugging Face returned an invalid text response.",
    )
    if isinstance(result, list) and result and isinstance(result[0], dict) and "generated_text" in result[0]:
        generated_text = result[0]["generated_text"]
        if isinstance(generated_text, str) and generated_text.strip():
            return generated_text.strip()
    if isinstance(result, dict) and isinstance(result.get("generated_text"), str) and result["generated_text"].strip():
        return result["generated_text"].strip()
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(f"Hugging Face text generation failed: {result['error']}")
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
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"OpenAI text-to-speech failed: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
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
            "language_code": _setting("SARVAM_LANGUAGE_CODE", "en-IN"),
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
                result = _decode_json(response.read(), "Sarvam returned an invalid text-to-speech response.")
                encoded_audio = result["audios"][0]
                audio_parts.append(base64.b64decode(encoded_audio, validate=True))
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
            binascii.Error,
        ) as exc:
            raise RuntimeError("Sarvam text-to-speech failed. Check SARVAM_API_KEY and voice settings.") from exc

    if not audio_parts or not all(audio_parts):
        raise RuntimeError("Sarvam text-to-speech returned no audio.")
    if len(audio_parts) == 1:
        return audio_parts[0]
    output = io.BytesIO()
    try:
        with wave.open(io.BytesIO(audio_parts[0]), "rb") as first:
            params = first.getparams()
            frames = [first.readframes(first.getnframes())]
        for part in audio_parts[1:]:
            with wave.open(io.BytesIO(part), "rb") as current:
                current_params = current.getparams()
                if (current_params.nchannels, current_params.sampwidth, current_params.framerate, current_params.comptype, current_params.compname) != (
                    params.nchannels,
                    params.sampwidth,
                    params.framerate,
                    params.comptype,
                    params.compname,
                ):
                    raise RuntimeError("Sarvam returned incompatible audio chunks.")
                frames.append(current.readframes(current.getnframes()))
        with wave.open(output, "wb") as combined:
            combined.setparams(params._replace(nframes=0))
            combined.writeframes(b"".join(frames))
    except (wave.Error, EOFError) as exc:
        raise RuntimeError("Sarvam returned invalid WAV audio.") from exc
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

    try:
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
    except Exception as exc:
        raise RuntimeError("Local Hugging Face text-to-speech failed. Check the model and CPU dependencies.") from exc


def _huggingface_transcription(audio: bytes, content_type: str) -> str:
    model = _setting("HUGGINGFACE_ASR_MODEL", "openai/whisper-large-v3-turbo")
    result = _decode_json(
        _huggingface_request(model, audio, content_type),
        "Hugging Face returned an invalid transcription response.",
    )
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(f"Hugging Face transcription failed: {result['error']}")
    text = result.get("text", "").strip() if isinstance(result, dict) else ""
    if not text:
        raise RuntimeError("Hugging Face did not detect speech in the recording.")
    return text


def _speech_audio(text: str, voice: str | None = None) -> tuple[bytes, str]:
    errors: list[str] = []
    if _setting("SARVAM_API_KEY", ""):
        try:
            return _sarvam_audio(text), "audio/wav"
        except RuntimeError as exc:
            errors.append(f"Sarvam: {exc}")

    mode = _setting("HUGGINGFACE_TTS_MODE", "local").lower()
    if mode == "local":
        try:
            return _local_huggingface_audio(text), "audio/wav"
        except RuntimeError as exc:
            errors.append(f"Local Hugging Face: {exc}")

    if _setting("HUGGINGFACE_API_TOKEN", ""):
        try:
            media_type = _setting("HUGGINGFACE_TTS_MEDIA_TYPE", "audio/wav")
            return _huggingface_audio(text), media_type
        except RuntimeError as exc:
            errors.append(f"Hugging Face API: {exc}")

    if _setting("OPENAI_API_KEY", ""):
        try:
            return _openai_audio(text, voice or _setting("OPENAI_TTS_VOICE", "alloy")), "audio/mpeg"
        except RuntimeError as exc:
            errors.append(f"OpenAI: {exc}")

    if errors:
        raise RuntimeError("All configured text-to-speech providers failed: " + "; ".join(errors))

    raise RuntimeError(
        "No speech provider is configured. Set SARVAM_API_KEY, HUGGINGFACE_API_TOKEN, or OPENAI_API_KEY in .env."
    )


def _speech_provider() -> str:
    if _setting("SARVAM_API_KEY", ""):
        return "sarvam"
    if _setting("HUGGINGFACE_TTS_MODE", "local").lower() == "local":
        return "huggingface-local"
    if _setting("HUGGINGFACE_API_TOKEN", ""):
        return "huggingface-api"
    if _setting("OPENAI_API_KEY", ""):
        return "openai"
    return "none"


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "document_loaded": bool(store.text),
        "document_source": store.source,
        "huggingface_configured": bool(_setting("HUGGINGFACE_API_TOKEN", "")),
        "sarvam_configured": bool(_setting("SARVAM_API_KEY", "")),
        "openai_configured": bool(_setting("OPENAI_API_KEY", "")),
        "speech_provider": _speech_provider(),
    }


@router.get("/api/pitch")
def get_pitch() -> dict[str, Any]:
    if not store.text:
        raise HTTPException(status_code=404, detail="No pitch document has been loaded.")
    return {"source": store.source, "text": store.text, "chunks": store.chunks()}


@router.post("/api/pitch/demo")
def load_demo_pitch() -> dict[str, Any]:
    """Restore the included, non-sensitive Pitchroom demo brief.

    This gives a presenter a reliable one-click reset after experimenting with
    an uploaded source during rehearsal.
    """
    try:
        text = DEFAULT_DOCUMENT.read_text(encoding="utf-8")
        store.path = DEFAULT_DOCUMENT
        store.replace(text, DEFAULT_DOCUMENT.name)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="The included demo source could not be loaded.") from exc
    return {"source": store.source, "characters": len(store.text), "chunks": len(store.chunks())}


@router.post("/api/pitch/document")
def upload_document(request: DocumentRequest) -> dict[str, Any]:
    try:
        store.replace(request.document, "request body")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"source": store.source, "characters": len(store.text), "chunks": len(store.chunks())}


@router.post("/api/pitch/file")
async def upload_pitch_file(file: UploadFile = File(...)) -> dict[str, Any]:
    content_type = (file.content_type or "").lower()
    filename = (file.filename or "").lower()
    accepted_types = {"text/plain", "text/markdown", "text/x-markdown", "application/octet-stream", "application/pdf"}
    is_pdf = content_type == "application/pdf" or filename.endswith(".pdf")
    is_text = content_type in accepted_types - {"application/pdf"} or filename.endswith((".txt", ".md", ".markdown"))
    if not is_pdf and not is_text:
        raise HTTPException(status_code=415, detail="Upload a PDF, plain-text, or Markdown document.")
    raw = await file.read()
    try:
        if is_pdf:
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
    answer = _fallback_answer(context)
    provider = "extractive"
    if context and _answer_generation_provider() == "huggingface":
        try:
            answer, provider = _answer_with_provider(request.question, context)
        except RuntimeError:
            # A configured generation provider is an enhancement, not a reason
            # to make a source-grounded answer unavailable during a live demo.
            pass
    return {"question": request.question, "answer": answer, "grounded": bool(context), "provider": provider, "sources": context}


@router.post("/api/voice/transcribe")
async def transcribe_audio(file: UploadFile = File(...)) -> dict[str, str]:
    if not _is_supported_audio_upload(file):
        raise HTTPException(
            status_code=415,
            detail="Upload an audio recording (WAV, MP3, M4A, OGG, FLAC, AAC, or WebM).",
        )
    audio = await _read_limited_audio_upload(file, _audio_upload_limit())
    if not _setting("HUGGINGFACE_API_TOKEN", ""):
        raise HTTPException(status_code=503, detail="Set HUGGINGFACE_API_TOKEN in .env to transcribe audio.")
    try:
        text = _huggingface_transcription(audio, _audio_content_type(file))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"text": text, "provider": "huggingface"}


@router.post("/api/voice/speak")
def speak(request: SpeakRequest) -> Response:
    try:
        audio, media_type = _speech_audio(request.text, request.voice)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=audio, media_type=media_type)


@router.post("/api/pitch/read")
def read_pitch() -> Response:
    if not store.text:
        raise HTTPException(status_code=404, detail="No pitch document has been loaded.")
    try:
        audio, media_type = _speech_audio(store.text)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=audio, media_type=media_type)
