# Pitchroom AI backend

FastAPI service for reading an approved pitch document aloud and answering questions grounded in that document.

## Run locally

```powershell
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload
```

Before starting, create the repository-root `.env` from [`.env.example`](../.env.example)
and set a long random `PITCHROOM_ACCESS_TOKEN`; the service fails closed while
it is empty. The browser uses HTTP Basic authentication with username
`presenter` and that shared token.

For local MMS TTS, the requirements install a CPU-only PyTorch build on Linux and a compatible PyPI wheel on macOS/other local platforms:

```bash
python -m pip install -r requirements.txt
```

The API runs at `http://localhost:8000` when launched directly. The repository's `./run-dev.sh` starts the same FastAPI app at `http://127.0.0.1:8501` and also serves the presentation-ready live browser room at `/`. Interactive API documentation is available at `/docs`.

## Routes

- `GET /health` is an anonymous status-only service check; it reports 503 until presenter authentication is configured.
- `GET /api/pitch` returns the loaded pitch, source sections, citations, and extraction metadata. All room and API routes require HTTP Basic authentication with username `presenter` and the `PITCHROOM_ACCESS_TOKEN` value.
- `POST /api/pitch/demo` restores the included Pitchroom demo brief.
- `POST /api/pitch/document` accepts `{ "document": "..." }`.
- `POST /api/pitch/file` accepts PPTX, selectable-text PDF, DOCX, plain-text, or Markdown uploads. PPTX text and speaker notes are extracted slide by slide; PDF text is extracted in a time-bounded worker with Linux CPU/memory limits; DOCX paragraphs are extracted from OOXML. Export legacy `.ppt` files as `.pptx` or PDF first.
- `POST /api/voice/answer` accepts `{ "question": "..." }` and returns a grounded answer, source chunks, and `source_refs` such as `Slide 4` or `Page 2`. The frontend can send speech-to-text output here.
- `POST /api/pitch/read` returns audio for the loaded pitch. Kokoro, Sarvam, Piper, local Hugging Face, and Hugging Face API output WAV; OpenAI output is MP3.
- `POST /api/voice/speak` accepts `{ "text": "...", "voice": "alloy" }` and returns audio with the correct `Content-Type`.
- `POST /api/voice/warm` warms the explicitly selected local Kokoro voice without invoking any hosted provider. The browser room calls this on load.
- `POST /api/voice/transcribe` accepts a supported recorded audio file up to `MAX_AUDIO_BYTES` and returns a Hugging Face Whisper transcription.

## Recommended local studio voice: Kokoro

Kokoro is the presentation-quality local English path. It uses the fixed official Apache-2.0 `hexgrad/Kokoro-82M` model, keeps answer text on the machine after its first download, and is selected only when `TTS_PROVIDER=kokoro` is set. It does not replace the browser fallback or call Sarvam.

```bash
python -m pip install -r requirements-kokoro.txt
# Optional but recommended for uncommon names and acronyms:
# macOS: brew install espeak-ng
# Ubuntu/Debian: sudo apt-get install espeak-ng
```

Set the following in the repository-root `.env`, then start the real FastAPI process before presenting:

```dotenv
TTS_PROVIDER=kokoro
KOKORO_LANG_CODE=a
KOKORO_VOICE=af_heart
KOKORO_SPEED=0.98
KOKORO_DEVICE=auto
```

The page asks `/api/voice/warm` to load the model and a short test phrase as soon as it opens, and repeated page loads return immediately once that server process is warm. The initial artifact download contacts Hugging Face but does not contain answer text; pre-cache it before an offline presentation. Wait for that first load (roughly 360 MB is cached locally), then run one text question and select **Play answer** before presenting. `af_bella` is the practical alternate narrator to audition. The answer path retains complete sentences up to 1,000 characters; synthesis keeps a separate 1,200-character hard guard. The browser buffers one WAV response rather than word-by-word streaming.

For this demo, use the curated pretrained narrator instead of a custom fine-tune. Fine-tuning needs a licensed, consented voice dataset plus evaluation time, and it does not remove model warm-up or response-generation latency.

For a smaller local neural fallback, run Piper and point `PIPER_TTS_URL` at it:

```bash
python -m pip install "piper-tts[http]"
python -m piper.download_voices en_US-lessac-medium
python -m piper.http_server -m en_US-lessac-medium --host 127.0.0.1 --port 5000
```

Then set `TTS_PROVIDER=piper` and `PIPER_TTS_URL=http://127.0.0.1:5000/synthesize`. Piper is local and does not require a provider key; voice models have their own licenses, so check the selected model before shipping.

Set `TTS_PROVIDER=auto` with `SARVAM_API_KEY` to use Sarvam Bulbul for speech output. In `auto` mode, Sarvam is tried first, then configured local Piper, Hugging Face, or OpenAI providers. Kokoro is intentionally excluded from `auto`, so the model is never downloaded unless it is explicitly chosen. The default `TTS_PROVIDER=browser` keeps the demo free: the shipped browser room uses its built-in SpeechSynthesis voice when no server TTS is selected, so a presentation can speak without Sarvam. Hugging Face Whisper handles speech-to-text. Source-grounded extractive answers are the default; set `ANSWER_GENERATION_PROVIDER=huggingface` only to opt into hosted answer generation. Without provider keys, extractive Q&A still works and the browser handles reply speech locally.

The repository-root `.env` is loaded automatically when the backend starts.
Use the categorized root [`.env.example`](../.env.example) as the only setup
reference. Set a long random `PITCHROOM_ACCESS_TOKEN` before starting the
service; an empty value fails closed. The browser asks for username `presenter`
and that shared password. Also set `HUGGINGFACE_API_TOKEN` before using
microphone transcription. Unsafe requests must come from an origin listed in
`FRONTEND_ORIGINS`; the shipped live room uses the same origin. Request bodies,
uploads, Office archive extraction, PDF pages, and document sections have
explicit size/count ceilings. Transcription is capped at 30 requests per hour
per process by default; this in-memory quota resets on restart and is not shared
across workers. One upload/transcription body is parsed at a time per process.
Use a non-sensitive demo source because configured providers receive audio and
text needed to process a voice turn.

Document ingestion is intentionally honest: embedded images, scanned pages, and
chart-only slides are counted and returned as review warnings. The current
retrieval path can answer from selectable text, tables, and speaker notes; add
OCR/vision extraction before claiming that arbitrary visual claims are covered.

## Tests

```powershell
python -m pytest -q
```
