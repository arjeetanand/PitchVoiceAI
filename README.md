# Pitchroom AI

**Every answer, from the deck.**

Pitchroom AI turns an approved pitch deck or document into a source-grounded voice rehearsal. A founder can load a pitch, ask a question aloud, see what the system heard, inspect the supporting slide/page sections, and hear the answer back.

## The problem

Pitch decks are written to be read, but meetings are conversations. When a customer or investor asks an unexpected question, founders may search through slides or improvise an answer that was never approved.

Pitchroom AI gives founder-led teams a rehearsal space that keeps the approved source visible. When the prototype finds no matching approved-source evidence, it says so instead of inventing a claim.

## What the prototype does

- Loads PPTX, selectable-text PDF, DOCX, Markdown, and plain-text pitch documents.
- Preserves slide/page provenance, including PPTX speaker notes, and shows the
  citation beside each grounded answer.
- Reports image-only slides/pages as review warnings instead of silently
  pretending that charts or screenshots were understood.
- Retrieves the most relevant source sections for each question.
- Supports typed questions and one-tap live voice conversations.
- Runs hands-free turns: speech detected → pause detected → transcription → grounded answer → spoken reply → microphone re-armed.
- Stops a spoken reply when the presenter interrupts and treats the interruption as the next question.
- Shows the transcript, answer, and exact source sections used.
- Presents the demo through five normal-scroll scenes with a lightweight, reactive 3D particle field—no scroll-jacking or canvas-only controls.
- Includes a verified demo brief with facts about the working prototype.

The experience is seamless turn-taking, not streaming transcription: a presenter starts the room once, then a short pause ends each question automatically. The active document stays in memory and is shared by the running API, so this is suitable for a controlled hackathon demo rather than multi-user production use.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-kokoro.txt
cp .env.example .env
./run-dev.sh
```

The Kokoro requirements are the recommended presentation install. They include
the base API dependencies and the local studio voice. If you only need typed
questions or the zero-install browser voice, install `backend/requirements.txt`
instead and set `TTS_PROVIDER=browser`.

Open [http://127.0.0.1:8501](http://127.0.0.1:8501). The included `pitch.txt`
brief loads automatically. Use **Start live session** once, ask naturally, and
pause to send the question. The reply stops if you speak over it, and the same
session listens for the next question automatically. Use **Use demo brief** for
a clean reset, or upload an approved PPTX, PDF, DOCX, Markdown, or TXT file
for rehearsal. Legacy binary `.ppt` files are converted only when LibreOffice
is available; exporting to `.pptx` is the reliable path.

## Configuration

There is one configuration file: the repository-root `.env`. Start from the
categorized [`.env.example`](.env.example), copy it to `.env`, and change only
the values needed for your demo. The backend and deployment template use this
same configuration contract; there is no second backend or frontend env file.

For the local presentation voice, set:

```dotenv
TTS_PROVIDER=kokoro
KOKORO_LANG_CODE=a
KOKORO_VOICE=af_heart
KOKORO_SPEED=0.98
KOKORO_DEVICE=auto
```

Live microphone transcription also needs a Hugging Face token in `.env`:

```dotenv
HUGGINGFACE_API_TOKEN=your_token_here
```

The hosted demo also requires a private `PITCHROOM_ACCESS_TOKEN` secret. Generate
one with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`, then
add it to Render's environment settings. The room asks attendees for this token
the first time they use the app in a tab. Set the same value in `.env` to enable
the access gate locally. The public `/health` check returns status only.

The important provider choices are:

- `TTS_PROVIDER=kokoro` is the recommended hackathon studio voice: a local, cached Kokoro English model with the curated `af_heart` narrator. Install it with `.venv/bin/python -m pip install -r backend/requirements-kokoro.txt`; its first model download is about 360 MB, then answer text stays on the presentation machine with no per-request TTS charge.
- `TTS_PROVIDER=auto` enables the configured server-provider chain; add `SARVAM_API_KEY` to include Sarvam Bulbul.
- `HUGGINGFACE_API_TOKEN` enables Whisper transcription and optionally Hugging Face answer generation.
- `OPENAI_API_KEY` enables the OpenAI text-to-speech fallback.
- `TTS_PROVIDER=browser` forces the free browser-native voice; it needs no API key and keeps reply text in the browser.
- `TTS_PROVIDER=piper` plus `PIPER_TTS_URL` uses a free local Piper neural voice. Setup commands are in [backend/README.md](backend/README.md).

The remaining provider settings are grouped in `.env.example` under runtime,
speech-to-text, local voice, and hosted voice sections. You do not need to fill
every key. Typed questions and browser speech work without a provider key;
live microphone transcription uses the configured Hugging Face Whisper path.

Kokoro starts warming as the live room opens, loading its model and narrator while the presenter gets ready. On its first install it downloads the public model artifacts from Hugging Face (not your answer text); after that cache is present, answers stay on the presentation machine and the demo can run offline for TTS. For the first launch, wait until the page is fully open before the first question; later answers use the in-memory model. This avoids a provider round trip, but it is not literal streaming audio—keep live answers to one to three sentences for the quickest response. Use `KOKORO_VOICE=af_bella` to audition the alternative high-quality English narrator, then keep one voice consistent for the demo.

Pitchroom uses deterministic extractive answers by default, which makes the demo fast and auditable. Set `ANSWER_GENERATION_PROVIDER=huggingface` only after testing the configured hosted model. `MAX_AUDIO_BYTES` defaults to 10 MiB. In `auto` mode, configured server speech providers are tried before the browser voice fallback; `browser` is the safest no-cost demo setting. Kokoro is explicit-only and never silently enters that chain.

Voice requests send recorded audio and, when a hosted server TTS provider is selected, reply text to those configured third-party providers. With `TTS_PROVIDER=browser` or `TTS_PROVIDER=kokoro`, reply text is synthesized locally. The live transcription path still uses the configured speech-to-text provider. Use only a non-sensitive demo brief unless your organization has approved that data handling.

The live microphone session needs a current desktop browser and HTTPS in
deployment (`localhost` is permitted for local development). Chrome or Edge is
the recommended presentation browser. Headphones are the most reliable setup
for interruption because acoustic echo cancellation varies by venue.

## Repository layout

| Path | Purpose |
| --- | --- |
| `frontend/static/` | The browser live room, responsive Three.js particle field, VAD, barge-in handling, transcript, and source-evidence UI. |
| `backend/app.py` | FastAPI entrypoint; serves the browser room and `/api` from one origin. |
| `backend/routes/pitch.py` | Document ingestion, grounded answers, transcription, and speech-provider integrations. |
| `backend/config.py` | Loads the root `.env` and owns the supported setting names and defaults. |
| `backend/data/pitch.txt` | Verified demo brief used by **Use demo brief**. |
| `run-dev.sh` | Local development server on port 8501. |
| `render-start.sh` | Render production start command. |

## Hackathon demo sequence

1. Start with the problem: static decks do not answer live questions.
2. Upload the real `.pptx` when the deck is text-selectable, then point to the
   visible slide/page extraction status. Use **Use demo brief** if needed.
3. Start the live session once and say: “What problem does Pitchroom AI solve?”
4. Pause; point out that the turn sends automatically, with no record-stop control.
5. Point to **Heard**, the grounded answer, the exact source evidence, and the spoken reply.
6. Ask an unsupported question, such as “What is the Series B valuation?” Explain that refusal is the trust feature.

For a real judging demo, keep a text-selectable deck or exported PDF ready. A
slide that is only a screenshot or chart is surfaced as a review warning; it is
not silently treated as reliable evidence.

The full speaking script and fallback plan are in [docs/hackathon-runbook.md](docs/hackathon-runbook.md).
The format support, trust boundary, and production path are in
[presentation-product-plan.md](presentation-product-plan.md).

## Testing

```bash
.venv/bin/python -m pytest backend -q
node --check frontend/static/app.js
node --check frontend/static/scene.js
node --test frontend/test_e2e.mjs # local Chrome required
```

## Deployment

`render.yaml` exposes one FastAPI service that serves both the static live room
and `/api` from the same public origin. Render uses the free browser voice by
default, so only `HUGGINGFACE_API_TOKEN` is needed for live speech. Run Kokoro
locally for the polished in-person presentation voice, or configure another
server provider only when you intentionally need it. HTTPS is required for
microphone capture outside local development.

Before presenting from a deployed service, use a non-sensitive source document, run the microphone check in the target browser, make one automatic-pause voice turn, and verify that a spoken interruption starts a fresh turn.
