# Pitch Voice Backend

FastAPI service for reading a shared pitch document aloud and answering questions grounded in that document.

## Run locally

```powershell
cd AIrtribeXRender\backend
python -m pip install -r requirements.txt
$env:PITCH_DOCUMENT_PATH = ".\data\pitch.txt"
python -m uvicorn app:app --reload
```

For local MMS TTS, the requirements install the CPU-only PyTorch build automatically:

```bash
python -m pip install -r requirements.txt
```

The API runs at `http://localhost:8000`. Interactive API documentation is available at `/docs`.

## Routes

- `GET /health` checks service and document state.
- `GET /api/pitch` returns the loaded pitch and sentence chunks.
- `POST /api/pitch/document` accepts `{ "document": "..." }`.
- `POST /api/pitch/file` accepts a PDF, plain-text, or Markdown upload. PDF text is extracted page by page with PyMuPDF.
- `POST /api/voice/answer` accepts `{ "question": "..." }` and returns a grounded answer plus source chunks. The frontend can send speech-to-text output here.
- `POST /api/pitch/read` returns MP3 audio for the loaded pitch.
- `POST /api/voice/speak` accepts `{ "text": "...", "voice": "alloy" }` and returns MP3 audio.
- `POST /api/voice/transcribe` accepts a recorded audio file and returns a Hugging Face Whisper transcription.

Set `SARVAM_API_KEY` to use Sarvam Bulbul for speech output. Sarvam is preferred for TTS and handles long pitches in chunks. Hugging Face remains responsible for speech-to-text and grounded answer generation, with local Hugging Face TTS as a fallback. Without provider keys, question answering uses a local extractive fallback and speech routes return `503`.

Set `FRONTEND_ORIGINS` to a comma-separated list of browser origins allowed to call the API. The repository root `.env` is loaded automatically when the backend starts. Fill in `HUGGINGFACE_API_TOKEN` there before using voice conversations.

## Tests

```powershell
python -m pytest -q
```
