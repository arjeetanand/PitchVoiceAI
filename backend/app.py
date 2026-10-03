import hmac
import json
from pathlib import Path
from threading import BoundedSemaphore

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import load_environment, setting

load_environment()

from routes.pitch import UPLOAD_ENDPOINTS, request_body_limit, router, store


class RequestSecurityMiddleware:
    """Protect API calls and bound request parsing before FastAPI reads bodies."""

    def __init__(self, app):
        self.app = app
        # ponytail: one upload at a time suits the shared presenter room; use shared admission control if scaled.
        self.upload_slots = BoundedSemaphore(1)

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "/")
        method = scope.get("method", "GET").upper()
        headers = scope.get("headers", [])
        limit = request_body_limit(path)
        content_lengths = [value for name, value in headers if name.lower() == b"content-length"]
        transfer_encodings = [value for name, value in headers if name.lower() == b"transfer-encoding"]
        if len(content_lengths) > 1 or (content_lengths and transfer_encodings):
            await self._respond(send, 400, "The request has an invalid content length.")
            return
        if content_lengths:
            raw_length = content_lengths[0]
            if not raw_length or not raw_length.isdigit():
                await self._respond(send, 400, "The request has an invalid content length.")
                return
            declared_length = raw_length.lstrip(b"0") or b"0"
            maximum_length = str(limit).encode("ascii")
            if len(declared_length) > len(maximum_length) or (
                len(declared_length) == len(maximum_length) and declared_length > maximum_length
            ):
                await self._respond(send, 413, "The request body exceeds the size limit.")
                return

        api_request = path == "/api" or path.startswith("/api/")
        if api_request and method != "OPTIONS":
            access_token = setting("PITCHROOM_ACCESS_TOKEN")
            if not access_token:
                await self._respond(send, 503, "PITCHROOM_ACCESS_TOKEN must be configured.")
                return
            authorization = [value for name, value in headers if name.lower() == b"authorization"]
            if len(authorization) != 1 or not self._authorized(authorization[0], access_token):
                await self._respond(
                    send,
                    401,
                    "Enter the access token configured for this Pitchroom room.",
                    [(b"www-authenticate", b"Bearer")],
                )
                return

            if method not in {"GET", "HEAD", "OPTIONS"}:
                origins = [value for name, value in headers if name.lower() == b"origin"]
                allowed = {
                    origin.strip()
                    for origin in setting("FRONTEND_ORIGINS").split(",")
                    if origin.strip()
                }
                if len(origins) != 1 or origins[0].decode("latin-1") not in allowed:
                    await self._respond(send, 403, "A trusted browser origin is required.")
                    return

        upload_slot = path in UPLOAD_ENDPOINTS
        if upload_slot and not self.upload_slots.acquire(blocking=False):
            await self._respond(send, 429, "The upload service is busy. Try again shortly.")
            return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise HTTPException(status_code=413, detail="The request body exceeds the size limit.")
            return message

        try:
            await self.app(scope, limited_receive, send)
        finally:
            if upload_slot:
                self.upload_slots.release()

    @staticmethod
    def _authorized(header: bytes, access_token: str) -> bool:
        try:
            scheme, provided_token = header.decode("ascii").split(" ", 1)
            if scheme.lower() != "bearer" or len(provided_token) > 4096:
                return False
        except (UnicodeDecodeError, ValueError):
            return False
        return hmac.compare_digest(provided_token.encode("ascii"), access_token.encode("utf-8"))

    @staticmethod
    async def _respond(send, status: int, detail: str, extra_headers=None) -> None:
        body = json.dumps({"detail": detail}).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
            *(extra_headers or []),
        ]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})


app = FastAPI(title="Pitchroom AI API", version="1.0.0")
app.add_middleware(RequestSecurityMiddleware)
allowed_origins = [
    origin.strip()
    for origin in setting("FRONTEND_ORIGINS").split(",")
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
