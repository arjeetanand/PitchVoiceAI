# Pitchroom AI

**Every answer, from the deck.**

Pitchroom AI turns an approved, text-based pitch into a source-grounded voice rehearsal. A founder can load a pitch, ask a question aloud, see what the system heard, inspect the supporting source sections, and hear the answer back.

## The problem

Pitch decks are written to be read, but meetings are conversations. When a customer or investor asks an unexpected question, founders may search through slides or improvise an answer that was never approved.

Pitchroom AI gives founder-led teams a rehearsal space that keeps the approved source visible. When the prototype finds no matching approved-source evidence, it says so instead of inventing a claim.

## What the prototype does

- Loads selectable-text PDFs, Markdown, and plain-text pitch documents.
- Retrieves the most relevant source sections for a question.
- Supports typed questions and a browser-native live voice session.
- Runs a hands-free voice turn: speech detected → short pause detected → speech-to-text → source-grounded answer → text-to-speech → microphone re-armed. Speaking over a reply interrupts it and starts the next turn.
- Shows the transcript, answer, and source sections used.
- Includes a verified demo brief with facts about the working prototype.

The experience is seamless turn-taking, not streaming transcription: a presenter starts the room once, then a short pause ends each question automatically. The active document stays in memory and is shared by the running API, so this is suitable for a controlled hackathon demo rather than multi-user production use.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
cp backend/.env.example .env
./run-dev.sh
```

Open [http://127.0.0.1:8501](http://127.0.0.1:8501). The included `pitch.txt` brief loads automatically. Use **Start live session** once, ask naturally, and pause to send the question. Use **Use demo brief** whenever a rehearsal needs a clean reset. Upload an approved text-based PDF, Markdown, or TXT file when rehearsing your own pitch.

## Voice configuration

Copy `backend/.env.example` to the repository-root `.env` and configure only the providers you use:

- `TTS_PROVIDER=auto` enables the configured server-provider chain; add `SARVAM_API_KEY` to include Sarvam Bulbul.
- `HUGGINGFACE_API_TOKEN` enables Whisper transcription and optionally Hugging Face answer generation.
- `OPENAI_API_KEY` enables the OpenAI text-to-speech fallback.
- `TTS_PROVIDER=browser` forces the free browser-native voice; it needs no API key and keeps reply text in the browser.
- `TTS_PROVIDER=piper` plus `PIPER_TTS_URL` uses a free local Piper neural voice. Setup commands are in [backend/README.md](backend/README.md).

Pitchroom uses deterministic extractive answers by default, which makes the demo fast and auditable. Set `ANSWER_GENERATION_PROVIDER=huggingface` only after testing the configured hosted model. `MAX_AUDIO_BYTES` defaults to 10 MiB. In `auto` mode, configured server speech providers are tried before the browser voice fallback; `browser` is the safest no-cost demo setting.

Voice requests send recorded audio and, when a server TTS provider is selected, reply text to those configured third-party providers. With `TTS_PROVIDER=browser`, reply text is synthesized locally by the browser. Use only a non-sensitive demo brief unless your organization has approved that data handling.

The live microphone session needs a current desktop browser and HTTPS in deployment (`localhost` is permitted for local development). Chrome or Edge is the recommended presentation browser. The browser may require one tap on **Play answer** if its autoplay policy blocks an asynchronous reply; the room continues listening either way.

## Hackathon demo sequence

1. Start with the problem: static decks do not answer live questions.
2. Point to the visible approved source and select **Use demo brief** if needed.
3. Start the live session once and say: “What problem does Pitchroom AI solve?”
4. Pause; point out that the turn sends automatically, with no record-stop control.
5. Point to **Heard**, the grounded answer, the exact source evidence, and the spoken reply.
6. Ask an unsupported question, such as “What is the Series B valuation?” Explain that refusal is the trust feature.

The full speaking script and fallback plan are in [docs/hackathon-runbook.md](docs/hackathon-runbook.md).

## Testing

```bash
.venv/bin/python -m pytest backend -q
node --check frontend/static/app.js
```

## Deployment

`render.yaml` exposes one FastAPI service that serves both the static live room and `/api` from the same public origin. The default Render template uses the free browser voice, so only the transcription token is needed for live speech; add Sarvam or another server provider only if you want its voice. HTTPS is required for microphone capture outside local development.

Before presenting from a deployed service, use a non-sensitive source document, run the microphone check in the target browser, make one automatic-pause voice turn, and verify that a spoken interruption starts a fresh turn.
