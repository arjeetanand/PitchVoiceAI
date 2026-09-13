# Pitchroom AI live-room frontend

`static/` is a no-build browser application served by FastAPI at `/`. It is designed for a hackathon presentation rather than a manual recorder workflow.

There is no separate Python frontend process; start the backend with the root
`./run-dev.sh` command and it serves this browser application and the API from
the same origin.

## Run

From the repository root:

```bash
./run-dev.sh
```

Open `http://127.0.0.1:8501`. The interface and API intentionally share one origin, including in production.

## Live voice behavior

1. The presenter selects **Start live session** once and grants microphone permission.
2. Browser VAD uses microphone RMS energy with a small adaptive noise floor.
3. Speech is confirmed after about 160 ms; a pause of about 850 ms ends the turn.
4. As the room opens, it calls `/api/voice/warm` and visibly reports **Studio voice ready**, browser-voice readiness, or fallback status. The endpoint is a no-op for browser and hosted voices, but preloads the explicitly selected local Kokoro studio voice before the first question.
5. The browser uploads the recording to `/api/voice/transcribe`, requests a grounded answer, and speaks it through the configured server provider or the built-in browser voice when `TTS_PROVIDER=browser` (the no-key default).
6. Before the short server WAV finishes buffering—and throughout playback—the browser retains a guarded hot capture. Sustained speech interrupts the reply and continues as the next question. Otherwise, the same microphone session re-arms automatically when playback ends.

An explicit **End live session** control stays available. A typed source-question form is the presentation fallback. The live loop needs an HTTPS page outside `localhost`; use Chrome or Edge for the most predictable demo behavior. Headphones are the most reliable setup for interruption because acoustic echo cancellation varies by venue and microphone.

## Visual layer

`static/scene.js` lazily imports a pinned Three.js module and renders one decorative, scroll-responsive particle field behind the semantic page. It morphs through the five story scenes and gently responds to voice state and microphone energy, while the actual controls, transcript, and evidence remain ordinary accessible HTML.

The visual layer caps device pixel ratio and particle density, pauses when the document is hidden, and respects `prefers-reduced-motion`. If the optional module cannot be reached—for example, on a presentation network that blocks the CDN—the canvas hides and the live room remains fully usable.
