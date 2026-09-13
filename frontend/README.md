# Pitchroom AI live-room frontend

`static/` is a dependency-free browser application served by FastAPI at `/`. It is designed for a hackathon presentation rather than a manual recorder workflow.

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
4. The browser uploads the recording to `/api/voice/transcribe`, requests a grounded answer, and speaks it through the configured server provider or the built-in browser voice when `TTS_PROVIDER=browser` (the no-key default).
5. During playback, sustained speech interrupts the reply and continues the hot microphone capture as the next question. Otherwise, the same microphone session re-arms automatically when playback ends.

An explicit **End live session** control stays available. A typed source-question form is the presentation fallback. The live loop needs an HTTPS page outside `localhost`; use Chrome or Edge for the most predictable demo behavior. Headphones are the most reliable setup for interruption because acoustic echo cancellation varies by venue and microphone.

The 3D voice orb asset lives at `static/assets/pitchroom-voice-orb.png`. Its visual states are decorative and respect `prefers-reduced-motion`; VAD does not depend on animation.
