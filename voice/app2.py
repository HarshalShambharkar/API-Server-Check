import streamlit as st
import streamlit.components.v1 as components
import requests
import time
import os
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="ARIA — Voice Agent",
    page_icon="🎙️",
    layout="wide"
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow:wght@300;400;600&display=swap');
html, body, [class*="css"] {
    background-color: #0a0c0f;
    color: #c8d6e5;
    font-family: 'Barlow', sans-serif;
}
.header-title {
    font-family: 'Share Tech Mono', monospace;
    font-size: 22px;
    letter-spacing: 4px;
    color: #00d4aa;
}
.header-sub {
    font-size: 12px;
    color: #4a6fa5;
    letter-spacing: 2px;
}
.chat-user {
    background: #111c2e;
    border-left: 3px solid #4a6fa5;
    border-radius: 6px;
    padding: 10px 16px;
    margin: 6px 0;
    font-size: 14px;
}
.chat-ai {
    background: #0f1f1a;
    border-left: 3px solid #00d4aa;
    border-radius: 6px;
    padding: 10px 16px;
    margin: 6px 0;
    font-size: 14px;
}
.chat-label-user { color: #4a6fa5; font-size: 10px; letter-spacing: 2px; font-family: 'Share Tech Mono', monospace; }
.chat-label-ai   { color: #00d4aa; font-size: 10px; letter-spacing: 2px; font-family: 'Share Tech Mono', monospace; }
.ts { color: #2a3a4a; font-size: 10px; float: right; }
hr  { border-color: #1e2a38; }
</style>
""", unsafe_allow_html=True)

# ─── Header ───
st.markdown("""
<div style="padding:10px 0 20px 0;">
    <div class="header-title">⬡ ARIA</div>
    <div class="header-sub">AUTONOMOUS REAL-TIME IoT ASSISTANT — VOICE MODE</div>
</div>
<hr>
""", unsafe_allow_html=True)

# ─── API Key Input ───
api_key = st.text_input(
    "Google API Key",
    type="password",
    placeholder="Paste your Google API Key from aistudio.google.com",
    value=os.getenv("GOOGLE_API_KEY", "")
)

if not api_key:
    st.info("👆 Enter your Google API Key to start.")
    st.stop()

# ─── System Prompt ───
DEFAULT_PROMPT = "You are ARIA, an intelligent real-time IoT monitoring assistant. You help operators understand sensor data, detect anomalies, and take corrective action. Be concise, precise, and speak in short sentences suitable for voice."

with st.expander("⚙️ Customize AI Persona (optional)"):
    system_prompt = st.text_area(
        "System Instruction",
        value=DEFAULT_PROMPT,
        height=100
    )

# ─── Voice Agent HTML/JS Component ───
# This runs entirely in the browser:
# Mic → Gemini Live WebSocket → Audio playback + POST to Flask
voice_component = f"""
<style>
  body {{ margin: 0; background: transparent; font-family: 'Share Tech Mono', monospace; }}
  #container {{
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    padding: 16px;
  }}
  #mic-btn {{
    width: 80px;
    height: 80px;
    border-radius: 50%;
    border: 2px solid #00d4aa;
    background: #111518;
    color: #00d4aa;
    font-size: 28px;
    cursor: pointer;
    transition: all 0.2s;
  }}
  #mic-btn.active {{
    background: #00d4aa22;
    border-color: #00ffcc;
    box-shadow: 0 0 20px #00d4aa66;
    animation: pulse 1.2s infinite;
  }}
  #mic-btn.listening {{
    background: #e8454522;
    border-color: #e84545;
    box-shadow: 0 0 20px #e8454566;
  }}
  @keyframes pulse {{
    0%   {{ box-shadow: 0 0 10px #00d4aa44; }}
    50%  {{ box-shadow: 0 0 30px #00d4aa99; }}
    100% {{ box-shadow: 0 0 10px #00d4aa44; }}
  }}
  #status {{
    font-size: 11px;
    letter-spacing: 2px;
    color: #4a6fa5;
    text-align: center;
    min-height: 20px;
  }}
  #transcript {{
    font-size: 12px;
    color: #c8d6e5;
    text-align: center;
    max-width: 400px;
    min-height: 18px;
    font-style: italic;
  }}
</style>

<div id="container">
  <button id="mic-btn" onclick="toggleSession()">🎙️</button>
  <div id="status">READY — CLICK TO CONNECT</div>
  <div id="transcript"></div>
</div>

<script type="module">
const API_KEY     = "{api_key}";
const FLASK       = "http://localhost:5001";
const MODEL       = "gemini-2.5-flash-native-audio-preview-09-2025";
const SYSTEM      = `{system_prompt}`;

let ws            = null;
let audioCtx      = null;
let mediaStream   = null;
let processor     = null;
let isConnected   = false;
let audioQueue    = [];
let isPlaying     = false;

const btn         = document.getElementById("mic-btn");
const statusEl    = document.getElementById("status");
const transcriptEl= document.getElementById("transcript");

// ─── Float32 PCM → base64 PCM16 ───
function float32ToBase64PCM16(float32Array) {{
  const pcm16 = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {{
    pcm16[i] = Math.max(-32768, Math.min(32767, float32Array[i] * 32767));
  }}
  const bytes = new Uint8Array(pcm16.buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}}

// ─── base64 PCM16 → play audio ───
function playPCM16(base64Audio) {{
  audioQueue.push(base64Audio);
  if (!isPlaying) drainQueue();
}}

async function drainQueue() {{
  if (audioQueue.length === 0) {{ isPlaying = false; return; }}
  isPlaying = true;
  const base64 = audioQueue.shift();
  const raw    = atob(base64);
  const bytes  = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  const pcm16  = new Int16Array(bytes.buffer);
  const float32= new Float32Array(pcm16.length);
  for (let i = 0; i < pcm16.length; i++) float32[i] = pcm16[i] / 32768;
  const buffer = audioCtx.createBuffer(1, float32.length, 24000);
  buffer.getChannelData(0).set(float32);
  const src = audioCtx.createBufferSource();
  src.buffer = buffer;
  src.connect(audioCtx.destination);
  src.onended = drainQueue;
  src.start();
}}

// ─── Connect to Gemini Live ───
async function connect() {{
  setStatus("CONNECTING...", false);
  audioCtx = new AudioContext({{ sampleRate: 16000 }});

  const wsUrl = `wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent?key=${{API_KEY}}`;
  ws = new WebSocket(wsUrl);

  ws.onopen = () => {{
    // Send setup message
    ws.send(JSON.stringify({{
      setup: {{
        model: "models/" + MODEL,
        generation_config: {{
          response_modalities: ["AUDIO"],
          speech_config: {{ voice_config: {{ prebuilt_voice_config: {{ voice_name: "Aoede" }} }} }}
        }},
        system_instruction: {{ parts: [{{ text: SYSTEM }}] }}
      }}
    }}));
  }};

  ws.onmessage = async (event) => {{
    let raw;
    if (event.data instanceof Blob) {{
      raw = await event.data.text();
    }} else {{
      raw = event.data;
    }}

    let msg;
    try {{ msg = JSON.parse(raw); }} catch {{ return; }}

    // Setup confirmed
    if (msg.setupComplete) {{
      isConnected = true;
      setStatus("🟢 CONNECTED — SPEAK NOW", true);
      btn.classList.add("active");
      postStatus(true, null);
      startMic();
      return;
    }}

    // Audio response from Gemini
    const parts = msg?.serverContent?.modelTurn?.parts || [];
    for (const part of parts) {{
      if (part.inlineData?.mimeType?.includes("audio")) {{
        playPCM16(part.inlineData.data);
      }}
      if (part.text) {{
        transcriptEl.textContent = "🤖 " + part.text;
        postTurn("assistant", part.text);
      }}
    }}

    // Turn complete
    if (msg?.serverContent?.turnComplete) {{
      setStatus("🟢 LISTENING...", true);
      btn.classList.remove("listening");
      btn.classList.add("active");
    }}

    // Input transcript
    const inputTranscript = msg?.serverContent?.inputTranscript;
    if (inputTranscript) {{
      transcriptEl.textContent = "🎙️ " + inputTranscript;
      postTurn("user", inputTranscript);
    }}
  }};

  ws.onerror = (e) => {{
    setStatus("❌ CONNECTION ERROR", false);
    postStatus(false, "WebSocket error");
    disconnect();
  }};

  ws.onclose = () => {{
    if (isConnected) setStatus("⚪ DISCONNECTED", false);
    isConnected = false;
    btn.classList.remove("active", "listening");
    postStatus(false, null);
  }};
}}

// ─── Start capturing mic ───
async function startMic() {{
  mediaStream = await navigator.mediaDevices.getUserMedia({{ audio: true }});
  const source = audioCtx.createMediaStreamSource(mediaStream);
  processor   = audioCtx.createScriptProcessor(4096, 1, 1);

  processor.onaudioprocess = (e) => {{
    if (!isConnected || !ws || ws.readyState !== WebSocket.OPEN) return;
    const samples = e.inputBuffer.getChannelData(0);
    const b64     = float32ToBase64PCM16(samples);
    ws.send(JSON.stringify({{
      realtime_input: {{
        media_chunks: [{{ mime_type: "audio/pcm;rate=16000", data: b64 }}]
      }}
    }}));
    btn.classList.add("listening");
  }};

  source.connect(processor);
  processor.connect(audioCtx.destination);
}}

// ─── Disconnect ───
function disconnect() {{
  if (processor)    {{ processor.disconnect(); processor = null; }}
  if (mediaStream)  {{ mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }}
  if (audioCtx)     {{ audioCtx.close(); audioCtx = null; }}
  if (ws)           {{ ws.close(); ws = null; }}
  isConnected = false;
  btn.classList.remove("active", "listening");
  setStatus("⚪ DISCONNECTED — CLICK TO RECONNECT", false);
}}

// ─── Toggle ───
window.toggleSession = function() {{
  if (isConnected) {{
    disconnect();
  }} else {{
    connect();
  }}
}};

// ─── Helpers ───
function setStatus(msg, active) {{
  statusEl.textContent = msg;
}}

async function postTurn(role, text) {{
  try {{
    await fetch(`${{FLASK}}/conversation`, {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ role, text }})
    }});
  }} catch(e) {{}}
}}

async function postStatus(connected, error) {{
  try {{
    await fetch(`${{FLASK}}/status`, {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ connected, error }})
    }});
  }} catch(e) {{}}
}}
</script>
"""

# ─── Render Voice Component ───
components.html(voice_component, height=200)
st.markdown("<hr>", unsafe_allow_html=True)

# ─── Controls ───
col_a, col_b, col_c = st.columns([1, 1, 4])
with col_a:
    if st.button("🗑️ Clear Chat"):
        try:
            requests.post("http://localhost:5001/clear", timeout=1)
        except:
            pass
        st.rerun()
with col_b:
    auto_refresh = st.checkbox("Auto refresh", value=True)

# ─── Status Bar ───
status_ph = st.empty()
chat_ph   = st.empty()

# ─── Live Refresh Loop ───
while True:
    # Status
    try:
        s = requests.get("http://localhost:5001/status", timeout=1).json()
        if s.get("connected"):
            status_ph.success(f"🟢 Gemini Live connected · Last update {s.get('last_updated','')}")
        else:
            err = s.get("error")
            if err:
                status_ph.error(f"❌ {err}")
            else:
                status_ph.info("⚪ Not connected — click the mic button above")
    except:
        status_ph.warning("⚠️ Flask server not running — open a terminal and run: python server.py")

    # Conversation
    try:
        turns = requests.get("http://localhost:5001/conversation", timeout=1).json()
        if turns:
            html_blocks = ""
            for t in turns:
                if t["role"] == "user":
                    html_blocks += f"""
                    <div class="chat-user">
                        <div class="chat-label-user">YOU <span class="ts">{t.get('ts','')}</span></div>
                        {t['text']}
                    </div>"""
                else:
                    html_blocks += f"""
                    <div class="chat-ai">
                        <div class="chat-label-ai">ARIA <span class="ts">{t.get('ts','')}</span></div>
                        {t['text']}
                    </div>"""
            chat_ph.markdown(html_blocks, unsafe_allow_html=True)
        else:
            chat_ph.markdown(
                "<div style='color:#2a3a4a;font-size:13px;padding:20px 0;'>No conversation yet. Click the mic to start.</div>",
                unsafe_allow_html=True
            )
    except:
        pass

    if not auto_refresh:
        break
    time.sleep(3)