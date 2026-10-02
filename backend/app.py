import hmac
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import load_environment, setting

load_environment()

from routes.pitch import router, store


app = FastAPI(title="Pitchroom AI API", version="1.0.0")
allowed_origins = [
    origin.strip()
    for origin in setting("FRONTEND_ORIGINS").split(",")
    if origin.strip()
]
@app.middleware("http")
async def require_room_token(request: Request, call_next):
    if request.method != "OPTIONS" and (request.url.path == "/api" or request.url.path.startswith("/api/")):
        # The Render launcher fails closed; an empty setting is for loopback development.
        required_token = setting("PITCHROOM_ACCESS_TOKEN")
        if required_token:
            scheme, _, provided_token = request.headers.get("authorization", "").partition(" ")
            if scheme.lower() != "bearer" or not hmac.compare_digest(provided_token, required_token):
                return JSONResponse(
                    {"detail": "Enter the access token configured for this Pitchroom room."},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
    return await call_next(request)


# Keep CORS outside the access gate so browser clients can read 401 challenges.
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

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
