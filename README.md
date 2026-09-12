# PitchVoice AI

PitchVoice AI turns a pitch document into an interactive, voice-first experience. Upload a PDF, Markdown, or text pitch; listen to it; and ask questions by typing or speaking. Answers are grounded in the supplied source material.

## What it does

- Extracts text from PDF, Markdown, and plain-text pitch documents.
- Answers questions using relevant source sections, with a provider-free extractive fallback.
- Reads pitches and answers aloud using Sarvam, Hugging Face, or OpenAI text-to-speech.
- Transcribes spoken questions with Hugging Face Whisper.

## Project structure

```text
PitchVoiceAI/
├── backend/             # FastAPI API, document processing, Q&A, and voice routes
├── frontend/            # Streamlit user interface
├── docs/                # Architecture and operational documentation
├── run-dev.sh           # Local development launcher
├── render-start.sh      # Render production launcher
└── render.yaml          # Render service configuration
```

See [the architecture guide](docs/architecture.md) for component responsibilities and request flow.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt -r frontend/requirements.txt
cp backend/.env.example .env
./run-dev.sh
```

Open [http://127.0.0.1:8501](http://127.0.0.1:8501). Uploading and source-grounded extractive Q&A work without provider credentials. Configure provider keys in `.env` to enable speech features.

## Configuration

Copy `backend/.env.example` to the repository-root `.env` and fill in only the providers you use:

- `SARVAM_API_KEY` for the preferred Bulbul text-to-speech path.
- `HUGGINGFACE_API_TOKEN` for Whisper transcription and provider-backed answers.
- `OPENAI_API_KEY` for the OpenAI text-to-speech fallback.

Never commit `.env` or real API keys.

## Testing

```bash
.venv/bin/python -m pytest backend -q
```

## Deploying to Render

The included `render.yaml` runs FastAPI internally and exposes the Streamlit UI on Render's assigned `$PORT`.

```bash
bash render-start.sh
```

Set `HUGGINGFACE_API_TOKEN` and `SARVAM_API_KEY` as secret environment variables in the Render dashboard. Update the `FRONTEND_ORIGINS` value in `render.yaml` after choosing your Render service URL.
