# Architecture

PitchVoice AI uses a small two-service application that can be run together locally or under one Render web service.

```text
Streamlit UI (frontend/)
        |
        | HTTP
        v
FastAPI API (backend/)
        |
        +-- document extraction and in-memory source store
        +-- source-grounded Q&A
        +-- speech-to-text and text-to-speech providers
```

## Components

| Area | Responsibility |
| --- | --- |
| `frontend/` | Uploads documents, presents extracted text, records questions, and plays returned audio. |
| `backend/routes/pitch.py` | Extracts document content, selects relevant source chunks, and provides Q&A and audio endpoints. |
| `backend/data/pitch.txt` | Default pitch content used when no document has been uploaded. |
| `run-dev.sh` | Starts FastAPI on port 8000 and Streamlit on port 8501. |
| `render-start.sh` | Starts FastAPI internally and Streamlit on Render's public port. |

## Request flow

1. The user uploads a pitch document in the Streamlit interface.
2. The API extracts and validates text, then retains it in the active document store.
3. For each question, the API selects relevant sentences and either generates a constrained answer with Hugging Face or returns an extractive fallback.
4. Optional voice routes transcribe recorded audio and synthesize pitch or answer audio through configured providers.

## Operational notes

- API credentials live only in the root `.env` file or deployment secret environment variables.
- The active document is in-memory; it resets when the API restarts. Persistent per-user document storage is a future extension.
- The local design/reference folders `motion-primitives/` and `threeui/` are intentionally ignored and are not application dependencies.
