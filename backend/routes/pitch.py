from __future__ import annotations

import json
import io
import base64
import binascii
import os
import re
import sys
import urllib.error
import urllib.request
import wave
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Any

import pymupdf
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from config import setting as _setting


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
KOKORO_SAMPLE_RATE = 24_000
KOKORO_MODEL_REPO = "hexgrad/Kokoro-82M"
MAX_KOKORO_TEXT_CHARS = 1_200
MAX_SPOKEN_ANSWER_CHARS = 1_000
KOKORO_WARMUP_TEXT = "Pitchroom is ready to answer the next presentation question clearly."
_kokoro_lock = RLock()
_kokoro_warmed: set[tuple[str, str, str, float, str]] = set()
router = APIRouter()


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


def _tts_provider_preference() -> str:
    """Return the requested speech path; browser voice is the safe default."""
    configured = _setting("TTS_PROVIDER", "browser").lower()
    aliases = {
        "web": "browser",
        "browser-native": "browser",
        "local-piper": "piper",
        "local-kokoro": "kokoro",
        "studio": "kokoro",
        "hf": "huggingface",
    }
    configured = aliases.get(configured, configured)
    return configured if configured in {"auto", "browser", "kokoro", "piper", "sarvam", "huggingface", "openai"} else "auto"


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


def _bounded_spoken_answer(answer: str) -> str:
    """Keep a live answer natural and inside the local studio-voice budget."""
    normalized = re.sub(r"\s+", " ", answer).strip()
    if len(normalized) <= MAX_SPOKEN_ANSWER_CHARS:
        return normalized

    complete_sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", normalized)
        if sentence.strip()
    ]
    selected: list[str] = []
    selected_length = 0
    for sentence in complete_sentences:
        candidate_length = selected_length + len(sentence) + (1 if selected else 0)
        if candidate_length > MAX_SPOKEN_ANSWER_CHARS:
            break
        selected.append(sentence)
        selected_length = candidate_length
    if selected:
        return " ".join(selected)

    # Avoid cutting a very long source sentence halfway through a claim. The
    # evidence remains visible in the UI, and a focused follow-up can select a
    # shorter source passage for the local presenter voice.
    return "The matching source passage is too long to read aloud in one reply. Please ask a more focused question."


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


def _piper_audio(text: str, voice: str | None = None) -> bytes:
    """Call an optional local Piper HTTP server; Piper itself is keyless."""
    url = _setting("PIPER_TTS_URL", "")
    if not url:
        raise RuntimeError("PIPER_TTS_URL is not configured")
    payload: dict[str, str] = {"text": text}
    configured_voice = voice or _setting("PIPER_TTS_VOICE", "")
    if configured_voice:
        payload["voice"] = configured_voice
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "audio/wav"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            audio = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Piper text-to-speech failed: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("The local Piper speech service could not be reached.") from exc
    if not audio:
        raise RuntimeError("Piper returned no audio.")
    return audio


def _kokoro_speed() -> float:
    """Return a deliberately conversational speed for the studio voice."""
    try:
        speed = float(_setting("KOKORO_SPEED", "0.98"))
    except ValueError as exc:
        raise RuntimeError("KOKORO_SPEED must be a number between 0.8 and 1.2.") from exc
    if not 0.8 <= speed <= 1.2:
        raise RuntimeError("KOKORO_SPEED must be between 0.8 and 1.2.")
    return speed


def _kokoro_device() -> str:
    """Choose the fastest safe local device without making it a requirement."""
    configured = _setting("KOKORO_DEVICE", "auto").lower()
    if configured in {"cpu", "cuda", "mps"}:
        if configured == "mps":
            # Kokoro requires this PyTorch fallback flag for its MPS path. It
            # lets unsupported operations fall back to CPU rather than making
            # the live demo fail on an Apple Silicon laptop.
            os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        return configured
    if configured != "auto":
        raise RuntimeError("KOKORO_DEVICE must be auto, cpu, cuda, or mps.")

    # PyTorch reads this compatibility flag while its MPS backend is imported.
    # Set it before importing torch, otherwise Kokoro can fail mid-synthesis on
    # an unsupported Apple-Silicon operator such as `aten::angle`.
    if sys.platform == "darwin":
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

    try:
        import torch
    except (ImportError, OSError):
        # The later Kokoro import produces the actionable installation error.
        return "cpu"

    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps and mps.is_available():
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        return "mps"
    return "cpu"


def _kokoro_options() -> tuple[str, str, str, float, str]:
    """Return the fully resolved, allowlisted local studio-voice settings."""
    return (
        _setting("KOKORO_LANG_CODE", "a").lower(),
        _setting("KOKORO_VOICE", "af_heart"),
        KOKORO_MODEL_REPO,
        _kokoro_speed(),
        _kokoro_device(),
    )


@lru_cache(maxsize=4)
def _kokoro_pipeline(lang_code: str, model_repo: str, device: str) -> Any:
    """Load the official Kokoro model once per configured local device."""
    try:
        from kokoro import KPipeline
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            "Kokoro local voice is unavailable. Install backend/requirements-kokoro.txt, "
            "then restart the app."
        ) from exc

    try:
        return KPipeline(lang_code=lang_code, repo_id=model_repo, device=device)
    except Exception as exc:
        raise RuntimeError(
            "Kokoro could not load its local English voice. Check the model download, "
            "KOKORO_DEVICE, and the optional espeak-ng install."
        ) from exc


def _kokoro_audio(text: str) -> bytes:
    """Synthesize a cached, local 24 kHz Kokoro WAV for a short live answer."""
    if len(text) > MAX_KOKORO_TEXT_CHARS:
        raise RuntimeError(
            f"Kokoro is optimized for live replies up to {MAX_KOKORO_TEXT_CHARS:,} characters. "
            "Ask a more focused question or use the browser voice for a full-document read."
        )
    return _kokoro_audio_with_options(text, _kokoro_options())


def _kokoro_audio_with_options(
    text: str,
    options: tuple[str, str, str, float, str],
) -> bytes:
    """Generate PCM with already-resolved local studio-voice settings."""
    lang_code, voice, model_repo, speed, device = options

    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("Kokoro local voice needs NumPy. Reinstall backend requirements.") from exc

    try:
        with _kokoro_lock:
            pipeline = _kokoro_pipeline(lang_code, model_repo, device)
            parts: list[Any] = []
            # Let Kokoro's English tokenizer keep a short answer in one
            # contextual phrase. It already splits at safe phoneme boundaries;
            # manually resetting on every sentence makes narration less fluid.
            for _, _, generated in pipeline(
                text,
                voice=voice,
                speed=speed,
                split_pattern=None,
            ):
                if generated is None:
                    continue
                if hasattr(generated, "detach"):
                    generated = generated.detach()
                if hasattr(generated, "cpu"):
                    generated = generated.cpu()
                samples = np.asarray(generated, dtype=np.float32).reshape(-1)
                if samples.size:
                    parts.append(samples)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(
            "Kokoro local voice could not synthesize this answer. Check the selected voice and pronunciation setup."
        ) from exc

    if not parts:
        raise RuntimeError("Kokoro local voice returned no audio.")

    audio = np.concatenate(parts)
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2", copy=False)
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(KOKORO_SAMPLE_RATE)
        wav_file.writeframes(pcm.tobytes())
    return output.getvalue()


def _warm_kokoro_voice() -> bool:
    """Warm each model/voice/device configuration once per server process."""
    options = _kokoro_options()
    with _kokoro_lock:
        if options in _kokoro_warmed:
            return False
        _kokoro_audio_with_options(KOKORO_WARMUP_TEXT, options)
        _kokoro_warmed.add(options)
    return True


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
    preference = _tts_provider_preference()
    if preference == "browser":
        raise RuntimeError("Browser voice is selected; the browser will synthesize this answer locally.")
    if preference == "kokoro":
        # Keep the studio voice deterministic and curated through KOKORO_VOICE
        # rather than accepting arbitrary model/voice downloads from requests.
        return _kokoro_audio(text), "audio/wav"
    if preference == "piper":
        return _piper_audio(text, voice), "audio/wav"

    errors: list[str] = []
    if _setting("SARVAM_API_KEY", ""):
        try:
            return _sarvam_audio(text), "audio/wav"
        except RuntimeError as exc:
            errors.append(f"Sarvam: {exc}")

    if _setting("PIPER_TTS_URL", ""):
        try:
            return _piper_audio(text, voice), "audio/wav"
        except RuntimeError as exc:
            errors.append(f"Piper: {exc}")

    mode = _setting("HUGGINGFACE_TTS_MODE", "off").lower()
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
        "No server speech provider is configured. Set TTS_PROVIDER=kokoro for the local studio voice, "
        "set PIPER_TTS_URL for local Piper, or configure a hosted provider."
    )


def _speech_provider() -> str:
    preference = _tts_provider_preference()
    if preference == "browser":
        return "browser"
    if preference == "kokoro":
        return "kokoro"
    if preference == "piper":
        return "piper" if _setting("PIPER_TTS_URL", "") else "piper-unconfigured"
    if _setting("SARVAM_API_KEY", ""):
        return "sarvam"
    if _setting("PIPER_TTS_URL", ""):
        return "piper"
    if _setting("HUGGINGFACE_TTS_MODE", "off").lower() == "local":
        return "huggingface-local"
    if _setting("HUGGINGFACE_API_TOKEN", ""):
        return "huggingface-api"
    if _setting("OPENAI_API_KEY", ""):
        return "openai"
    # The shipped browser room has a no-key SpeechSynthesis fallback even when
    # no server-side voice is configured.
    return "browser"


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "document_loaded": bool(store.text),
        "document_source": store.source,
        "huggingface_configured": bool(_setting("HUGGINGFACE_API_TOKEN", "")),
        "sarvam_configured": bool(_setting("SARVAM_API_KEY", "")),
        "kokoro_selected": _tts_provider_preference() == "kokoro",
        "piper_configured": bool(_setting("PIPER_TTS_URL", "")),
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
    answer = _bounded_spoken_answer(answer)
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


@router.post("/api/voice/warm")
def warm_voice() -> dict[str, Any]:
    """Warm only the explicitly selected local studio voice.

    The page calls this harmlessly during load, giving Kokoro time to load while
    a presenter grants microphone access or starts their first question. Remote
    providers are deliberately never invoked by this endpoint.
    """
    preference = _tts_provider_preference()
    if preference != "kokoro":
        return {"provider": _speech_provider(), "warmed": False, "ready": preference == "browser"}
    try:
        warmed = _warm_kokoro_voice()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"provider": "kokoro", "warmed": warmed, "ready": True}


@router.post("/api/pitch/read")
def read_pitch() -> Response:
    if not store.text:
        raise HTTPException(status_code=404, detail="No pitch document has been loaded.")
    try:
        audio, media_type = _speech_audio(store.text)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=audio, media_type=media_type)
