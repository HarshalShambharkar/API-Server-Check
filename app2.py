import streamlit as st
import streamlit.components.v1 as components
import requests
import time

st.set_page_config(
    page_title="ARIA — Sensor Monitor",
    page_icon="🏭",
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
.metric-card {
    background: #111518;
    border: 1px solid #1e2a38;
    border-left: 3px solid #00d4aa;
    border-radius: 6px;
    padding: 18px 22px;
    margin-bottom: 12px;
}
.metric-label {
    font-family: 'Share Tech Mono', monospace;
    font-size: 11px;
    letter-spacing: 2px;
    color: #4a6fa5;
    text-transform: uppercase;
    margin-bottom: 6px;
}
.metric-value {
    font-family: 'Share Tech Mono', monospace;
    font-size: 32px;
}
.status-ok   { color: #00d4aa; }
.status-warn { color: #f0a500; }
.status-fail { color: #e84545; }
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
hr { border-color: #1e2a38; }
</style>
""", unsafe_allow_html=True)

# ─── Header ───
st.markdown("""
<div style="padding:10px 0 20px 0;">
    <div class="header-title">⬡ ARIA</div>
    <div class="header-sub">AUTONOMOUS REAL-TIME IoT ASSISTANT — VALIDATION BUILD</div>
</div>
<hr>
""", unsafe_allow_html=True)

# ─── Auth Token Input ───
auth_token = st.text_input(
    "Blynk Auth Token",
    type="password",
    placeholder="Paste your Blynk Auth Token here"
)

if not auth_token:
    st.info("👆 Enter your Blynk Auth Token to start.")
    st.stop()

# ─── Hidden HTML fetcher ───
# Only job: fetch Blynk every 3s and POST to Flask mailbox
html_fetcher = f"""
<script>
const TOKEN = "{auth_token}";
const PINS  = ["v0","v1","v2","v3","v4","v5"];
const BLYNK = "https://blynk.cloud/external/api/get";
const FLASK = "http://localhost:5001/update";

async function fetchAndForward() {{
    try {{
        let data = {{}};
        for (const pin of PINS) {{
            const res = await fetch(`${{BLYNK}}?token=${{TOKEN}}&${{pin}}`);
            const val = await res.text();
            data[pin] = parseFloat(val);
        }}
        await fetch(FLASK, {{
            method: "POST",
            headers: {{"Content-Type": "application/json"}},
            body: JSON.stringify(data)
        }});
        document.getElementById("js_status").textContent =
            "✅ JS forwarded at " + new Date().toLocaleTimeString();
    }} catch(e) {{
        document.getElementById("js_status").textContent = "❌ JS error: " + e.message;
    }}
}}

fetchAndForward();
setInterval(fetchAndForward, 3000);
</script>
<div id="js_status" style="
    font-family: monospace;
    font-size: 11px;
    color: #4a6fa5;
    padding: 6px 10px;
    background: #111518;
    border: 1px solid #1e2a38;
    border-radius: 4px;
">Starting JS fetcher...</div>
"""

components.html(html_fetcher, height=40)
st.markdown("<hr>", unsafe_allow_html=True)

# ─── Helper functions ───
def get_sensor_data():
    try:
        res = requests.get("http://localhost:5001/data", timeout=2)
        return res.json()
    except:
        return None

def vibration_color(v):
    if v < 4:  return "status-ok"
    if v < 7:  return "status-warn"
    return "status-fail"

def temp_color(v):
    if v < 80:  return "status-ok"
    if v < 110: return "status-warn"
    return "status-fail"

def render_card(label, value, unit, color_class):
    return f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value {color_class}">
            {value}
            <span style="font-size:14px;color:#4a6fa5;margin-left:4px;">{unit}</span>
        </div>
    </div>
    """

# ─── Layout ───
st.markdown("#### Live Sensor Values")

col1, col2, col3 = st.columns(3)
col4, col5, col6 = st.columns(3)

ph = {
    "v0": col1.empty(),
    "v1": col2.empty(),
    "v2": col3.empty(),
    "v3": col4.empty(),
    "v4": col5.empty(),
    "v5": col6.empty(),
}

flask_status = st.empty()
raw_display  = st.empty()

# ─── Live refresh loop ───
while True:
    data = get_sensor_data()

    if data is None:
        flask_status.error("❌ Flask server not reachable — run: python server.py")
    else:
        flask_status.success(f"✅ Flask OK · Python read at {time.strftime('%H:%M:%S')}")

        v0 = data.get("v0", 0)
        v1 = data.get("v1", 0)
        v2 = data.get("v2", 0)
        v3 = data.get("v3", 0)
        v4 = data.get("v4", 0)
        v5 = data.get("v5", 0)

        ph["v0"].markdown(render_card("Vibration",     f"{v0:.1f}", "g",   vibration_color(v0)), unsafe_allow_html=True)
        ph["v1"].markdown(render_card("Temperature",   f"{v1:.1f}", "°C",  temp_color(v1)),      unsafe_allow_html=True)
        ph["v2"].markdown(render_card("Sound Level",   f"{v2:.1f}", "dB",  "status-ok"),         unsafe_allow_html=True)
        ph["v3"].markdown(render_card("Belt Speed",    f"{v3:.1f}", "%",   "status-ok"),         unsafe_allow_html=True)
        ph["v4"].markdown(render_card("Error Code",    f"E-{int(v4):02d}", "", "status-warn" if v4 > 0 else "status-ok"), unsafe_allow_html=True)
        ph["v5"].markdown(render_card("Machine Status","ONLINE" if v5 == 1 else "OFFLINE", "", "status-ok" if v5 == 1 else "status-fail"), unsafe_allow_html=True)

        raw_display.code(str(data), language="json")

    time.sleep(3)
