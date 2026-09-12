# AIrtribeXRender
Build your first AI agent and deploy

## Render deployment

Render uses one web service and one Start Command:

```bash
bash render-start.sh
```

The script runs FastAPI internally on `127.0.0.1:8000` and exposes Streamlit on Render's `$PORT`. Set `HUGGINGFACE_API_TOKEN` and `SARVAM_API_KEY` as secret environment variables in the Render dashboard.
