from __future__ import annotations

import os
import hashlib
from html import escape
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import requests
import streamlit as st


load_dotenv(Path(__file__).resolve().parents[1] / ".env")
DEFAULT_BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")

st.set_page_config(
    page_title="Pitchroom | Voice pitch assistant",
    page_icon="P",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&display=swap');

    :root {
        --ink: #17211b;
        --muted: #6c786f;
        --paper: #f3f1e9;
        --panel: #fffdf7;
        --line: #d9ded3;
        --moss: #2f634a;
        --coral: #dd725e;
        --yellow: #e7bb56;
    }

    .stApp {
        background: var(--paper);
        color: var(--ink);
    }

    [data-testid="stHeader"] { background: transparent; }
    [data-testid="stSidebar"] {
        background: #1d3026;
        border-right: 0;
    }
    [data-testid="stSidebar"] * { color: #f4f3e9; }
    [data-testid="stSidebar"] input {
        background: #294334;
        color: #f4f3e9;
        border-color: #4c6855;
    }

    h1, h2, h3, p, label, button { font-family: 'Manrope', sans-serif; }
    h1 { letter-spacing: -0.04em; font-weight: 800; }
    h2 { letter-spacing: -0.03em; font-weight: 800; }
    .mono { font-family: 'DM Mono', monospace; }

    .eyebrow {
        color: var(--coral);
        font-family: 'DM Mono', monospace;
        font-size: 0.72rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin-bottom: 0.65rem;
    }
    .hero {
        border-bottom: 1px solid var(--line);
        padding: 1.6rem 0 1.3rem;
        margin-bottom: 1.6rem;
    }
    .hero p { color: var(--muted); max-width: 660px; font-size: 1rem; }
    .status {
        background: var(--panel);
        border: 1px solid var(--line);
        border-left: 5px solid var(--moss);
        padding: 0.8rem 1rem;
        margin: 0.7rem 0 1.2rem;
    }
    .status strong { display: block; color: var(--moss); }
    .transcript {
        background: var(--panel);
        border: 1px solid var(--line);
        padding: 1.2rem 1.35rem;
        max-height: 440px;
        overflow-y: auto;
        line-height: 1.75;
        white-space: pre-wrap;
    }
    .answer {
        background: #e4eee3;
        border: 1px solid #bed3bf;
        border-left: 5px solid var(--moss);
        padding: 1.1rem 1.25rem;
        line-height: 1.65;
        margin: 0.7rem 0;
    }
    .source {
        color: #506258;
        font-family: 'DM Mono', monospace;
        font-size: 0.75rem;
        border-top: 1px solid #c9d9ca;
        padding-top: 0.65rem;
        margin-top: 0.8rem;
    }
    .small-note { color: var(--muted); font-size: 0.82rem; }
    div.stButton > button {
        border-radius: 2px;
        border: 1px solid var(--moss);
        background: var(--moss);
        color: white;
        font-weight: 700;
        min-height: 2.6rem;
    }
    div.stButton > button:hover { background: #234b38; border-color: #234b38; }
    </style>
    """,
    unsafe_allow_html=True,
)


def api_request(method: str, path: str, *, timeout: int = 45, **kwargs: Any) -> requests.Response:
    url = f"{st.session_state.backend_url}{path}"
    return requests.request(method, url, timeout=timeout, **kwargs)


def show_api_error(response: requests.Response) -> None:
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        detail = response.text
    st.error(f"Backend error ({response.status_code}): {detail or 'Request failed.'}")


if "backend_url" not in st.session_state:
    st.session_state.backend_url = DEFAULT_BACKEND_URL
if "pitch" not in st.session_state:
    st.session_state.pitch = None
if "answer" not in st.session_state:
    st.session_state.answer = None
if "processed_file_hash" not in st.session_state:
    st.session_state.processed_file_hash = None
if "pitch_audio" not in st.session_state:
    st.session_state.pitch_audio = None
if "answer_audio" not in st.session_state:
    st.session_state.answer_audio = None

with st.sidebar:
    st.markdown("<div class='eyebrow'>Pitchroom / control</div>", unsafe_allow_html=True)
    st.header("Session setup")
    st.session_state.backend_url = st.text_input(
        "Backend URL",
        value=st.session_state.backend_url,
        help="The FastAPI service URL, for example http://localhost:8000.",
    ).rstrip("/")
    if st.button("Check connection", use_container_width=True):
        try:
            response = api_request("GET", "/health", timeout=8)
            if response.ok:
                st.success("Backend is online")
            else:
                show_api_error(response)
        except requests.RequestException as exc:
            st.error(f"Could not reach backend: {exc}")
    st.divider()
    st.markdown("<div class='small-note'>Upload an approved pitch deck as PDF, Markdown, or plain text. The backend extracts the source text and keeps answers grounded in it.</div>", unsafe_allow_html=True)

st.markdown("<div class='hero'>", unsafe_allow_html=True)
st.markdown("<div class='eyebrow'>Voice-first pitch assistant</div>", unsafe_allow_html=True)
st.title("Make the pitch easy to hear.")
st.markdown("Upload the deck, let the room hear the story, then ask precise questions without leaving the source document.")
st.markdown("</div>", unsafe_allow_html=True)

upload_col, read_col = st.columns([1.35, 0.65], gap="large")
with upload_col:
    st.subheader("Load the pitch deck")
    uploaded_file = st.file_uploader(
        "Choose a deck or document",
        type=["pdf", "md", "txt"],
        label_visibility="collapsed",
    )
    if uploaded_file is not None:
        uploaded_bytes = uploaded_file.getvalue()
        uploaded_hash = hashlib.sha256(uploaded_bytes).hexdigest()
        if uploaded_hash != st.session_state.processed_file_hash:
            st.session_state.processed_file_hash = uploaded_hash
            st.session_state.pitch = None
            st.session_state.answer = None
            st.session_state.pitch_audio = None
            with st.spinner("Extracting the pitch and starting playback..."):
                try:
                    response = api_request(
                        "POST",
                        "/api/pitch/file",
                        files={"file": (uploaded_file.name, uploaded_bytes, uploaded_file.type or "application/octet-stream")},
                    )
                    if response.ok:
                        pitch_response = api_request("GET", "/api/pitch")
                        if pitch_response.ok:
                            st.session_state.pitch = pitch_response.json()
                            audio_response = api_request("POST", "/api/pitch/read", timeout=90)
                            if audio_response.ok:
                                st.session_state.pitch_audio = audio_response.content
                            else:
                                show_api_error(audio_response)
                        else:
                            show_api_error(pitch_response)
                    else:
                        show_api_error(response)
                except requests.RequestException as exc:
                    st.error(f"Upload or playback failed: {exc}")
            if st.session_state.pitch is not None:
                st.success(f"Extracted {response.json()['characters']:,} characters from {uploaded_file.name}.")

    if st.session_state.pitch_audio is not None:
        st.audio(st.session_state.pitch_audio, format="audio/wav", autoplay=True)

with read_col:
    st.subheader("Read it aloud")
    st.markdown("<div class='small-note'>Playback starts automatically after text extraction completes.</div>", unsafe_allow_html=True)

st.divider()
st.subheader("Talk with the pitch agent")
st.markdown("<div class='small-note'>Record a question. Hugging Face Whisper transcribes it, the pitch agent answers from the document, and the answer is spoken back.</div>", unsafe_allow_html=True)
voice_recording = st.audio_input("Record a question", disabled=st.session_state.pitch is None)
if voice_recording is not None:
    recording_bytes = voice_recording.getvalue()
    recording_hash = hashlib.sha256(recording_bytes).hexdigest()
    if recording_hash != st.session_state.get("processed_recording_hash"):
        st.session_state.processed_recording_hash = recording_hash
        with st.spinner("Transcribing and answering..."):
            try:
                transcription_response = api_request(
                    "POST",
                    "/api/voice/transcribe",
                    files={"file": ("question.wav", recording_bytes, voice_recording.type or "audio/wav")},
                    timeout=120,
                )
                if transcription_response.ok:
                    question_text = transcription_response.json()["text"]
                    answer_response = api_request("POST", "/api/voice/answer", json={"question": question_text}, timeout=120)
                    if answer_response.ok:
                        st.session_state.answer = answer_response.json()
                        if st.session_state.answer["grounded"]:
                            audio_response = api_request("POST", "/api/voice/speak", json={"text": st.session_state.answer["answer"]}, timeout=120)
                            if audio_response.ok:
                                st.session_state.answer_audio = audio_response.content
                            else:
                                show_api_error(audio_response)
                    else:
                        show_api_error(answer_response)
                else:
                    show_api_error(transcription_response)
            except requests.RequestException as exc:
                st.error(f"Voice conversation failed: {exc}")
        if transcription_response.ok:
            st.caption(f"Heard: {transcription_response.json()['text']}")

if st.session_state.get("answer_audio"):
    st.audio(st.session_state.answer_audio, format="audio/wav", autoplay=True)

if st.session_state.pitch is None:
    st.markdown("<div class='status'><strong>Waiting for a pitch deck</strong>Upload a document above to open its transcript and Q&A workspace.</div>", unsafe_allow_html=True)
else:
    pitch = st.session_state.pitch
    st.markdown(f"<div class='status'><strong>Source loaded</strong>{escape(str(pitch['source']))} &middot; {len(pitch['chunks'])} readable sections</div>", unsafe_allow_html=True)
    transcript_col, ask_col = st.columns([1.15, 0.85], gap="large")

    with transcript_col:
        st.subheader("Pitch transcript")
        st.markdown(f"<div class='transcript'>{escape(pitch['text'])}</div>", unsafe_allow_html=True)

    with ask_col:
        st.subheader("Ask the pitch")
        question = st.text_area(
            "Question",
            placeholder="What problem does this product solve?",
            height=125,
            label_visibility="collapsed",
        )
        if st.button("Answer from source", use_container_width=True, disabled=not question.strip()):
            try:
                response = api_request("POST", "/api/voice/answer", json={"question": question.strip()})
                if response.ok:
                    st.session_state.answer = response.json()
                else:
                    show_api_error(response)
            except requests.RequestException as exc:
                st.error(f"Question failed: {exc}")

        answer = st.session_state.answer
        if answer:
            grounded_label = "Grounded in source" if answer["grounded"] else "No matching source found"
            st.markdown(f"<div class='eyebrow'>{grounded_label}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='answer'>{escape(answer['answer'])}<div class='source'>{len(answer['sources'])} source section(s) used</div></div>", unsafe_allow_html=True)
            if answer["grounded"] and st.button("Play answer", use_container_width=True):
                try:
                    response = api_request("POST", "/api/voice/speak", json={"text": answer["answer"]}, timeout=90)
                    if response.ok:
                        st.audio(response.content, format="audio/mp3", autoplay=False)
                    else:
                        show_api_error(response)
                except requests.RequestException as exc:
                    st.error(f"Audio request failed: {exc}")
            with st.expander("View source sections"):
                for index, source in enumerate(answer["sources"], start=1):
                    st.markdown(f"**{index}.** {escape(source)}")
