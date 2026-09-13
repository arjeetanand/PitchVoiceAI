import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from routes.pitch import router, store


app = FastAPI(title="Pitchroom AI API", version="1.0.0")
allowed_origins = [
    origin.strip()
    for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)

# The public demo uses one origin: FastAPI serves both the API and the browser
# voice room.  That keeps microphone uploads on the same HTTPS origin in a
# deployment instead of exposing a private localhost API to presentation
# attendees' browsers.
FRONTEND_STATIC_DIR = Path(__file__).resolve().parents[1] / "frontend" / "static"
if FRONTEND_STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=FRONTEND_STATIC_DIR), name="frontend-static")

    @app.get("/", include_in_schema=False)
    def serve_frontend() -> FileResponse:
        return FileResponse(FRONTEND_STATIC_DIR / "index.html")

__all__ = ["app", "store"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
