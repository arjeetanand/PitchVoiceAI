# Pitchroom Frontend

Streamlit interface for the AirtribeXRender pitch voice backend.

## Run

Start the backend first:

```powershell
cd PitchVoiceAI/backend
python -m uvicorn app:app --reload
```

Then start the frontend in a second terminal:

```powershell
cd PitchVoiceAI/frontend
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

From the repository root, the same two services can be started together with `./run-dev.sh`. The launcher uses the active Python environment for both Uvicorn and Streamlit.

The frontend lets users:

- Upload PDF, Markdown, or plain-text pitch documents.
- Review the extracted transcript.
- Play the full pitch using the backend TTS provider.
- Ask questions and receive answers grounded in extracted source sections.
- Play grounded answers aloud.
- Record a question and receive a Hugging Face Whisper transcription, grounded answer, and spoken response.

Configure `HUGGINGFACE_API_TOKEN` in the repository root `.env` for voice transcription and provider-backed answer generation. `SARVAM_API_KEY` enables the preferred Bulbul TTS path; local Hugging Face TTS, Hugging Face API TTS, and OpenAI TTS are supported fallbacks. Extractive Q&A works without a provider key, while speech controls show a setup message when no speech provider is configured.
