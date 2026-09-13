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
- `POST /api/pitch/read` returns audio for the loaded pitch. Sarvam, Piper, local Hugging Face, and Hugging Face API output WAV; OpenAI output is MP3.
- `POST /api/voice/speak` accepts `{ "text": "...", "voice": "alloy" }` and returns audio with the correct `Content-Type`.
- `POST /api/voice/transcribe` accepts a supported recorded audio file up to `MAX_AUDIO_BYTES` and returns a Hugging Face Whisper transcription.

For a completely free neural voice, run Piper locally and point `PIPER_TTS_URL` at it:

```bash
python -m pip install "piper-tts[http]"
python -m piper.download_voices en_US-lessac-medium
python -m piper.http_server -m en_US-lessac-medium --host 127.0.0.1 --port 5000
```

Then set `TTS_PROVIDER=piper` and `PIPER_TTS_URL=http://127.0.0.1:5000/synthesize`. Piper is local and does not require a provider key; voice models have their own licenses, so check the selected model before shipping.

Set `TTS_PROVIDER=auto` with `SARVAM_API_KEY` to use Sarvam Bulbul for speech output. In `auto` mode, Sarvam is tried first, then configured local Piper, Hugging Face, or OpenAI providers. The default `TTS_PROVIDER=browser` keeps the demo free: the shipped browser room uses its built-in SpeechSynthesis voice when no server TTS is selected, so a presentation can speak without Sarvam. Hugging Face Whisper handles speech-to-text. Source-grounded extractive answers are the default; set `ANSWER_GENERATION_PROVIDER=huggingface` only to opt into hosted answer generation. Without provider keys, extractive Q&A still works and the browser handles reply speech locally.

The repository root `.env` is loaded automatically when the backend starts. Fill in `HUGGINGFACE_API_TOKEN` there before using voice conversations. `FRONTEND_ORIGINS` is only needed if a separate frontend origin will call the API; the shipped live room uses the same origin. Use a non-sensitive demo source because configured providers receive audio and text needed to process a voice turn.

## Tests

```powershell
python -m pytest -q
```
