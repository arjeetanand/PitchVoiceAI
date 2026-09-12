# Pitchroom Frontend

Streamlit interface for the AirtribeXRender pitch voice backend.

## Run

Start the backend first:

```powershell
cd AIrtribeXRender\backend
python -m uvicorn app:app --reload
```

Then start the frontend in a second terminal:

```powershell
cd AIrtribeXRender\frontend
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

Configure `HUGGINGFACE_API_TOKEN` in the repository root `.env`. The default models are Whisper for speech-to-text, Qwen for grounded answer generation, and MMS-TTS for speech output. OpenAI remains a fallback when configured. Extractive Q&A works without a provider key.
