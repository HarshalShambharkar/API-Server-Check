import base64
import io
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import streamlit as st
from dotenv import load_dotenv
from PyPDF2 import PdfReader


APP_DIR = Path(__file__).resolve().parent
SHARED_ENV_PATH = APP_DIR.parent / "voice_rag_streamlit" / ".env"
load_dotenv(dotenv_path=SHARED_ENV_PATH)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_CHAT_MODEL = "gemini-2.5-flash"
DEFAULT_EMBED_MODEL = "gemini-embedding-2"
DEFAULT_TTS_MODEL = "gemini-2.5-flash-preview-tts"
DEFAULT_TTS_VOICE = "Kore"
CHUNK_SIZE = 1400
CHUNK_OVERLAP = 200
TOP_K = 4

LANGUAGES = {
    "English": "Respond in clear English.",
    "Hindi": "Respond in natural Hindi using Devanagari script.",
    "Marathi": "Respond in natural Marathi using Devanagari script.",
    "Hinglish": "Respond in natural Hinglish using Roman script.",
    "Spanish": "Respond in natural Spanish.",
    "Japanese": "Respond in natural Japanese.",
}


@dataclass
class Chunk:
    text: str
    source: str


def env(name: str, default: str = "") -> str:
    import os

    value = os.getenv(name, default)
    return value.strip() if isinstance(value, str) else default


def get_config() -> dict[str, str]:
    return {
        "api_key": env("GEMINI_API_KEY", env("GOOGLE_API_KEY")),
        "chat_model": env("LLM_MODEL", DEFAULT_CHAT_MODEL),
        "embed_model": env("EMBEDDING_MODEL", DEFAULT_EMBED_MODEL),
        "tts_model": env("TTS_MODEL", DEFAULT_TTS_MODEL),
        "tts_voice": env("TTS_VOICE", DEFAULT_TTS_VOICE),
    }


def init_state() -> None:
    defaults = {
        "chunks": [],
        "embeddings": None,
        "indexed_files": [],
        "messages": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def gemini_headers(api_key: str) -> dict[str, str]:
    return {"Content-Type": "application/json", "x-goog-api-key": api_key}


def split_text(text: str) -> list[str]:
    clean = " ".join(text.split())
    if not clean:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + CHUNK_SIZE)
        chunks.append(clean[start:end])
        if end == len(clean):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def read_uploaded_file(uploaded_file: Any) -> str:
    suffix = Path(uploaded_file.name).suffix.lower()
    raw = uploaded_file.getvalue()

    if suffix == ".txt":
        return raw.decode("utf-8", errors="ignore")
    if suffix == ".pdf":
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    raise ValueError(f"Unsupported file type: {suffix}")


def normalize(vector: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vector)
    return vector if norm == 0 else vector / norm


def embed_text(text: str, config: dict[str, str], mode: str) -> np.ndarray:
    prefix = "Represent this query for retrieval:\n" if mode == "query" else "Represent this document for retrieval:\n"
    payload = {
        "model": f"models/{config['embed_model']}",
        "content": {"parts": [{"text": prefix + text}]},
    }
    response = httpx.post(
        f"{GEMINI_API_BASE}/models/{config['embed_model']}:embedContent",
        headers=gemini_headers(config["api_key"]),
        json=payload,
        timeout=240,
    )
    response.raise_for_status()
    vector = np.array(response.json()["embedding"]["values"], dtype="float32")
    return normalize(vector)


def build_index(uploaded_files: list[Any], config: dict[str, str]) -> tuple[list[Chunk], np.ndarray]:
    chunks: list[Chunk] = []
    for uploaded_file in uploaded_files:
        text = read_uploaded_file(uploaded_file)
        for chunk_text in split_text(text):
            chunks.append(Chunk(text=chunk_text, source=uploaded_file.name))

    if not chunks:
        raise ValueError("No readable text found in the uploaded files.")

    embeddings = np.vstack([embed_text(chunk.text, config, "document") for chunk in chunks]).astype("float32")
    return chunks, embeddings


def retrieve(question: str, config: dict[str, str]) -> list[Chunk]:
    if st.session_state.embeddings is None or not st.session_state.chunks:
        return []

    query_vector = embed_text(question, config, "query")
    scores = st.session_state.embeddings @ query_vector
    indices = np.argsort(scores)[::-1][:TOP_K]
    return [st.session_state.chunks[idx] for idx in indices]


def extract_text(data: dict[str, Any]) -> str:
    candidates = data.get("candidates", [])
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return "\n".join(part.get("text", "") for part in parts if part.get("text")).strip()


def gemini_text(prompt: str, config: dict[str, str], system_instruction: str) -> str:
    payload = {
        "system_instruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"parts": [{"text": prompt}]}],
    }
    response = httpx.post(
        f"{GEMINI_API_BASE}/models/{config['chat_model']}:generateContent",
        headers=gemini_headers(config["api_key"]),
        json=payload,
        timeout=240,
    )
    response.raise_for_status()
    return extract_text(response.json())


def generate_grounded_english_answer(question_in_english: str, config: dict[str, str]) -> tuple[str, list[Chunk]]:
    sources = retrieve(question_in_english, config)
    context = "\n\n".join(
        f"Source {i} [{chunk.source}]\n{chunk.text}" for i, chunk in enumerate(sources, start=1)
    ) or "No supporting context was retrieved."
    prompt = (
        "Answer the user's question using the retrieved context below. "
        "If the context is insufficient, say so clearly. "
        "Respond only in English.\n\n"
        f"{context}\n\nQuestion: {question_in_english}"
    )
    answer = gemini_text(
        prompt,
        config,
        "You are a grounded RAG assistant. Keep answers concise and natural for speech.",
    )
    return answer, sources


def transcribe_audio_in_user_language(
    audio_bytes: bytes, mime_type: str, language: str, config: dict[str, str]
) -> str:
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "Transcribe this speech to text in the same language as spoken. "
                            f"The expected spoken language is {language}. "
                            "Do not translate to English. Return only the transcript text."
                        )
                    },
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64.b64encode(audio_bytes).decode("utf-8"),
                        }
                    },
                ]
            }
        ]
    }
    response = httpx.post(
        f"{GEMINI_API_BASE}/models/{config['chat_model']}:generateContent",
        headers=gemini_headers(config["api_key"]),
        json=payload,
        timeout=240,
    )
    response.raise_for_status()
    return extract_text(response.json()).strip()


def translate_question_to_english(question: str, language: str, config: dict[str, str]) -> str:
    if language == "English":
        return question.strip()
    prompt = (
        f"Translate the following user question from {language} to English for document retrieval. "
        "Preserve the meaning exactly. Return only the English translation.\n\n"
        f"Question: {question}"
    )
    return gemini_text(
        prompt,
        config,
        "You are a translation assistant for retrieval queries.",
    ).strip()


def localize_answer(english_answer: str, language: str, config: dict[str, str]) -> str:
    if language == "English":
        return english_answer
    prompt = (
        f"Translate the following English answer into {language}. "
        "Keep the meaning accurate, concise, and natural for speech output. "
        "Return only the translated answer.\n\n"
        f"English answer: {english_answer}"
    )
    return gemini_text(
        prompt,
        config,
        "You are a multilingual assistant that produces natural spoken-language output.",
    ).strip()


def pcm_to_wav_bytes(pcm_bytes: bytes, sample_rate: int = 24000) -> bytes:
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_bytes)
        return buffer.getvalue()


def generate_tts_audio(text: str, config: dict[str, str]) -> bytes | None:
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": config["tts_voice"]}
                }
            },
        },
    }
    response = httpx.post(
        f"{GEMINI_API_BASE}/models/{config['tts_model']}:generateContent",
        headers=gemini_headers(config["api_key"]),
        json=payload,
        timeout=240,
    )
    if response.status_code >= 400:
        return None
    data = response.json()
    candidates = data.get("candidates", [])
    if not candidates:
        return None
    parts = candidates[0].get("content", {}).get("parts", [])
    for part in parts:
        inline_data = part.get("inlineData") or part.get("inline_data")
        if inline_data and inline_data.get("data"):
            return pcm_to_wav_bytes(base64.b64decode(inline_data["data"]))
    return None


def ask_and_store(user_question: str, language: str, config: dict[str, str]) -> None:
    retrieval_query = translate_question_to_english(user_question, language, config)
    english_answer, sources = generate_grounded_english_answer(retrieval_query, config)
    localized_answer = localize_answer(english_answer, language, config)
    audio_bytes = generate_tts_audio(localized_answer, config)
    st.session_state.messages.append({"role": "user", "content": user_question})
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": localized_answer,
            "sources": [source.source for source in sources],
            "audio_bytes": audio_bytes,
            "user_language": language,
            "original_question": user_question,
            "retrieval_query": retrieval_query,
            "english_answer": english_answer,
            "localized_answer": localized_answer,
        }
    )


def main() -> None:
    st.set_page_config(page_title="Minimal Multilingual Voice RAG", page_icon="🎙️", layout="wide")
    init_state()
    config = get_config()

    st.title("Minimal Multilingual Voice RAG")
    st.caption(f"Shared env: `{SHARED_ENV_PATH}`")

    with st.sidebar:
        language = st.selectbox("Response Language", list(LANGUAGES.keys()))
        uploads = st.file_uploader(
            "Upload knowledge files",
            type=["pdf", "txt"],
            accept_multiple_files=True,
        )
        if st.button("Build Index", use_container_width=True):
            if not uploads:
                st.warning("Upload at least one PDF or TXT file first.")
            else:
                with st.spinner("Building Gemini embedding index..."):
                    chunks, embeddings = build_index(uploads, config)
                st.session_state.chunks = chunks
                st.session_state.embeddings = embeddings
                st.session_state.indexed_files = [file.name for file in uploads]
                st.session_state.messages = []
                st.success(f"Indexed {len(chunks)} chunks.")

        if st.session_state.indexed_files:
            st.markdown("### Indexed Files")
            for name in st.session_state.indexed_files:
                st.caption(name)

    left, right = st.columns([1.35, 1])

    with left:
        st.subheader("Conversation")
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
                if message["role"] == "assistant":
                    if message.get("user_language") and message["user_language"] != "English":
                        st.caption(f"Input language: {message['user_language']}")
                    if message.get("original_question"):
                        st.caption("Original transcript / question: " + message["original_question"])
                    if message.get("retrieval_query"):
                        st.caption("English query used for RAG: " + message["retrieval_query"])
                    if message.get("english_answer") and message.get("localized_answer") != message.get("english_answer"):
                        st.caption("English grounded answer: " + message["english_answer"])
                    if message.get("sources"):
                        st.caption("Sources: " + ", ".join(dict.fromkeys(message["sources"])))
                    if message.get("audio_bytes"):
                        st.audio(message["audio_bytes"], format="audio/wav")

        user_text = st.chat_input("Ask a question about your uploaded documents")
        if user_text:
            if st.session_state.embeddings is None:
                st.warning("Build the document index first.")
            else:
                with st.spinner("Generating grounded answer..."):
                    ask_and_store(user_text, language, config)
                st.rerun()

    with right:
        st.subheader("Recorded Voice")
        st.caption("Record first, then transcribe, retrieve, answer, and generate an audio clip.")
        audio_value = st.audio_input("Speak your question")
        if audio_value is not None:
            st.audio(audio_value)
            if st.button("Transcribe and Ask", use_container_width=True):
                if st.session_state.embeddings is None:
                    st.warning("Build the document index first.")
                else:
                    mime_type = getattr(audio_value, "type", None) or "audio/wav"
                    with st.spinner("Transcribing audio..."):
                        transcript = transcribe_audio_in_user_language(
                            audio_value.getvalue(), mime_type, language, config
                        )
                    st.info(f"Original transcript: {transcript}")
                    with st.spinner("Generating grounded answer..."):
                        ask_and_store(transcript, language, config)
                    st.rerun()


if __name__ == "__main__":
    main()
