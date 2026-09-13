from __future__ import annotations

import hashlib
import json
import os
from html import escape
from pathlib import Path
from typing import Any

import requests
import streamlit as st
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")
DEFAULT_BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
ALLOW_CUSTOM_BACKEND_URL = os.getenv("ALLOW_CUSTOM_BACKEND_URL", "false").strip().lower() in {"1", "true", "yes"}

st.set_page_config(
    page_title="Pitchroom | Voice pitch assistant",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def icon(name: str, size: int = 20, stroke_width: float = 1.8) -> str:
    """Return a small, consistent SVG icon for the code-native UI."""

    paths = {
        "wave": (
            '<path d="M4 10v4M8 7v10M12 4v16M16 7v10M20 10v4" '
            'stroke="currentColor" stroke-linecap="round"/>'
        ),
        "upload": (
            '<path d="M12 16V4m0 0-4 4m4-4 4 4M5 14v4.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V14" '
            'stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"/>'
        ),
        "file": (
            '<path d="M6 3.75h7.1L18 8.65v11.6H6z" stroke="currentColor" stroke-linejoin="round"/>'
            '<path d="M13 3.75v5h5M9 13h6M9 16h4" stroke="currentColor" stroke-linecap="round"/>'
        ),
        "mic": (
            '<rect x="9" y="3" width="6" height="11" rx="3" stroke="currentColor"/>'
            '<path d="M6.5 11.5a5.5 5.5 0 0 0 11 0M12 17v4m-3 0h6" stroke="currentColor" stroke-linecap="round"/>'
        ),
        "message": (
            '<path d="M5.5 6.25h13a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-7l-4.5 3v-3h-1.5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2Z" '
            'stroke="currentColor" stroke-linejoin="round"/>'
            '<path d="M8.5 11.75h.01M12 11.75h.01M15.5 11.75h.01" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>'
        ),
        "play": '<path d="m9 6 8 6-8 6z" fill="currentColor"/>',
        "arrow": '<path d="M5 12h13m-5-5 5 5-5 5" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"/>',
        "check": '<path d="m6 12 4 4 8-9" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"/>',
        "spark": (
            '<path d="m12 3 1.15 5.85L19 10l-5.85 1.15L12 17l-1.15-5.85L5 10l5.85-1.15z" '
            'stroke="currentColor" stroke-linejoin="round"/>'
        ),
    }
    return (
        f'<svg class="pr-icon" width="{size}" height="{size}" viewBox="0 0 24 24" '
        f'fill="none" stroke-width="{stroke_width}" aria-hidden="true">{paths[name]}</svg>'
    )


def waveform(heights: list[int], class_name: str = "") -> str:
    bars = "".join(f'<span style="--bar-height:{height}px"></span>' for height in heights)
    return f'<div class="pr-waveform {class_name}">{bars}</div>'


def api_request(method: str, path: str, *, timeout: int = 45, **kwargs: Any) -> requests.Response:
    url = f"{st.session_state.backend_url}{path}"
    return requests.request(method, url, timeout=timeout, **kwargs)


def response_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
    except (TypeError, ValueError):
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("error") or response.text
    elif payload is not None:
        detail = payload
    else:
        detail = response.text
    if isinstance(detail, (dict, list)):
        detail = json.dumps(detail)
    return str(detail or "Request failed.")


def response_audio_format(response: requests.Response, fallback: str = "audio/wav") -> str:
    media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    return media_type if media_type.startswith("audio/") else fallback


def show_api_error(response: requests.Response) -> None:
    st.error(f"Backend error ({response.status_code}): {response_detail(response)}")


def reset_answer_state() -> None:
    st.session_state.answer = None
    st.session_state.answer_audio = None
    st.session_state.answer_audio_format = None
    st.session_state.answer_audio_error = None
    st.session_state.answer_audio_autoplay = False
    st.session_state.last_heard_question = None


def load_active_pitch() -> bool:
    """Load the server's current approved source without triggering speech synthesis."""
    try:
        pitch_response = api_request("GET", "/api/pitch")
        if not pitch_response.ok:
            show_api_error(pitch_response)
            return False
        st.session_state.pitch = pitch_response.json()
        st.session_state.pitch_audio = None
        st.session_state.pitch_audio_format = "audio/wav"
        st.session_state.pitch_audio_error = None
        reset_answer_state()
        return True
    except (KeyError, requests.RequestException, TypeError, ValueError) as exc:
        st.error(f"Could not load the pitch: {exc}")
        return False


def load_demo_pitch() -> bool:
    """Restore the bundled demo brief before loading the workspace."""
    try:
        demo_response = api_request("POST", "/api/pitch/demo")
        if not demo_response.ok:
            show_api_error(demo_response)
            return False
        return load_active_pitch()
    except (KeyError, requests.RequestException, TypeError, ValueError) as exc:
        st.error(f"Could not restore the demo source: {exc}")
        return False


def read_loaded_pitch() -> None:
    """Request pitch narration only when the presenter asks for it."""
    if st.session_state.pitch is None:
        st.warning("Load a pitch before asking Pitchroom to read it aloud.")
        return
    with st.spinner("Preparing pitch audio..."):
        try:
            audio_response = api_request("POST", "/api/pitch/read", timeout=90)
            if audio_response.ok and audio_response.content:
                st.session_state.pitch_audio = audio_response.content
                st.session_state.pitch_audio_format = response_audio_format(audio_response)
                st.session_state.pitch_audio_error = None
            else:
                st.session_state.pitch_audio_error = response_detail(audio_response)
        except requests.RequestException as exc:
            st.session_state.pitch_audio_error = str(exc)


def process_uploaded_file(uploaded_file: Any) -> None:
    uploaded_bytes = uploaded_file.getvalue()
    uploaded_hash = hashlib.sha256(uploaded_bytes).hexdigest()
    if uploaded_hash == st.session_state.processed_file_hash:
        return

    with st.spinner("Extracting the pitch and preparing the workspace..."):
        try:
            upload_response = api_request(
                "POST",
                "/api/pitch/file",
                files={
                    "file": (
                        uploaded_file.name,
                        uploaded_bytes,
                        uploaded_file.type or "application/octet-stream",
                    )
                },
            )
            if not upload_response.ok:
                show_api_error(upload_response)
                return
        except (KeyError, requests.RequestException, TypeError, ValueError) as exc:
            st.error(f"Upload failed: {exc}")
            st.session_state.processed_file_hash = None
            return

        if not load_active_pitch():
            st.session_state.processed_file_hash = None
            return

        st.session_state.processed_file_hash = uploaded_hash
        st.session_state.processed_recording_hash = None
        st.session_state.clear_typed_question = True
        st.rerun()


def answer_from_question(question: str) -> None:
    try:
        response = api_request(
            "POST",
            "/api/voice/answer",
            json={"question": question.strip()},
            timeout=120,
        )
        if response.ok:
            st.session_state.answer = response.json()
            st.session_state.answer_audio = None
            st.session_state.answer_audio_format = None
            st.session_state.answer_audio_error = None
            st.session_state.answer_audio_autoplay = False
        else:
            show_api_error(response)
    except (KeyError, requests.RequestException, TypeError, ValueError) as exc:
        st.error(f"Question failed: {exc}")


def process_voice_recording(recording: Any) -> None:
    recording_bytes = recording.getvalue()
    recording_hash = hashlib.sha256(recording_bytes).hexdigest()
    if recording_hash == st.session_state.processed_recording_hash:
        return

    st.session_state.answer_audio = None
    st.session_state.answer_audio_format = None
    st.session_state.answer_audio_error = None
    st.session_state.last_heard_question = None
    with st.spinner("Transcribing and answering from the pitch..."):
        try:
            transcription_response = api_request(
                "POST",
                "/api/voice/transcribe",
                files={
                    "file": (
                        "question.wav",
                        recording_bytes,
                        recording.type or "audio/wav",
                    )
                },
                timeout=120,
            )
            if not transcription_response.ok:
                show_api_error(transcription_response)
                return

            question_text = transcription_response.json()["text"]
            answer_response = api_request(
                "POST",
                "/api/voice/answer",
                json={"question": question_text},
                timeout=120,
            )
            if not answer_response.ok:
                show_api_error(answer_response)
                return

            st.session_state.answer = answer_response.json()
            st.session_state.last_heard_question = question_text
            try:
                audio_response = api_request(
                    "POST",
                    "/api/voice/speak",
                    json={"text": st.session_state.answer["answer"]},
                    timeout=90,
                )
                if audio_response.ok and audio_response.content:
                    st.session_state.answer_audio = audio_response.content
                    st.session_state.answer_audio_format = response_audio_format(audio_response)
                    st.session_state.answer_audio_autoplay = True
                else:
                    st.session_state.answer_audio_error = response_detail(audio_response)
            except requests.RequestException as exc:
                st.session_state.answer_audio_error = str(exc)
            st.session_state.processed_recording_hash = recording_hash
        except (KeyError, requests.RequestException, TypeError, ValueError) as exc:
            st.error(f"Voice conversation failed: {exc}")
            st.session_state.processed_recording_hash = None


for key, default in {
    "backend_url": DEFAULT_BACKEND_URL,
    "pitch": None,
    "answer": None,
    "processed_file_hash": None,
    "processed_recording_hash": None,
    "pitch_audio": None,
    "pitch_audio_format": "audio/wav",
    "answer_audio": None,
    "answer_audio_format": "audio/wav",
    "answer_audio_autoplay": False,
    "pitch_audio_error": None,
    "answer_audio_error": None,
    "last_heard_question": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

if st.session_state.pop("clear_typed_question", False):
    st.session_state.pop("typed_question", None)


st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&display=swap');

    :root {
        --pr-ink: #101828;
        --pr-ink-soft: #344054;
        --pr-muted: #667085;
        --pr-subtle: #98a2b3;
        --pr-blue: #315cf6;
        --pr-blue-dark: #2445c7;
        --pr-sky: #dff1ff;
        --pr-sky-soft: #f4f9ff;
        --pr-lavender: #eef2ff;
        --pr-mint: #d9f8ee;
        --pr-line: #e6eaf0;
        --pr-line-strong: #d5deeb;
        --pr-white: #ffffff;
        --pr-shadow: 0 24px 60px rgba(29, 50, 93, 0.10);
    }

    html { scroll-behavior: smooth; }
    .stApp {
        background: linear-gradient(180deg, #ffffff 0%, #ffffff 65%, #f5faff 100%);
        color: var(--pr-ink);
    }
    [data-testid="stAppViewContainer"] { background: transparent; }
    [data-testid="stHeader"] { background: transparent; }
    [data-testid="stToolbar"] { visibility: visible; background: transparent; }
    [data-testid="stMainMenuButton"] { visibility: hidden; }
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    [data-testid="stMainBlockContainer"], .block-container {
        max-width: 1280px;
        padding-top: 1.1rem;
        padding-bottom: 5rem;
    }
    h1, h2, h3, h4, p, label, button, input, textarea, [data-testid="stMarkdownContainer"] {
        font-family: 'Manrope', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }
    h1, h2, h3, h4, p { color: var(--pr-ink); }
    h2 { letter-spacing: -0.035em; }
    .pr-icon { display: inline-block; flex: 0 0 auto; vertical-align: middle; }
    .pr-mono {
        font-family: 'DM Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
        letter-spacing: 0.02em;
    }
    .pr-anchor { scroll-margin-top: 24px; }

    .pr-topbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 28px;
        padding: 1rem 0 1.5rem;
    }
    .pr-brand {
        display: inline-flex;
        align-items: center;
        gap: 11px;
        color: var(--pr-ink);
        font-size: 1.25rem;
        font-weight: 800;
        letter-spacing: -0.045em;
        text-decoration: none;
    }
    nav.pr-topbar a.pr-brand, nav.pr-topbar a.pr-brand:hover {
        color: var(--pr-ink) !important;
        text-decoration: none !important;
    }
    .pr-brand-mark {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 35px;
        height: 35px;
        color: var(--pr-blue);
        border: 1px solid #d8e4ff;
        border-radius: 12px;
        background: #f4f7ff;
    }
    .pr-brand-mark .pr-icon { width: 23px; height: 23px; stroke-width: 2.2; }
    .pr-nav {
        display: flex;
        align-items: center;
        gap: 2.1rem;
        margin-left: auto;
    }
    .pr-nav a {
        color: var(--pr-muted);
        font-size: 0.86rem;
        font-weight: 700;
        text-decoration: none;
        transition: color 160ms ease;
    }
    .pr-nav a:hover { color: var(--pr-blue); }
    .pr-nav-cta, .pr-primary-cta {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 0.55rem;
        border: 1px solid var(--pr-blue);
        border-radius: 12px;
        background: var(--pr-blue);
        color: var(--pr-white) !important;
        font-weight: 800 !important;
        text-decoration: none !important;
        box-shadow: 0 8px 20px rgba(49, 92, 246, 0.16);
        transition: transform 160ms ease, box-shadow 160ms ease, background 160ms ease;
    }
    .pr-nav-cta {
        min-height: 2.75rem;
        padding: 0.55rem 1.05rem;
        font-size: 0.82rem;
    }
    .pr-primary-cta {
        min-height: 3.35rem;
        padding: 0.8rem 1.35rem;
        font-size: 0.95rem;
    }
    .pr-nav-cta:hover, .pr-primary-cta:hover {
        background: var(--pr-blue-dark);
        box-shadow: 0 12px 24px rgba(49, 92, 246, 0.22);
        transform: translateY(-2px);
    }

    .pr-hero {
        display: grid;
        grid-template-columns: minmax(0, 0.95fr) minmax(0, 1.05fr);
        align-items: center;
        gap: clamp(2.5rem, 4.5vw, 5rem);
        padding: 4.35rem 0 5.8rem;
    }
    .pr-hero-copy { position: relative; }
    .pr-hero-copy h1 {
        max-width: 610px;
        margin: 0;
        color: var(--pr-ink);
        font-size: clamp(3.15rem, 4.8vw, 5rem);
        font-weight: 800;
        letter-spacing: -0.075em;
        line-height: 0.97;
    }
    .pr-hero-copy h1 span { display: block; }
    .pr-hero-copy p {
        max-width: 490px;
        margin: 1.8rem 0 2rem;
        color: var(--pr-muted);
        font-size: 1.05rem;
        line-height: 1.65;
    }
    .pr-hero-wave {
        position: absolute;
        z-index: -1;
        right: -2.4rem;
        bottom: -1.9rem;
        width: min(420px, 90%);
        opacity: 0.72;
        pointer-events: none;
    }

    .pr-product-preview {
        position: relative;
        overflow: hidden;
        border: 1px solid #dae6f3;
        border-radius: 24px;
        background: #f7fbff;
        box-shadow: var(--pr-shadow);
    }
    .pr-product-preview::before {
        position: absolute;
        top: -5rem;
        right: -3rem;
        width: 17rem;
        height: 17rem;
        border-radius: 50%;
        background: rgba(219, 237, 255, 0.52);
        content: '';
        filter: blur(1px);
        pointer-events: none;
    }
    .pr-preview-toolbar {
        position: relative;
        z-index: 1;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
        min-height: 3.8rem;
        padding: 0.75rem 1rem;
        border-bottom: 1px solid #dce7f2;
        background: rgba(255, 255, 255, 0.78);
    }
    .pr-preview-toolbar-brand, .pr-preview-file {
        display: inline-flex;
        align-items: center;
        gap: 0.55rem;
        color: var(--pr-ink);
        font-size: 0.79rem;
        font-weight: 800;
    }
    .pr-preview-toolbar-brand { font-size: 0.95rem; letter-spacing: -0.04em; }
    .pr-preview-toolbar-brand .pr-icon { color: var(--pr-blue); }
    .pr-preview-file { color: var(--pr-ink-soft); font-weight: 700; }
    .pr-preview-file .pr-icon { color: var(--pr-blue); }
    .pr-preview-menu { color: var(--pr-subtle); font-size: 1.15rem; letter-spacing: 0.15em; }
    .pr-preview-body {
        position: relative;
        z-index: 1;
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(250px, 0.82fr);
        gap: 0.8rem;
        padding: 0.8rem;
    }
    .pr-preview-document, .pr-preview-agent {
        min-height: 360px;
        border: 1px solid #dfe8f1;
        border-radius: 16px;
        background: rgba(255, 255, 255, 0.86);
    }
    .pr-preview-document { display: grid; grid-template-columns: 58px minmax(0, 1fr); overflow: hidden; }
    .pr-preview-rail { padding: 0.8rem 0.55rem; border-right: 1px solid #e3eaf2; background: #f9fcff; }
    .pr-preview-thumb {
        display: grid;
        place-items: center;
        height: 50px;
        margin-bottom: 0.55rem;
        border: 1px solid #dbe6f4;
        border-radius: 7px;
        background: #f6f9fe;
        color: #a2b7d3;
        font-family: 'DM Mono', monospace;
        font-size: 0.61rem;
    }
    .pr-preview-thumb.is-active { border: 2px solid #7ba3ff; color: var(--pr-blue); background: #eff5ff; }
    .pr-preview-page { padding: 1.55rem; background: #ffffff; }
    .pr-preview-page-title { max-width: 170px; margin: 0.25rem 0 1rem; color: var(--pr-ink); font-size: 1.7rem; font-weight: 800; letter-spacing: -0.06em; line-height: 1.02; }
    .pr-preview-page-copy { max-width: 200px; color: #8494aa; font-size: 0.62rem; line-height: 1.55; }
    .pr-preview-page-line { width: 72%; height: 4px; margin-top: 0.7rem; border-radius: 99px; background: #e6eef8; }
    .pr-preview-agent { padding: 1.2rem; }
    .pr-preview-agent-tabs { display: flex; gap: 1.1rem; padding-bottom: 0.72rem; border-bottom: 1px solid #e8edf4; color: #9aa6b8; font-size: 0.7rem; font-weight: 800; }
    .pr-preview-agent-tabs .is-active { color: var(--pr-blue); }
    .pr-preview-mic-area { display: grid; place-items: center; min-height: 163px; margin: 0.8rem 0; border-radius: 13px; background: var(--pr-lavender); }
    .pr-preview-mic { display: grid; place-items: center; width: 74px; height: 74px; border: 5px solid #e7edff; border-radius: 50%; background: var(--pr-blue); color: #ffffff; box-shadow: 0 8px 22px rgba(49, 92, 246, 0.2); }
    .pr-preview-mic .pr-icon { width: 29px; height: 29px; stroke-width: 1.7; }
    .pr-preview-agent-label { margin-top: 0.7rem; color: var(--pr-ink-soft); font-size: 0.73rem; font-weight: 800; }
    .pr-preview-question { padding: 0.75rem 0.8rem; border: 1px solid #dbe3ed; border-radius: 10px; color: #98a2b3; font-size: 0.7rem; }
    .pr-preview-answer { margin-top: 0.7rem; padding: 0.75rem 0.8rem; border-radius: 11px; background: var(--pr-mint); color: #12715a; font-size: 0.71rem; font-weight: 800; }
    .pr-preview-answer-lines { display: grid; gap: 0.35rem; margin-top: 0.55rem; }
    .pr-preview-answer-lines span { display: block; height: 4px; border-radius: 99px; background: rgba(19, 120, 92, 0.17); }
    .pr-preview-answer-lines span:nth-child(2) { width: 82%; }
    .pr-preview-answer-lines span:nth-child(3) { width: 60%; }
    .pr-waveform { display: inline-flex; align-items: center; justify-content: center; gap: 3px; min-height: 35px; }
    .pr-waveform span { display: block; width: 3px; height: var(--bar-height); border-radius: 99px; background: #93b9ff; }
    .pr-waveform-blue { margin: 0 auto 0.2rem; width: 100%; }
    .pr-preview-mic-area > div { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 0.45rem; width: 90%; }
    .pr-preview-mic-area .pr-waveform { overflow: hidden; }

    .pr-process-section {
        margin: 0 calc(50% - 50vw);
        padding: 4.3rem max(24px, calc((100vw - 1280px) / 2)) 4.6rem;
        border-top: 1px solid #e7f0f8;
        border-bottom: 1px solid #e7f0f8;
        background: #f4f9ff;
    }
    .pr-process-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: clamp(1.5rem, 5vw, 5rem); }
    .pr-step { position: relative; padding-top: 0.1rem; }
    .pr-step:not(:last-child)::after { position: absolute; top: 1.7rem; right: -2.4rem; width: 3.2rem; height: 1px; background: #b5d2fa; content: ''; }
    .pr-step-icon { display: grid; place-items: center; width: 3.25rem; height: 3.25rem; margin-bottom: 1.25rem; border: 1px solid #d8e8fb; border-radius: 15px; background: #e5f1ff; color: var(--pr-blue); }
    .pr-step-icon .pr-icon { width: 1.7rem; height: 1.7rem; stroke-width: 2.1; }
    .pr-step-index { margin-bottom: 0.6rem; color: #7b9ac3; font-family: 'DM Mono', monospace; font-size: 0.66rem; }
    .pr-step h3 { margin: 0; font-size: 1.08rem; font-weight: 800; letter-spacing: -0.035em; }
    .pr-step p { margin: 0.65rem 0 0; color: var(--pr-muted); font-size: 0.87rem; line-height: 1.55; }

    .pr-section-intro { display: flex; align-items: end; justify-content: space-between; gap: 2rem; margin: 5.8rem 0 1.65rem; }
    .pr-section-intro h2 { margin: 0.35rem 0 0; font-size: clamp(2rem, 3.4vw, 3.05rem); font-weight: 800; line-height: 1.02; }
    .pr-section-intro p { max-width: 470px; margin: 0; color: var(--pr-muted); font-size: 0.96rem; line-height: 1.6; }
    .pr-section-label { margin: 0; color: var(--pr-blue); font-family: 'DM Mono', monospace; font-size: 0.7rem; font-weight: 500; letter-spacing: 0.08em; text-transform: uppercase; }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border: 1px solid var(--pr-line) !important;
        border-radius: 24px !important;
        background: rgba(255, 255, 255, 0.93) !important;
        box-shadow: 0 18px 48px rgba(21, 57, 113, 0.06);
    }
    div[data-testid="stVerticalBlockBorderWrapper"] > div { border-radius: 24px !important; }
    .pr-upload-head { display: flex; align-items: start; justify-content: space-between; gap: 2rem; padding: 0.4rem 0 0.4rem; }
    .pr-upload-head h3 { margin: 0; font-size: 1.35rem; font-weight: 800; letter-spacing: -0.045em; }
    .pr-upload-head p { max-width: 520px; margin: 0.55rem 0 0; color: var(--pr-muted); font-size: 0.9rem; line-height: 1.55; }
    .pr-upload-icon { display: grid; place-items: center; width: 2.75rem; height: 2.75rem; border-radius: 13px; background: var(--pr-lavender); color: var(--pr-blue); }
    .pr-upload-icon .pr-icon { width: 1.45rem; height: 1.45rem; }
    [data-testid="stFileUploader"] {
        margin-top: 1.1rem;
        padding: 0.8rem;
        border: 1px dashed #b9cff0;
        border-radius: 16px;
        background: #f8fbff;
    }
    [data-testid="stFileUploaderDropzone"] { min-height: 126px; border: 0; background: transparent; }
    [data-testid="stFileUploaderDropzoneInstructions"] { color: var(--pr-muted); }
    [data-testid="stFileUploaderDropzoneInstructions"] > div:first-child { color: var(--pr-ink); font-weight: 800; }
    [data-testid="stFileUploaderDropzoneInstructions"] small { color: var(--pr-subtle); }
    [data-testid="stFileUploaderDropzone"] button {
        border: 1px solid #c9d9ff;
        border-radius: 9px;
        background: #ffffff;
        color: var(--pr-blue);
        font-size: 0.78rem;
        font-weight: 800;
    }
    .pr-ready-state { display: flex; align-items: center; gap: 0.85rem; margin-top: 1rem; padding: 0.95rem 1rem; border: 1px solid #dce8f7; border-radius: 13px; background: var(--pr-sky-soft); color: var(--pr-muted); font-size: 0.86rem; line-height: 1.45; }
    .pr-ready-state strong { display: block; margin-bottom: 0.12rem; color: var(--pr-ink); font-size: 0.9rem; }
    .pr-ready-check { display: grid; place-items: center; width: 1.9rem; height: 1.9rem; border-radius: 50%; background: var(--pr-blue); color: #ffffff; }
    .pr-ready-check .pr-icon { width: 1rem; height: 1rem; stroke-width: 2.5; }
    .pr-source-bar { display: flex; align-items: center; justify-content: space-between; gap: 1.2rem; margin-bottom: 1.35rem; padding: 0.8rem 1rem; border: 1px solid #cfe3fa; border-radius: 14px; background: var(--pr-sky); }
    .pr-source-main, .pr-source-status { display: flex; align-items: center; gap: 0.75rem; }
    .pr-source-file-icon { display: grid; place-items: center; width: 2rem; height: 2rem; border-radius: 9px; background: #ffffff; color: var(--pr-blue); }
    .pr-source-file-icon .pr-icon { width: 1.2rem; height: 1.2rem; }
    .pr-source-kicker { display: block; color: #58749e; font-family: 'DM Mono', monospace; font-size: 0.63rem; letter-spacing: 0.04em; text-transform: uppercase; }
    .pr-source-name { display: block; max-width: 520px; overflow: hidden; color: var(--pr-ink); font-size: 0.87rem; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
    .pr-source-status { color: #147c61; font-size: 0.77rem; font-weight: 800; }
    .pr-status-dot { width: 0.5rem; height: 0.5rem; border-radius: 50%; background: #19b98c; box-shadow: 0 0 0 4px rgba(25, 185, 140, 0.13); }
    .pr-panel-title { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-bottom: 0.9rem; }
    .pr-panel-title h3 { margin: 0; font-size: 1.2rem; font-weight: 800; letter-spacing: -0.045em; }
    .pr-panel-title p { margin: 0; color: var(--pr-muted); font-size: 0.78rem; }
    .pr-audio-card { margin-bottom: 1rem; padding: 0.78rem 0.9rem; border: 1px solid #ccdcff; border-radius: 13px; background: #f2f6ff; }
    .pr-audio-card-label { display: flex; align-items: center; gap: 0.48rem; margin-bottom: 0.25rem; color: var(--pr-blue); font-size: 0.76rem; font-weight: 800; }
    .pr-audio-card-label .pr-icon { width: 1rem; height: 1rem; }
    [data-testid="stAudio"] { width: 100%; min-height: 36px; }
    audio { width: 100%; height: 34px; }
    .pr-transcript {
        max-height: 470px;
        overflow-y: auto;
        padding: 1.2rem 1.3rem;
        border: 1px solid var(--pr-line);
        border-radius: 15px;
        background: #fbfcfe;
        color: var(--pr-ink-soft);
        font-size: 0.98rem;
        line-height: 1.82;
        white-space: pre-wrap;
    }
    .pr-record-card { display: flex; align-items: center; gap: 0.9rem; min-height: 106px; margin-bottom: 1.1rem; padding: 1rem; border: 1px solid #d9e3ff; border-radius: 15px; background: var(--pr-lavender); }
    .pr-record-mic { display: grid; place-items: center; width: 3.1rem; height: 3.1rem; flex: 0 0 auto; border-radius: 50%; background: var(--pr-blue); color: #ffffff; box-shadow: 0 7px 18px rgba(49, 92, 246, 0.2); }
    .pr-record-mic .pr-icon { width: 1.5rem; height: 1.5rem; }
    .pr-record-copy strong { display: block; color: var(--pr-ink); font-size: 0.85rem; }
    .pr-record-copy span { display: block; margin-top: 0.25rem; color: var(--pr-muted); font-size: 0.75rem; line-height: 1.4; }
    [data-testid="stAudioInput"] { width: 100%; }
    [data-testid="stAudioInput"] > div,
    [data-testid="stAudioInput"] > div > div,
    [data-testid="stAudioInput"] > div > div > div {
        background: #f2f6ff !important;
    }
    [data-testid="stAudioInput"] > div > div {
        border: 1px solid #d9e3ff !important;
        border-radius: 12px !important;
    }
    [data-testid="stAudioInput"] .progress { background: #c5d8ff !important; }
    [data-testid="stAudioInput"] .cursor { background: var(--pr-blue) !important; }
    [data-testid="stAudioInput"] button { color: var(--pr-blue) !important; background: transparent !important; border: 0 !important; }
    .pr-field-label { margin: 0 0 0.45rem; color: var(--pr-ink); font-size: 0.78rem; font-weight: 800; }
    textarea, input {
        border: 1px solid var(--pr-line-strong) !important;
        border-radius: 12px !important;
        background: #ffffff !important;
        color: var(--pr-ink) !important;
        font-family: 'Manrope', sans-serif !important;
        font-size: 0.86rem !important;
    }
    textarea:focus, input:focus { border-color: #96b4ff !important; box-shadow: 0 0 0 3px rgba(49, 92, 246, 0.10) !important; }
    textarea::placeholder, input::placeholder { color: #98a2b3 !important; opacity: 1 !important; }
    div.stButton > button {
        width: 100%;
        min-height: 2.65rem;
        border: 1px solid var(--pr-blue);
        border-radius: 11px;
        background: var(--pr-blue);
        color: #ffffff;
        font-size: 0.82rem;
        font-weight: 800;
        transition: transform 160ms ease, background 160ms ease, box-shadow 160ms ease;
    }
    div.stButton > button { color: #ffffff !important; }
    div.stButton > button p { color: #ffffff !important; }
    div.stButton > button span { color: #ffffff !important; }
    div.stButton > button:hover { border-color: var(--pr-blue-dark); background: var(--pr-blue-dark); box-shadow: 0 9px 18px rgba(49, 92, 246, 0.16); transform: translateY(-1px); }
    div.stButton > button:disabled { border-color: #d9e0ea; background: #eef1f5; color: #98a2b3 !important; box-shadow: none; transform: none; }
    div.stButton > button:disabled p { color: #98a2b3 !important; }
    div.stButton > button:disabled span { color: #98a2b3 !important; }
    div[data-testid="stDownloadButton"] > button {
        width: 100%;
        min-height: 2.4rem;
        margin-top: 0.75rem;
        border: 1px solid #c9d9ff;
        border-radius: 11px;
        background: #f4f9ff;
        color: var(--pr-blue) !important;
        font-size: 0.78rem;
        font-weight: 800;
    }
    div[data-testid="stDownloadButton"] > button p { color: var(--pr-blue) !important; }
    div[data-testid="stDownloadButton"] > button span { color: var(--pr-blue) !important; }
    div[data-testid="stDownloadButton"] > button:hover { border-color: #9fbaff; background: var(--pr-lavender); }
    .pr-answer-card { margin-top: 1rem; padding: 1.1rem 1.15rem; border: 1px solid #bfe9db; border-radius: 15px; background: var(--pr-mint); }
    .pr-answer-head { display: flex; align-items: center; justify-content: space-between; gap: 0.8rem; margin-bottom: 0.65rem; color: #147c61; font-size: 0.8rem; font-weight: 800; }
    .pr-answer-head span { display: inline-flex; align-items: center; gap: 0.45rem; }
    .pr-answer-head .pr-icon { width: 1rem; height: 1rem; }
    .pr-answer-copy { color: #184d42; font-size: 0.88rem; line-height: 1.65; }
    .pr-answer-foot { display: flex; align-items: center; gap: 0.45rem; margin-top: 0.85rem; padding-top: 0.7rem; border-top: 1px solid rgba(20, 124, 97, 0.18); color: #287b68; font-family: 'DM Mono', monospace; font-size: 0.66rem; }
    .pr-answer-foot .pr-icon { width: 0.95rem; height: 0.95rem; }
    .pr-heard { margin: 0.65rem 0 0; color: var(--pr-muted); font-size: 0.75rem; font-style: italic; }
    .pr-footer { display: flex; justify-content: space-between; gap: 1rem; margin-top: 4rem; padding-top: 1.2rem; border-top: 1px solid var(--pr-line); color: var(--pr-subtle); font-size: 0.73rem; }

    [data-testid="stSidebar"] { border-right: 1px solid var(--pr-line); background: #fbfcff; }
    [data-testid="stSidebar"] * { color: var(--pr-ink); }
    [data-testid="stSidebar"] .stButton > button { background: #ffffff; color: var(--pr-blue) !important; border-color: #c9d9ff; box-shadow: none; }
    [data-testid="stSidebar"] .stButton > button p,
    [data-testid="stSidebar"] .stButton > button span { color: var(--pr-blue) !important; }
    [data-testid="stSidebar"] .stButton > button:hover { background: var(--pr-lavender); border-color: #9fbaff; }
    .pr-sidebar-title { padding: 1rem 0 0.3rem; color: var(--pr-ink); font-size: 1.1rem; font-weight: 800; letter-spacing: -0.04em; }
    .pr-sidebar-copy { color: var(--pr-muted); font-size: 0.77rem; line-height: 1.5; }
    .pr-sidebar-note { margin-top: 1.2rem; padding-top: 1rem; border-top: 1px solid var(--pr-line); color: var(--pr-muted); font-size: 0.72rem; line-height: 1.55; }

    @media (max-width: 980px) {
        .pr-hero { grid-template-columns: 1fr; gap: 3.2rem; padding-top: 2.9rem; }
        .pr-hero-copy h1 { max-width: 720px; }
        .pr-hero-copy p { max-width: 620px; }
        .pr-product-preview { max-width: 760px; }
        .pr-section-intro { align-items: start; flex-direction: column; gap: 0.8rem; }
    }
    @media (max-width: 720px) {
        [data-testid="stMainBlockContainer"], .block-container { padding-left: 1rem; padding-right: 1rem; }
        .pr-topbar { flex-wrap: wrap; gap: 1rem; }
        .pr-nav { order: 3; width: 100%; justify-content: space-between; gap: 1rem; margin-left: 0; padding-top: 0.4rem; }
        .pr-nav-cta { margin-left: auto; }
        .pr-hero { padding: 2.5rem 0 3.8rem; }
        .pr-hero-copy h1 { font-size: clamp(3rem, 14vw, 4.6rem); }
        .pr-hero-copy p { font-size: 0.96rem; }
        .pr-preview-body { grid-template-columns: 1fr; }
        .pr-preview-document { min-height: 260px; }
        .pr-preview-agent { min-height: 300px; }
        .pr-process-section { padding-top: 3.3rem; padding-bottom: 3.5rem; }
        .pr-process-grid { grid-template-columns: 1fr; gap: 2.2rem; }
        .pr-step:not(:last-child)::after { top: auto; right: auto; bottom: -1.35rem; left: 1.55rem; width: 1px; height: 1.2rem; }
        .pr-upload-head, .pr-source-bar, .pr-footer { align-items: start; flex-direction: column; }
        .pr-source-status { align-self: flex-start; }
        .pr-source-name { max-width: 290px; }
        .pr-panel-title { align-items: start; flex-direction: column; gap: 0.3rem; }
        .pr-transcript { max-height: 360px; font-size: 0.9rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&family=DM+Serif+Display:ital@0;1&display=swap');

    :root {
        --pr-canvas: #060816;
        --pr-panel: rgba(12, 17, 38, 0.76);
        --pr-panel-solid: #0d1228;
        --pr-panel-raised: #141b38;
        --pr-ink: #f5f5ff;
        --pr-ink-soft: #c8cce3;
        --pr-muted: #9198bb;
        --pr-subtle: #6b7296;
        --pr-blue: #7888ff;
        --pr-blue-dark: #5e70f0;
        --pr-sky: #1b3565;
        --pr-sky-soft: #101d3c;
        --pr-lavender: #25224f;
        --pr-mint: #102f35;
        --pr-line: rgba(174, 187, 255, 0.15);
        --pr-line-strong: rgba(174, 187, 255, 0.31);
        --pr-white: #ffffff;
        --pr-shadow: 0 28px 80px rgba(0, 0, 0, 0.42);
    }

    html { background: var(--pr-canvas); }
    .stApp {
        position: relative;
        min-height: 100vh;
        overflow: visible;
        background:
            radial-gradient(ellipse 52% 30% at 76% 5%, rgba(75, 103, 255, 0.29), transparent 72%),
            radial-gradient(ellipse 38% 22% at 37% 21%, rgba(57, 185, 255, 0.15), transparent 72%),
            radial-gradient(ellipse 26% 20% at 71% 51%, rgba(126, 64, 255, 0.12), transparent 76%),
            var(--pr-canvas);
        color: var(--pr-ink);
    }
    .stApp::before {
        position: fixed;
        z-index: 0;
        top: -18vh;
        left: 34%;
        width: 54vw;
        height: 64vh;
        border-radius: 50%;
        background: linear-gradient(122deg, transparent 32%, rgba(98, 217, 255, 0.09) 49%, rgba(130, 94, 255, 0.16) 59%, transparent 76%);
        content: '';
        filter: blur(22px);
        opacity: .95;
        pointer-events: none;
        transform: rotate(-12deg);
        animation: pr-drift 14s ease-in-out infinite alternate;
    }
    @keyframes pr-drift { to { transform: rotate(-6deg) translate3d(2vw, 2vh, 0) scale(1.06); } }
    [data-testid="stAppViewContainer"] { position: relative !important; min-height: 100vh; overflow: visible !important; background: transparent; }
    [data-testid="stHeader"] { background: transparent; }
    [data-testid="stBaseButton-header"] { display: none !important; }
    [data-testid="stHeader"], [data-testid="stToolbar"] { position: relative; z-index: 2; }
    [data-testid="stMainBlockContainer"], .block-container { position: relative; z-index: 1; max-width: 1280px; padding-top: .65rem; padding-bottom: 4rem; }
    h1, h2, h3, h4, p, label, button, input, textarea, [data-testid="stMarkdownContainer"] { font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
    h1, h2, h3, h4, p { color: var(--pr-ink); }

    .pr-topbar { min-height: 68px; padding: .78rem 0 1.15rem; border-bottom: 1px solid var(--pr-line); }
    .pr-brand { color: var(--pr-ink); font-size: 1.15rem; font-weight: 700; letter-spacing: -0.045em; }
    nav.pr-topbar a.pr-brand, nav.pr-topbar a.pr-brand:hover { color: var(--pr-ink) !important; }
    .pr-brand-mark { width: 34px; height: 34px; border: 1px solid rgba(128, 145, 255, 0.48); border-radius: 10px; background: linear-gradient(145deg, rgba(124, 140, 255, .32), rgba(39, 211, 255, .08)); color: #aab6ff; box-shadow: inset 0 1px 0 rgba(255,255,255,.13), 0 0 24px rgba(100, 126, 255, .18); }
    .pr-nav { gap: 1.8rem; }
    .pr-nav a { color: var(--pr-muted); font-size: .8rem; font-weight: 600; }
    .pr-nav a:hover { color: #c4cbff; }
    .pr-nav-cta, .pr-primary-cta { border: 1px solid rgba(160, 174, 255, .48); border-radius: 10px; background: linear-gradient(110deg, #6077f6, #896bff); color: white !important; box-shadow: 0 10px 30px rgba(92, 107, 255, .26), inset 0 1px 0 rgba(255,255,255,.22); }
    .pr-nav-cta { min-height: 2.55rem; padding: .5rem 1rem; font-size: .78rem; }
    .pr-primary-cta { min-height: 3.2rem; padding: .75rem 1.28rem; font-size: .89rem; }
    .pr-nav-cta:hover, .pr-primary-cta:hover { border-color: #b9c3ff; background: linear-gradient(110deg, #7187ff, #9c7cff); box-shadow: 0 15px 35px rgba(92, 107, 255, .34); transform: translateY(-2px); }

    .pr-hero { grid-template-columns: minmax(0, 1.05fr) minmax(460px, .95fr); gap: clamp(2.5rem, 3.5vw, 4.25rem); min-height: 530px; padding: 4.7rem 0 4.6rem; }
    .pr-hero-copy h1 { max-width: 620px; color: var(--pr-ink); font-family: 'DM Serif Display', Georgia, serif; font-size: clamp(3.8rem, 4.4vw, 5.1rem); font-weight: 400; letter-spacing: -.052em; line-height: .92; }
    .pr-hero-copy h1 span { margin-top: .12em; background: linear-gradient(105deg, #a18dff 8%, #9bb3ff 58%, #a6e8ff); -webkit-background-clip: text; background-clip: text; color: transparent; }
    .pr-hero-copy p { max-width: 455px; margin: 1.75rem 0 2.15rem; color: #bbc2e3; font-size: 1.03rem; line-height: 1.7; }
    .pr-hero-wave { z-index: 0; right: -3.4rem; bottom: -2rem; opacity: .28; }
    .pr-hero-wave path:first-child { stroke: #6f8aff; }
    .pr-hero-wave path:last-child { stroke: #8cdeff; }

    .pr-product-preview { border: 1px solid rgba(158, 176, 255, .23); border-radius: 15px; background: linear-gradient(145deg, rgba(17, 28, 60, .91), rgba(7, 12, 28, .92)); box-shadow: var(--pr-shadow), 0 0 0 1px rgba(120, 138, 255, .06), inset 0 1px 0 rgba(255,255,255,.08); }
    .pr-product-preview::before { top: -7rem; right: -1rem; width: 21rem; height: 18rem; background: radial-gradient(circle, rgba(99, 140, 255, .38), transparent 66%); filter: blur(11px); }
    .pr-product-preview::after { position: absolute; z-index: 0; right: 12%; bottom: -16%; width: 60%; height: 36%; border-radius: 50%; background: rgba(91, 100, 255, .18); content: ''; filter: blur(42px); pointer-events: none; }
    .pr-preview-toolbar { min-height: 3.5rem; border-bottom-color: var(--pr-line); background: rgba(7, 12, 29, .7); }
    .pr-preview-toolbar-brand, .pr-preview-file { color: var(--pr-ink); }
    .pr-preview-toolbar-brand { font-size: .9rem; }
    .pr-preview-toolbar-brand .pr-icon, .pr-preview-file .pr-icon { color: #94a5ff; }
    .pr-preview-file { color: #a7afd1; font-size: .72rem; }
    .pr-preview-menu { color: #7d86aa; }
    .pr-preview-body { position: relative; z-index: 1; gap: .7rem; padding: .7rem; }
    .pr-preview-document, .pr-preview-agent { min-height: 340px; border-color: rgba(161, 178, 255, .16); border-radius: 11px; background: rgba(7, 12, 28, .65); }
    .pr-preview-document { grid-template-columns: 52px minmax(0,1fr); }
    .pr-preview-rail { border-right-color: rgba(161, 178, 255, .14); background: rgba(17, 26, 54, .65); }
    .pr-preview-thumb { border-color: rgba(151, 174, 255, .15); border-radius: 6px; background: linear-gradient(145deg, #101a3d, #0a1025); color: #7783ad; }
    .pr-preview-thumb.is-active { border-color: #7d91ff; background: linear-gradient(145deg, #263a7f, #1a1e55); color: #dfe3ff; box-shadow: 0 0 18px rgba(112, 134, 255, .28); }
    .pr-preview-page { position: relative; overflow: hidden; padding: 1.5rem; background: linear-gradient(160deg, #f7f7ff 0%, #dfe7ff 62%, #bac8fa 100%); }
    .pr-preview-page::after { position: absolute; right: -1.5rem; bottom: -3.5rem; width: 16rem; height: 11rem; border-radius: 50% 45% 0 0; background: linear-gradient(135deg, #223878, #5a75c7 55%, #211b56); content: ''; clip-path: polygon(0 78%, 24% 45%, 39% 63%, 59% 17%, 76% 52%, 100% 0, 100% 100%, 0 100%); opacity: .94; }
    .pr-preview-page-title { position: relative; z-index: 1; max-width: 165px; color: #121b40; font-family: 'DM Serif Display', Georgia, serif; font-size: 2rem; font-weight: 400; letter-spacing: -.055em; line-height: .93; }
    .pr-preview-page-copy { position: relative; z-index: 1; color: #3c4c7d; font-size: .65rem; }
    .pr-preview-page-line { position: relative; z-index: 1; background: rgba(73, 91, 145, .21); }
    .pr-preview-agent { padding: 1rem; background: rgba(8, 13, 32, .84); }
    .pr-preview-agent-tabs { border-bottom-color: rgba(161, 178, 255, .15); color: #7f89ad; font-size: .66rem; }
    .pr-preview-agent-tabs .is-active { color: #aab6ff; }
    .pr-preview-mic-area { min-height: 154px; background: radial-gradient(circle at 50% 50%, rgba(95, 110, 255, .34), transparent 55%), #10173b; }
    .pr-preview-mic { border-color: rgba(171, 184, 255, .24); background: linear-gradient(145deg, #7184ff, #725ddd); box-shadow: 0 0 30px rgba(113, 127, 255, .45); }
    .pr-waveform span { background: #8fb0ff; }
    .pr-preview-question { border-color: rgba(170, 187, 255, .2); background: rgba(21, 30, 62, .7); color: #a5afd1; }
    .pr-preview-answer { background: rgba(26, 75, 88, .45); color: #b4f1e4; }
    .pr-preview-answer-lines span { background: rgba(154, 244, 223, .22); }

    .pr-process-section { margin-top: 0; border-top-color: var(--pr-line); border-bottom-color: var(--pr-line); background: linear-gradient(90deg, rgba(17, 24, 53, .68), rgba(8, 13, 32, .18), rgba(24, 17, 59, .48)); }
    .pr-step:not(:last-child)::after { background: rgba(149, 164, 255, .36); }
    .pr-step-icon { border-color: rgba(148, 165, 255, .25); border-radius: 12px; background: linear-gradient(145deg, rgba(88, 117, 250, .22), rgba(77, 198, 255, .08)); color: #a7b5ff; }
    .pr-step-index, .pr-section-label { color: #a5b4ff; }
    .pr-step h3 { color: var(--pr-ink); }
    .pr-step p, .pr-section-intro p { color: var(--pr-muted); }
    .pr-section-intro { margin-top: 5.3rem; }
    .pr-section-intro h2 { font-family: 'DM Serif Display', Georgia, serif; color: var(--pr-ink); font-size: clamp(2.35rem, 3.5vw, 3.4rem); font-weight: 400; letter-spacing: -.045em; }

    div[data-testid="stVerticalBlockBorderWrapper"] { border-color: rgba(159, 176, 255, .18) !important; border-radius: 16px !important; background: linear-gradient(145deg, rgba(16, 23, 51, .86), rgba(8, 12, 29, .82)) !important; box-shadow: var(--pr-shadow), inset 0 1px 0 rgba(255,255,255,.045); }
    div[data-testid="stVerticalBlockBorderWrapper"] > div { border-radius: 16px !important; }
    .pr-upload-head h3, .pr-panel-title h3 { color: var(--pr-ink); font-family: 'DM Serif Display', Georgia, serif; font-weight: 400; letter-spacing: -.035em; }
    .pr-upload-head p, .pr-panel-title p { color: var(--pr-muted); }
    .pr-upload-icon { border: 1px solid rgba(150, 169, 255, .2); background: rgba(110, 125, 255, .16); color: #afbbff; }
    [data-testid="stFileUploader"] { border-color: rgba(125, 149, 255, .48); background: rgba(9, 15, 37, .62); }
    [data-testid="stFileUploaderDropzoneInstructions"] { color: var(--pr-muted); }
    [data-testid="stFileUploaderDropzoneInstructions"] > div:first-child { color: var(--pr-ink); }
    [data-testid="stFileUploaderDropzone"] button { border-color: rgba(142, 159, 255, .42); background: rgba(108, 126, 255, .16); color: #bdc7ff; }
    .pr-ready-state { border-color: rgba(147, 168, 255, .2); background: rgba(23, 36, 77, .62); color: var(--pr-muted); }
    .pr-ready-state strong { color: var(--pr-ink); }
    .pr-ready-check { background: linear-gradient(145deg, #7a8dff, #755fe0); }
    .pr-source-bar { border-color: rgba(141, 164, 255, .24); background: linear-gradient(90deg, rgba(33, 57, 113, .65), rgba(19, 28, 65, .7)); }
    .pr-source-file-icon { background: rgba(125, 143, 255, .18); color: #b8c3ff; }
    .pr-source-kicker { color: #a7b8ee; }
    .pr-source-name, .pr-field-label { color: var(--pr-ink); }
    .pr-source-status { color: #88e5ce; }
    .pr-status-dot { background: #65dfbd; box-shadow: 0 0 0 4px rgba(101, 223, 189, .12); }
    .pr-audio-card { border-color: rgba(136, 159, 255, .23); background: rgba(32, 47, 105, .55); }
    .pr-audio-card-label { color: #b3c0ff; }
    .pr-transcript { border-color: var(--pr-line); background: rgba(5, 9, 23, .58); color: #c2c8e2; }
    .pr-record-card { border-color: rgba(141, 160, 255, .24); background: linear-gradient(125deg, rgba(58, 52, 123, .62), rgba(19, 28, 67, .68)); }
    .pr-record-mic { background: linear-gradient(145deg, #7e8fff, #6c58e0); box-shadow: 0 9px 23px rgba(103, 112, 255, .35); }
    .pr-record-copy strong { color: var(--pr-ink); }
    .pr-record-copy span, .pr-heard { color: var(--pr-muted); }
    [data-testid="stAudioInput"] > div, [data-testid="stAudioInput"] > div > div, [data-testid="stAudioInput"] > div > div > div { background: rgba(14, 21, 49, .94) !important; }
    [data-testid="stAudioInput"] > div > div { border-color: rgba(141, 160, 255, .28) !important; }
    [data-testid="stAudioInput"] button { color: #aebaff !important; }
    textarea, input { border-color: rgba(148, 165, 255, .3) !important; background: rgba(6, 10, 25, .66) !important; color: var(--pr-ink) !important; }
    textarea:focus, input:focus { border-color: #8294ff !important; box-shadow: 0 0 0 3px rgba(114, 133, 255, .16) !important; }
    textarea::placeholder, input::placeholder { color: #717a9e !important; }
    div.stButton > button { border-color: rgba(160, 174, 255, .46); border-radius: 10px; background: linear-gradient(110deg, #657cf5, #856afb); box-shadow: 0 10px 26px rgba(89, 104, 255, .19), inset 0 1px 0 rgba(255,255,255,.18); }
    div.stButton > button:hover { border-color: #b4c0ff; background: linear-gradient(110deg, #7288ff, #9679ff); box-shadow: 0 14px 30px rgba(89, 104, 255, .32); }
    div.stButton > button:disabled { border-color: rgba(159, 171, 216, .15); background: #202641; }
    div[data-testid="stDownloadButton"] > button { border-color: rgba(141, 160, 255, .33); background: rgba(47, 61, 123, .42); color: #b8c4ff !important; }
    div[data-testid="stDownloadButton"] > button p, div[data-testid="stDownloadButton"] > button span { color: #b8c4ff !important; }
    div[data-testid="stDownloadButton"] > button:hover { border-color: rgba(172, 188, 255, .54); background: rgba(77, 86, 171, .52); }
    .pr-answer-card { border-color: rgba(104, 227, 195, .28); background: linear-gradient(140deg, rgba(13, 65, 72, .74), rgba(11, 38, 54, .78)); }
    .pr-answer-head { color: #91ebd4; }
    .pr-answer-copy { color: #d1eee9; }
    .pr-answer-foot { border-top-color: rgba(136, 242, 215, .18); color: #8ed7ca; }
    .pr-footer { border-top-color: var(--pr-line); color: var(--pr-subtle); }
    a[aria-label="Link to heading"] { display: none !important; }

    [data-testid="stSidebar"] { border-right-color: var(--pr-line); background: #080c1d; }
    [data-testid="stSidebar"] * { color: var(--pr-ink); }
    [data-testid="stSidebar"] .stButton > button { border-color: rgba(144, 161, 255, .33); background: rgba(58, 73, 149, .38); color: #b9c5ff !important; box-shadow: none; }
    [data-testid="stSidebar"] .stButton > button p, [data-testid="stSidebar"] .stButton > button span { color: #b9c5ff !important; }
    [data-testid="stSidebar"] .stButton > button:hover { background: rgba(90, 104, 205, .43); }
    .pr-sidebar-title { color: var(--pr-ink); font-family: 'DM Serif Display', Georgia, serif; font-weight: 400; }
    .pr-sidebar-copy, .pr-sidebar-note { color: var(--pr-muted); }
    .pr-sidebar-note { border-top-color: var(--pr-line); }

    @media (max-width: 980px) { .pr-hero { grid-template-columns: 1fr; min-height: auto; padding-top: 4rem; } .pr-product-preview { max-width: 800px; } }
    @media (max-width: 720px) {
        .pr-topbar { padding-bottom: 1rem; }
        .pr-hero { padding: 3.4rem 0 4rem; }
        .pr-hero-copy h1 { font-size: clamp(3.4rem, 16vw, 5rem); }
        .pr-nav { gap: .8rem; }
        .pr-process-section { background: rgba(13, 20, 46, .62); }
        .pr-preview-page::after { width: 12rem; }
    }
    @media (prefers-reduced-motion: reduce) { .stApp::before { animation: none; } *, *::before, *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; } }
    </style>
    """,
    unsafe_allow_html=True,
)


with st.sidebar:
    st.markdown(f'<div class="pr-brand"><span class="pr-brand-mark">{icon("wave", 22)}</span>Pitchroom</div>', unsafe_allow_html=True)
    st.markdown('<div class="pr-sidebar-title">Session setup</div>', unsafe_allow_html=True)
    st.markdown('<div class="pr-sidebar-copy">The workspace is connected to the approved pitch service for this demo.</div>', unsafe_allow_html=True)
    if ALLOW_CUSTOM_BACKEND_URL:
        st.session_state.backend_url = st.text_input(
            "Backend URL",
            value=st.session_state.backend_url,
            help="Developer setting. Use only a trusted FastAPI service URL.",
        ).rstrip("/")
    if st.button("Check connection", use_container_width=True):
        try:
            health_response = api_request("GET", "/health", timeout=8)
            if health_response.ok:
                health = health_response.json()
                speech_ready = bool(health.get("huggingface_configured")) and health.get("speech_provider") != "none"
                st.success("Backend is online")
                if speech_ready:
                    st.caption(f"Voice stack configured: transcription + {health['speech_provider']} speech.")
                else:
                    st.warning("Text answers are ready; configure transcription and speech before a voice demo.")
            else:
                show_api_error(health_response)
        except requests.RequestException as exc:
            st.error(f"Could not reach backend: {exc}")
    st.markdown(
        '<div class="pr-sidebar-note">Upload an approved pitch deck as PDF, Markdown, or plain text. Answers stay grounded in the source document.</div>',
        unsafe_allow_html=True,
    )


st.markdown(
    f'''
    <nav class="pr-topbar" aria-label="Primary navigation">
        <a class="pr-brand" href="#top" aria-label="Pitchroom home">
            <span class="pr-brand-mark">{icon("wave", 22)}</span>
            <span>Pitchroom</span>
        </a>
        <div class="pr-nav">
            <a href="#how-it-works">How it works</a>
            <a href="#workspace">Workspace</a>
        </div>
        <a class="pr-nav-cta" href="#workspace">Open workspace {icon("arrow", 15, 2.1)}</a>
    </nav>
    <div id="top" class="pr-anchor"></div>
    <section class="pr-hero" aria-labelledby="hero-heading">
        <div class="pr-hero-copy">
            <h1 id="hero-heading">Know your pitch.<span>Own the room.</span></h1>
            <p>Turn your pitch into a conversation worth remembering. Hear the story, surface the detail, and walk into every room prepared.</p>
            <a class="pr-primary-cta" href="#workspace">Open workspace {icon("arrow", 18, 2.1)}</a>
            <svg class="pr-hero-wave" viewBox="0 0 420 92" fill="none" aria-hidden="true">
                <path d="M2 56C41 27 70 25 108 49c37 24 62 34 89 22 28-12 42-47 68-48 27-1 37 43 65 50 28 7 48-27 87-47" stroke="#c7e2ff" stroke-width="2" stroke-linecap="round"/>
                <path d="M0 75c35-13 66-8 95 4 29 12 59 19 86 5 28-14 39-43 63-44 25-1 42 35 68 39 28 4 48-17 106-45" stroke="#e1efff" stroke-width="2" stroke-linecap="round"/>
            </svg>
        </div>
        <div class="pr-product-preview" aria-label="Pitchroom product preview">
            <div class="pr-preview-toolbar">
                <div class="pr-preview-toolbar-brand">{icon("wave", 20, 2.2)} Pitchroom</div>
                <div class="pr-preview-file">{icon("file", 16)} Q3 Growth Deck.pdf</div>
                <div class="pr-preview-menu" aria-hidden="true">•••</div>
            </div>
            <div class="pr-preview-body">
                <div class="pr-preview-document">
                    <div class="pr-preview-rail">
                        <div class="pr-preview-thumb is-active">01</div>
                        <div class="pr-preview-thumb">02</div>
                        <div class="pr-preview-thumb">03</div>
                        <div class="pr-preview-thumb">04</div>
                    </div>
                    <div class="pr-preview-page">
                        <div class="pr-preview-page-title">Go to<br>market</div>
                        <div class="pr-preview-page-copy">A focused, scalable path from pilot to category leadership.</div>
                        <div class="pr-preview-page-line"></div>
                        <div class="pr-preview-page-line" style="width:54%"></div>
                    </div>
                </div>
                <div class="pr-preview-agent">
                    <div class="pr-preview-agent-tabs"><span class="is-active">{icon("mic", 14)} Talk with the pitch agent</span><span>Transcript</span></div>
                    <div class="pr-preview-mic-area">
                        <div>
                            {waveform([9, 16, 27, 15, 34, 20, 11, 26, 14, 8], "pr-waveform-blue")}
                            <div class="pr-preview-mic">{icon("mic", 28, 1.6)}</div>
                            {waveform([8, 14, 24, 35, 18, 29, 15, 10], "pr-waveform-blue")}
                        </div>
                    </div>
                    <div class="pr-preview-question">Ask the pitch</div>
                    <div class="pr-preview-answer">{icon("file", 15)} Answer from source<div class="pr-preview-answer-lines"><span></span><span></span><span></span></div></div>
                </div>
            </div>
        </div>
    </section>
    <div id="how-it-works" class="pr-anchor"></div>
    <section class="pr-process-section" aria-labelledby="process-heading">
        <div class="pr-process-grid">
            <div class="pr-step">
                <div class="pr-step-icon">{icon("upload", 25, 1.9)}</div>
                <div class="pr-step-index">01</div>
                <h3>Load the pitch deck</h3>
                <p>PDF, Markdown, or plain text.</p>
            </div>
            <div class="pr-step">
                <div class="pr-step-icon">{icon("wave", 25, 2.1)}</div>
                <div class="pr-step-index">02</div>
                <h3>Read it aloud</h3>
                <p>Playback starts after extraction completes.</p>
            </div>
            <div class="pr-step">
                <div class="pr-step-icon">{icon("message", 25, 1.9)}</div>
                <div class="pr-step-index">03</div>
                <h3>Ask the room</h3>
                <p>Ask the questions the room is already thinking.</p>
            </div>
        </div>
    </section>
    ''',
    unsafe_allow_html=True,
)


st.markdown('<div id="workspace" class="pr-anchor"></div>', unsafe_allow_html=True)
pitch = st.session_state.pitch

if pitch is None:
    st.markdown(
        '''
        <div class="pr-section-intro">
            <div>
                <p class="pr-section-label">Workspace</p>
                <h2>Pitch document</h2>
            </div>
            <p>Bring the approved source into a focused space for playback and grounded questions.</p>
        </div>
        ''',
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        st.markdown(
            f'''
            <div class="pr-upload-head">
                <div>
                <h3>Put the story on the table.</h3>
                    <p>Upload a PDF, Markdown, or plain-text file. The source stays at the center of every answer.</p>
                </div>
                <div class="pr-upload-icon">{icon("upload", 22, 1.9)}</div>
            </div>
            ''',
            unsafe_allow_html=True,
        )
        demo_col, upload_col = st.columns([0.9, 1.1], gap="medium")
        with demo_col:
            st.caption("Demo-ready source")
            st.write("Open the included fact sheet to rehearse the complete flow before loading your own approved pitch.")
            if st.button("Load demo source", use_container_width=True, key="load_demo_source"):
                if load_demo_pitch():
                    st.rerun()
        with upload_col:
            st.caption("Use your own source")
            uploaded_file = st.file_uploader(
                "Upload a text-based PDF, Markdown, or plain-text file",
                type=["pdf", "md", "txt"],
                label_visibility="collapsed",
                key="pitch_file",
            )
            if uploaded_file is not None:
                process_uploaded_file(uploaded_file)
        if st.session_state.pitch is None:
            st.markdown(
                f'''
                <div class="pr-ready-state">
                    <span class="pr-ready-check">{icon("check", 15, 2.4)}</span>
                    <div><strong>Ready when you are</strong>Load the demo source or upload an approved document to open its transcript and Q&amp;A workspace.</div>
                </div>
                ''',
                unsafe_allow_html=True,
            )
else:
    st.markdown(
        '''
        <div class="pr-section-intro">
            <div>
                <p class="pr-section-label">Workspace</p>
                <h2>Keep the story close.</h2>
            </div>
            <p>Review the approved source, hear it aloud, and ask the pitch agent for the detail you need.</p>
        </div>
        ''',
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        # The backend may report an absolute local path for the bundled demo
        # source.  Present only the filename; judges need provenance, not a
        # developer workstation path.
        source = escape(Path(str(pitch["source"])).name or "Approved pitch source")
        st.markdown(
            f'''
            <div class="pr-source-bar">
                <div class="pr-source-main">
                    <span class="pr-source-file-icon">{icon("file", 19)}</span>
                    <div><span class="pr-source-kicker">Source loaded</span><span class="pr-source-name">{source}</span></div>
                </div>
                <div class="pr-source-status"><span class="pr-status-dot"></span>{len(pitch["chunks"])} readable sections</div>
            </div>
            ''',
            unsafe_allow_html=True,
        )

        transcript_col, ask_col = st.columns([1.1, 0.9], gap="large")
        with transcript_col:
            st.markdown(
                f'<div class="pr-panel-title"><h3>Pitch transcript</h3><p>{len(pitch["text"]):,} characters</p></div>',
                unsafe_allow_html=True,
            )
            if st.button("Read pitch aloud", use_container_width=True, key="read_pitch_aloud"):
                read_loaded_pitch()
            if st.session_state.pitch_audio is not None:
                st.markdown(
                    f'<div class="pr-audio-card"><div class="pr-audio-card-label">{icon("play", 16)} Read it aloud</div>',
                    unsafe_allow_html=True,
                )
                st.audio(
                    st.session_state.pitch_audio,
                    format=st.session_state.pitch_audio_format or "audio/wav",
                    autoplay=False,
                )
                st.markdown("</div>", unsafe_allow_html=True)
            elif st.session_state.pitch_audio_error:
                st.warning(f"Pitch loaded, but narration was unavailable: {st.session_state.pitch_audio_error}")
            st.markdown(
                f'<div class="pr-transcript">{escape(str(pitch["text"]))}</div>',
                unsafe_allow_html=True,
            )
            st.download_button(
                "Download transcript",
                data=str(pitch["text"]),
                file_name="pitch-transcript.txt",
                mime="text/plain",
                use_container_width=True,
                key="download_transcript",
            )

        with ask_col:
            st.markdown(
                '<div class="pr-panel-title"><h3>Ask the pitch</h3><p>Voice or text</p></div>',
                unsafe_allow_html=True,
            )
            st.caption("Demo questions")
            demo_questions = (
                ("Problem", "What problem does Pitchroom AI solve?"),
                ("Audience", "What kind of teams does Pitchroom AI help?"),
                ("Trust", "How does Pitchroom AI stay trustworthy?"),
            )
            demo_question_columns = st.columns(3, gap="small")
            for column, (label, question_text) in zip(demo_question_columns, demo_questions):
                with column:
                    if st.button(label, use_container_width=True, key=f"demo_question_{label}"):
                        answer_from_question(question_text)
            st.markdown(
                f'''
                <div class="pr-record-card">
                    <span class="pr-record-mic">{icon("mic", 24, 1.7)}</span>
                    <div class="pr-record-copy"><strong>Record a question</strong><span>Pitchroom transcribes your question, answers from the source, and speaks the result back.</span></div>
                </div>
                ''',
                unsafe_allow_html=True,
            )
            voice_recording = st.audio_input("Record a question", disabled=st.session_state.pitch is None)
            if voice_recording is not None:
                process_voice_recording(voice_recording)
                if st.session_state.last_heard_question:
                    st.markdown(
                        f'<p class="pr-heard">Heard: {escape(st.session_state.last_heard_question)}</p>',
                        unsafe_allow_html=True,
                    )

            with st.form("typed_question_form", clear_on_submit=True):
                st.markdown('<div class="pr-field-label">Ask the pitch</div>', unsafe_allow_html=True)
                question = st.text_area(
                    "Ask the pitch",
                    placeholder="What problem does Pitchroom solve?",
                    height=104,
                    label_visibility="collapsed",
                    key="typed_question",
                )
                submitted_question = st.form_submit_button("Answer from source", use_container_width=True)
            if submitted_question:
                if question.strip():
                    answer_from_question(question)
                else:
                    st.warning("Ask a question first.")

            answer = st.session_state.answer
            if answer:
                grounded_status = "Grounded in source" if answer["grounded"] else "No matching source found"
                answer_text = escape(str(answer["answer"]))
                st.markdown(
                    f'''
                    <div class="pr-answer-card">
                        <div class="pr-answer-head"><span>{icon("file", 16)} Answer from source</span><span>{grounded_status}</span></div>
                        <div class="pr-answer-copy">{answer_text}</div>
                        <div class="pr-answer-foot">{icon("file", 14)} {len(answer["sources"])} source section(s) used</div>
                    </div>
                    ''',
                    unsafe_allow_html=True,
                )
                if answer["grounded"] and st.button("Play answer", use_container_width=True, key="play_answer"):
                    try:
                        speak_response = api_request(
                            "POST",
                            "/api/voice/speak",
                            json={"text": answer["answer"]},
                            timeout=90,
                        )
                        if speak_response.ok and speak_response.content:
                            st.session_state.answer_audio = speak_response.content
                            st.session_state.answer_audio_format = response_audio_format(speak_response, "audio/mpeg")
                            st.session_state.answer_audio_error = None
                            st.session_state.answer_audio_autoplay = False
                        else:
                            st.session_state.answer_audio_error = response_detail(speak_response)
                    except (requests.RequestException, TypeError, ValueError) as exc:
                        st.session_state.answer_audio_error = str(exc)
                if st.session_state.answer_audio is not None:
                    st.audio(
                        st.session_state.answer_audio,
                        format=st.session_state.answer_audio_format or "audio/wav",
                        autoplay=st.session_state.answer_audio_autoplay,
                    )
                elif st.session_state.answer_audio_error:
                    st.warning(f"Answer ready, but spoken playback was unavailable: {st.session_state.answer_audio_error}")
                with st.expander("View source sections"):
                    for index, source_section in enumerate(answer["sources"], start=1):
                        st.markdown(f"**{index}.** {escape(str(source_section))}")

        with st.expander("Replace pitch source"):
            replacement_file = st.file_uploader(
                "Choose a new deck or document",
                type=["pdf", "md", "txt"],
                label_visibility="collapsed",
                key="replacement_pitch_file",
            )
            if replacement_file is not None:
                process_uploaded_file(replacement_file)


st.markdown(
    '<div class="pr-footer"><span>Pitchroom / voice-first pitch assistant</span><span class="pr-mono">Source-grounded by design</span></div>',
    unsafe_allow_html=True,
)
