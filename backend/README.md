# Pitchroom AI backend

FastAPI service for reading an approved pitch document aloud and answering questions grounded in that document.

## Run locally

```powershell
cd backend
python -m pip install -r requirements.txt
$env:PITCH_DOCUMENT_PATH = ".\data\pitch.txt"
python -m uvicorn app:app --reload
```

For local MMS TTS, the requirements install a CPU-only PyTorch build on Linux and a compatible PyPI wheel on macOS/other local platforms:

```bash
python -m pip install -r requirements.txt
```

The API runs at `http://localhost:8000` when launched directly. The repository's `./run-dev.sh` starts the same FastAPI app at `http://127.0.0.1:8501` and also serves the presentation-ready live browser room at `/`. Interactive API documentation is available at `/docs`.

## Routes

- `GET /health` checks service and document state.
- `GET /api/pitch` returns the loaded pitch and sentence chunks.
- `POST /api/pitch/demo` restores the included Pitchroom demo brief.
- `POST /api/pitch/document` accepts `{ "document": "..." }`.
- `POST /api/pitch/file` accepts a PDF, plain-text, or Markdown upload. PDF text is extracted page by page with PyMuPDF.
- `POST /api/voice/answer` accepts `{ "question": "..." }` and returns a grounded answer plus source chunks. The frontend can send speech-to-text output here.
- `POST /api/pitch/read` returns audio for the loaded pitch. Sarvam, local Hugging Face, and Hugging Face API output WAV; OpenAI output is MP3.
- `POST /api/voice/speak` accepts `{ "text": "...", "voice": "alloy" }` and returns audio with the correct `Content-Type`.
- `POST /api/voice/transcribe` accepts a supported recorded audio file up to `MAX_AUDIO_BYTES` and returns a Hugging Face Whisper transcription.

Set `SARVAM_API_KEY` to use Sarvam Bulbul for speech output. Sarvam is preferred for TTS and handles long pitches in chunks; if it fails, configured Hugging Face and OpenAI providers are tried as fallbacks. Hugging Face Whisper handles speech-to-text. Source-grounded extractive answers are the default; set `ANSWER_GENERATION_PROVIDER=huggingface` only to opt into hosted answer generation. Without provider keys, extractive Q&A still works and speech routes return `503`.

The repository root `.env` is loaded automatically when the backend starts. Fill in `HUGGINGFACE_API_TOKEN` there before using voice conversations. `FRONTEND_ORIGINS` is only needed if a separate frontend origin will call the API; the shipped live room uses the same origin. Use a non-sensitive demo source because configured providers receive audio and text needed to process a voice turn.

## Tests

```powershell
python -m pytest -q
```
