# Voice RAG Streamlit

This app provides a browser-based voice RAG chatbot with swappable backends.

- Personal mode: Gemini
- Hackathon / corporate mode: OpenAI-compatible endpoints

## Files

- `app.py`: compatibility entrypoint for the original launch command
- `hackathon_voice_rag_app.py`: clearly named multi-backend voice RAG app
- `requirements.txt`: pinned Python dependencies
- `.env.example`: provider configuration template

## Setup

```powershell
cd voice_rag_streamlit
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
streamlit run app.py
```

You can also launch the explicitly named app directly:

```powershell
streamlit run hackathon_voice_rag_app.py
```

## Personal mode

```ini
GEMINI_API_KEY=your_ai_studio_key
LLM_PROVIDER=gemini
STT_PROVIDER=gemini
EMBEDDING_PROVIDER=gemini
TTS_PROVIDER=gemini
LLM_MODEL=gemini-2.5-flash
STT_MODEL=gemini-2.5-flash
EMBEDDING_MODEL=gemini-embedding-2
TTS_MODEL=gemini-2.5-flash-preview-tts
TTS_VOICE=Kore
```

## Hackathon / corporate mode

```ini
OPENAI_API_KEY=your_internal_key
OPENAI_BASE_URL=https://your-approved-host/v1
OPENAI_VERIFY_SSL=false

LLM_PROVIDER=openai_compatible
STT_PROVIDER=openai_compatible
EMBEDDING_PROVIDER=openai_compatible
TTS_PROVIDER=openai_compatible

OPENAI_LLM_MODEL=your-approved-gpt4o-model
OPENAI_STT_MODEL=your-approved-whisper-or-transcribe-model
OPENAI_EMBEDDING_MODEL=your-approved-embedding-model
OPENAI_TTS_MODEL=your-approved-tts-model
OPENAI_TTS_VOICE=alloy
```

## Notes

- The app supports `pdf` and `txt` uploads.
- Voice input is record-then-transcribe, not real-time streaming.
- If your hackathon endpoint does not expose TTS, set `TTS_PROVIDER=none`.
