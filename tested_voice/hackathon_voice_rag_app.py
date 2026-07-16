import base64
import io
import os
import re
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import faiss
import httpx
import numpy as np
import streamlit as st
from dotenv import load_dotenv
from PyPDF2 import PdfReader


load_dotenv()

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_GEMINI_LLM_MODEL = "gemini-2.5-flash"
DEFAULT_GEMINI_EMBED_MODEL = "gemini-embedding-2"
DEFAULT_GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"
DEFAULT_GEMINI_TTS_VOICE = "Kore"
DEFAULT_OPENAI_LLM_MODEL = "gpt-4o-mini"
DEFAULT_OPENAI_STT_MODEL = "gpt-4o-mini-transcribe"
DEFAULT_OPENAI_EMBED_MODEL = "text-embedding-3-small"
DEFAULT_OPENAI_TTS_MODEL = "gpt-4o-mini-tts"
DEFAULT_OPENAI_TTS_VOICE = "alloy"
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200
TOP_K = 4
GEMINI_EMBED_DIM = 768


@dataclass
class DocumentChunk:
    text: str
    source: str


def env(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    return value.strip() if isinstance(value, str) else default


def env_bool(name: str, default: bool) -> bool:
    value = env(name, "true" if default else "false").lower()
    return value in {"1", "true", "yes", "on"}


def get_config() -> dict[str, Any]:
    openai_base_url = env("OPENAI_BASE_URL", env("OPENAI_API_BASE"))
    openai_api_key = env("OPENAI_API_KEY")
    return {
        "llm_provider": env("LLM_PROVIDER", "gemini"),
        "stt_provider": env("STT_PROVIDER", "gemini"),
        "embedding_provider": env("EMBEDDING_PROVIDER", "gemini"),
        "tts_provider": env("TTS_PROVIDER", "gemini"),
        "gemini_api_key": env("GEMINI_API_KEY", env("GOOGLE_API_KEY")),
        "openai_api_key": openai_api_key,
        "openai_base_url": openai_base_url,
        "openai_verify_ssl": env_bool("OPENAI_VERIFY_SSL", True),
        "llm_model": env("LLM_MODEL", DEFAULT_GEMINI_LLM_MODEL),
        "stt_model": env("STT_MODEL", DEFAULT_GEMINI_LLM_MODEL),
        "embedding_model": env("EMBEDDING_MODEL", DEFAULT_GEMINI_EMBED_MODEL),
        "tts_model": env("TTS_MODEL", DEFAULT_GEMINI_TTS_MODEL),
        "tts_voice": env("TTS_VOICE", DEFAULT_GEMINI_TTS_VOICE),
        "openai_llm_model": env("OPENAI_LLM_MODEL", DEFAULT_OPENAI_LLM_MODEL),
        "openai_stt_model": env("OPENAI_STT_MODEL", DEFAULT_OPENAI_STT_MODEL),
        "openai_embedding_model": env("OPENAI_EMBEDDING_MODEL", DEFAULT_OPENAI_EMBED_MODEL),
        "openai_tts_model": env("OPENAI_TTS_MODEL", DEFAULT_OPENAI_TTS_MODEL),
        "openai_tts_voice": env("OPENAI_TTS_VOICE", DEFAULT_OPENAI_TTS_VOICE),
        "system_prompt": env(
            "SYSTEM_PROMPT",
            (
                "You are a voice-enabled RAG assistant. Answer from the retrieved document "
                "context when possible. If the context is insufficient, say that clearly. "
                "Keep answers concise and natural for speech."
            ),
        ),
    }


def init_state() -> None:
    defaults = {
        "messages": [],
        "vector_index": None,
        "chunks": [],
        "indexed_files": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


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
    if suffix == ".txt":
        return uploaded_file.getvalue().decode("utf-8", errors="ignore")
    if suffix == ".pdf":
        reader = PdfReader(io.BytesIO(uploaded_file.getvalue()))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)
    raise ValueError(f"Unsupported file type: {suffix}")


def normalize_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def extract_http_error(exc: httpx.HTTPStatusError) -> str:
    try:
        data = exc.response.json()
        return data.get("error", {}).get("message", exc.response.text)
    except Exception:
        return exc.response.text


def gemini_headers(api_key: str) -> dict[str, str]:
    return {"Content-Type": "application/json", "x-goog-api-key": api_key}


def gemini_generate_content(
    model: str, payload: dict[str, Any], api_key: str, timeout: int = 240
) -> dict[str, Any]:
    if not api_key:
        raise ValueError("Set GEMINI_API_KEY or GOOGLE_API_KEY in the .env file.")

    url = f"{GEMINI_API_BASE}/models/{model}:generateContent"
    response = httpx.post(url, headers=gemini_headers(api_key), json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def openai_request(
    config: dict[str, Any],
    path: str,
    *,
    json: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    timeout: int = 240,
) -> httpx.Response:
    if not config["openai_api_key"] or not config["openai_base_url"]:
        raise ValueError("Set OPENAI_API_KEY and OPENAI_BASE_URL in the .env file.")

    url = config["openai_base_url"].rstrip("/") + path
    headers = {"Authorization": f"Bearer {config['openai_api_key']}"}
    response = httpx.post(
        url,
        headers=headers,
        json=json,
        files=files,
        data=data,
        timeout=timeout,
        verify=config["openai_verify_ssl"],
    )
    response.raise_for_status()
    return response


def gemini_embed_text(text: str, config: dict[str, Any]) -> np.ndarray:
    payload = {
        "model": f"models/{config['embedding_model']}",
        "content": {"parts": [{"text": text}]},
        "output_dimensionality": GEMINI_EMBED_DIM,
    }
    url = f"{GEMINI_API_BASE}/models/{config['embedding_model']}:embedContent"
    response = httpx.post(
        url,
        headers=gemini_headers(config["gemini_api_key"]),
        json=payload,
        timeout=240,
    )
    response.raise_for_status()
    values = response.json()["embedding"]["values"]
    vector = np.array(values, dtype="float32")
    norm = np.linalg.norm(vector)
    return vector if norm == 0 else vector / norm


def openai_embed_text(text: str, config: dict[str, Any]) -> np.ndarray:
    response = openai_request(
        config,
        "/embeddings",
        json={"model": config["openai_embedding_model"], "input": text},
    )
    values = response.json()["data"][0]["embedding"]
    vector = np.array(values, dtype="float32")
    norm = np.linalg.norm(vector)
    return vector if norm == 0 else vector / norm


def embed_text(text: str, config: dict[str, Any], mode: str) -> np.ndarray:
    provider = config["embedding_provider"]
    if provider == "gemini":
        prefix = "Represent this query for retrieval:\n" if mode == "query" else "Represent this document for retrieval:\n"
        return gemini_embed_text(prefix + text, config)
    if provider == "openai_compatible":
        return openai_embed_text(text, config)
    raise ValueError(f"Unsupported embedding provider: {provider}")


def embed_texts(texts: list[str], config: dict[str, Any], mode: str) -> np.ndarray:
    embeddings = [embed_text(text, config, mode) for text in texts]
    return np.vstack(embeddings).astype("float32")


def build_vector_index(chunks: list[DocumentChunk], config: dict[str, Any]) -> faiss.IndexFlatIP:
    embeddings = embed_texts([chunk.text for chunk in chunks], config, mode="document")
    embeddings = normalize_rows(embeddings)
    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)
    return index


def retrieve_context(question: str, config: dict[str, Any]) -> tuple[list[DocumentChunk], list[float]]:
    if st.session_state.vector_index is None or not st.session_state.chunks:
        return [], []

    query_embedding = embed_text(question, config, mode="query")
    query_embedding = query_embedding.reshape(1, -1).astype("float32")
    scores, indices = st.session_state.vector_index.search(query_embedding, TOP_K)

    docs: list[DocumentChunk] = []
    doc_scores: list[float] = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0:
            continue
        docs.append(st.session_state.chunks[idx])
        doc_scores.append(float(score))
    return docs, doc_scores


def build_answer_prompt(question: str, docs: list[DocumentChunk]) -> str:
    if docs:
        context = "\n\n".join(
            f"Source {i} [{doc.source}]\n{doc.text}" for i, doc in enumerate(docs, start=1)
        )
    else:
        context = "No supporting context was retrieved."

    return (
        "Use the retrieved context below to answer the question.\n\n"
        f"{context}\n\n"
        f"Question: {question}\n\n"
        "Answer naturally and briefly. If the answer is not supported by the context, say that."
    )


def extract_text_from_gemini_response(data: dict[str, Any]) -> str:
    candidates = data.get("candidates", [])
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    texts = [part.get("text", "") for part in parts if part.get("text")]
    return "\n".join(texts).strip()


def generate_answer(question: str, config: dict[str, Any]) -> tuple[str, list[DocumentChunk], list[float]]:
    docs, scores = retrieve_context(question, config)
    prompt = build_answer_prompt(question, docs)

    if config["llm_provider"] == "gemini":
        payload = {
            "system_instruction": {"parts": [{"text": config["system_prompt"]}]},
            "contents": [{"parts": [{"text": prompt}]}],
        }
        data = gemini_generate_content(config["llm_model"], payload, config["gemini_api_key"])
        answer = extract_text_from_gemini_response(data)
    elif config["llm_provider"] == "openai_compatible":
        response = openai_request(
            config,
            "/chat/completions",
            json={
                "model": config["openai_llm_model"],
                "messages": [
                    {"role": "system", "content": config["system_prompt"]},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            },
        )
        answer = response.json()["choices"][0]["message"]["content"].strip()
    else:
        raise ValueError(f"Unsupported LLM provider: {config['llm_provider']}")

    return answer, docs, scores


def sanitize_transcript(text: str) -> str:
    text = re.sub(r"^\s*(transcript|transcription)\s*:\s*", "", text, flags=re.I)
    return text.strip()


def transcribe_audio(audio_bytes: bytes, mime_type: str, config: dict[str, Any]) -> str:
    if config["stt_provider"] == "gemini":
        prompt = (
            "Transcribe this speech to text. Return only the spoken words. "
            "Do not add commentary, labels, or formatting."
        )
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
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
        data = gemini_generate_content(config["stt_model"], payload, config["gemini_api_key"])
        return sanitize_transcript(extract_text_from_gemini_response(data))

    if config["stt_provider"] == "openai_compatible":
        response = openai_request(
            config,
            "/audio/transcriptions",
            files={"file": ("question.wav", audio_bytes, mime_type)},
            data={"model": config["openai_stt_model"]},
            timeout=300,
        )
        return sanitize_transcript(response.json().get("text", ""))

    raise ValueError(f"Unsupported STT provider: {config['stt_provider']}")


def pcm_to_wav_bytes(pcm_bytes: bytes, sample_rate: int = 24000) -> bytes:
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_bytes)
        return buffer.getvalue()


def generate_tts_audio(text: str, config: dict[str, Any]) -> tuple[bytes | None, str | None]:
    if not text:
        return None, None

    if config["tts_provider"] == "gemini":
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
        try:
            data = gemini_generate_content(config["tts_model"], payload, config["gemini_api_key"])
        except httpx.HTTPStatusError as exc:
            st.warning(f"Gemini TTS unavailable for this request: {extract_http_error(exc)}")
            return None, None

        candidates = data.get("candidates", [])
        if not candidates:
            return None, None

        parts = candidates[0].get("content", {}).get("parts", [])
        for part in parts:
            inline_data = part.get("inlineData") or part.get("inline_data")
            if inline_data and inline_data.get("data"):
                pcm_bytes = base64.b64decode(inline_data["data"])
                return pcm_to_wav_bytes(pcm_bytes), "audio/wav"
        return None, None

    if config["tts_provider"] == "openai_compatible":
        try:
            response = openai_request(
                config,
                "/audio/speech",
                json={
                    "model": config["openai_tts_model"],
                    "voice": config["openai_tts_voice"],
                    "input": text,
                    "format": "mp3",
                },
                timeout=300,
            )
        except httpx.HTTPStatusError as exc:
            st.warning(f"OpenAI-compatible TTS unavailable for this request: {extract_http_error(exc)}")
            return None, None
        return response.content, "audio/mp3"

    if config["tts_provider"] == "none":
        return None, None

    raise ValueError(f"Unsupported TTS provider: {config['tts_provider']}")


def index_uploaded_files(uploaded_files: list[Any], config: dict[str, Any]) -> None:
    chunks: list[DocumentChunk] = []
    indexed_files: list[str] = []

    for uploaded_file in uploaded_files:
        text = read_uploaded_file(uploaded_file)
        file_chunks = split_text(text)
        for chunk in file_chunks:
            chunks.append(DocumentChunk(text=chunk, source=uploaded_file.name))
        indexed_files.append(uploaded_file.name)

    if not chunks:
        raise ValueError("No readable text found in the uploaded files.")

    with st.spinner("Building the vector index..."):
        index = build_vector_index(chunks, config)

    st.session_state.vector_index = index
    st.session_state.chunks = chunks
    st.session_state.indexed_files = indexed_files
    st.session_state.messages = []


def handle_question(question: str, config: dict[str, Any], synthesize_voice: bool) -> None:
    answer, docs, scores = generate_answer(question, config)
    audio_bytes, audio_format = generate_tts_audio(answer, config) if synthesize_voice else (None, None)

    st.session_state.messages.append({"role": "user", "content": question})
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": answer,
            "sources": [doc.source for doc in docs],
            "scores": scores,
            "audio_bytes": audio_bytes,
            "audio_format": audio_format,
        }
    )


def render_sidebar(config: dict[str, Any]) -> tuple[list[Any], bool]:
    with st.sidebar:
        st.header("Backend Config")
        st.caption("Same UI, swappable providers through .env only.")
        st.write(
            {
                "llm_provider": config["llm_provider"],
                "stt_provider": config["stt_provider"],
                "embedding_provider": config["embedding_provider"],
                "tts_provider": config["tts_provider"],
            }
        )
        st.write(
            {
                "llm_model": config["llm_model"] if config["llm_provider"] == "gemini" else config["openai_llm_model"],
                "stt_model": config["stt_model"] if config["stt_provider"] == "gemini" else config["openai_stt_model"],
                "embedding_model": config["embedding_model"] if config["embedding_provider"] == "gemini" else config["openai_embedding_model"],
                "tts_model": config["tts_model"] if config["tts_provider"] == "gemini" else config["openai_tts_model"],
            }
        )

        synthesize_voice = st.toggle("Generate voice replies", value=config["tts_provider"] != "none")
        uploaded_files = st.file_uploader(
            "Upload PDF or TXT files",
            type=["pdf", "txt"],
            accept_multiple_files=True,
        )

        if st.button("Build / Rebuild Index", use_container_width=True):
            if not uploaded_files:
                st.warning("Upload at least one PDF or TXT file first.")
            else:
                index_uploaded_files(uploaded_files, config)
                st.success(f"Indexed {len(st.session_state.chunks)} chunks.")

        if st.button("Reset Chat", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

        if st.session_state.indexed_files:
            st.divider()
            st.subheader("Indexed Files")
            for file_name in st.session_state.indexed_files:
                st.caption(file_name)

    return uploaded_files or [], synthesize_voice


def main() -> None:
    st.set_page_config(page_title="Voice RAG Chatbot", page_icon="🎙️", layout="wide")
    init_state()
    config = get_config()

    st.title("Voice RAG Chatbot")
    st.caption(
        "Use Gemini on personal setup and switch to OpenAI-compatible endpoints for the hackathon "
        "without changing app code."
    )
    st.info(
        "Speech input is record-then-transcribe. If your hackathon TTS endpoint is unavailable, "
        "set `TTS_PROVIDER=none` and keep text plus STT."
    )

    _, synthesize_voice = render_sidebar(config)

    chat_col, voice_col = st.columns([1.4, 1])

    with chat_col:
        st.subheader("Conversation")
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
                if message["role"] == "assistant":
                    sources = message.get("sources") or []
                    if sources:
                        unique_sources = list(dict.fromkeys(sources))
                        st.caption("Sources: " + ", ".join(unique_sources))
                    if message.get("audio_bytes"):
                        st.audio(message["audio_bytes"], format=message.get("audio_format"))

        typed_question = st.chat_input("Ask about your uploaded documents")
        if typed_question:
            if st.session_state.vector_index is None:
                st.warning("Upload documents and build the index first.")
            else:
                with st.spinner("Generating answer..."):
                    handle_question(typed_question, config, synthesize_voice)
                st.rerun()

    with voice_col:
        st.subheader("Voice Input")
        st.caption("Record a question, transcribe it, then run the same RAG flow.")
        audio_value = st.audio_input("Speak your question")
        if audio_value is not None:
            st.audio(audio_value)
            if st.button("Transcribe and Ask", use_container_width=True):
                if st.session_state.vector_index is None:
                    st.warning("Upload documents and build the index first.")
                else:
                    mime_type = getattr(audio_value, "type", None) or "audio/wav"
                    with st.spinner("Transcribing audio..."):
                        transcript = transcribe_audio(audio_value.getvalue(), mime_type, config)
                    if not transcript:
                        st.error("The STT provider did not return a transcript.")
                    else:
                        st.info(f"Transcript: {transcript}")
                        with st.spinner("Generating answer..."):
                            handle_question(transcript, config, synthesize_voice)
                        st.rerun()

        st.divider()
        st.subheader("Config File")
        st.code(
            "C:\\Users\\diksh\\Downloads\\voicerag\\voice_rag_streamlit\\.env",
            language="text",
        )
        st.caption("Personal and hackathon modes should differ only through environment variables.")


if __name__ == "__main__":
    main()
