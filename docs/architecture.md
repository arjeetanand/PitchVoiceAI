# Architecture

Pitchroom AI serves one same-origin browser application from FastAPI. This is deliberate: the live browser microphone can send its audio to `/api` without trying to reach a private server address from a presentation attendee's device.

```text
Browser live room (frontend/static)
        |
        +-- MediaRecorder + adaptive silence detection
        |       Start once → speak → pause → send turn
        |
        | same-origin /api
        v
FastAPI (backend/)
        |
        +-- document extraction and in-memory source store
        +-- source-grounded Q&A
        +-- speech-to-text and text-to-speech providers
```

## Components

| Area | Responsibility |
| --- | --- |
| `frontend/static/` | Light presentation interface, generated 3D voice orb, browser microphone lifecycle, adaptive silence detection, source evidence, typed fallback, and audio playback. |
| `backend/routes/pitch.py` | Extracts document content, selects relevant source chunks, and provides Q&A and audio endpoints. |
| `backend/data/pitch.txt` | Verified demo brief used by the one-click demo path. |
| `run-dev.sh` | Starts the same-origin FastAPI application on port 8501 by default. |
| `render-start.sh` | Starts one public FastAPI process on Render's assigned port. |

## Request flow

1. The user loads the included demo brief or uploads a pitch document in the browser interface.
2. The API extracts and validates text, then retains it in the active document store.
3. For each question, the API selects relevant sentences and returns a deterministic extractive answer by default. Hugging Face answer generation is an explicit optional enhancement.
4. During a live session, the browser begins recording once speech is confirmed and ends a turn after about 850 ms of silence. It sends WebM or MP4 audio to Hugging Face Whisper, retrieves source sections, synthesizes the answer through configured Sarvam, local Piper, Hugging Face, or OpenAI providers, then re-arms the same microphone stream after reply playback. If no server TTS is available, the browser uses its built-in SpeechSynthesis voice locally. Sustained speech during a reply cancels the playback and promotes a guarded hot capture into the next turn.

## Operational notes

- API credentials live only in the root `.env` file or deployment secret environment variables.
- The active document is in-memory; it resets when the API restarts. Persistent per-user document storage is a future extension.
- The source text and recorded audio leave the app when a configured third-party transcription or speech provider processes them. Use an approved non-sensitive demo source.
- Set `TTS_PROVIDER=browser` for a no-key presentation: reply text stays in the browser and is spoken by the device voice. Set `TTS_PROVIDER=piper` with `PIPER_TTS_URL` for a local neural voice; Piper is an optional separate process.
- Browser microphone capture requires HTTPS in deployment (or `localhost` while developing). There is intentionally one explicit **Start live session** control because browsers require a user gesture for microphone permission.
- Text extraction supports selectable PDF text only. Image-only slides, charts, tables, and scanned documents are not yet part of the retrieval path.
- The generated orb is a local presentation asset; its animation is decorative and independent from the silence-detection loop. Reduced-motion settings disable its motion.
