import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="ARIA — Sensor Monitor",
    page_icon="🏭",
    layout="wide"
)

html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow:wght@300;400;600&display=swap" rel="stylesheet">
<style>
body {
    background-color: #0a0c0f;
    color: #c8d6e5;
    font-family: 'Barlow', sans-serif;
    margin: 20px;
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
.metric-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    margin-top: 20px;
}
.metric-card {
    background: #111518;
    border: 1px solid #1e2a38;
    border-left: 3px solid #00d4aa;
    border-radius: 6px;
    padding: 18px;
}
.metric-label {
    font-family: 'Share Tech Mono', monospace;
    font-size: 11px;
    letter-spacing: 2px;
    color: #4a6fa5;
    text-transform: uppercase;
}
.metric-value {
    font-family: 'Share Tech Mono', monospace;
    font-size: 28px;
}
.status-ok   { color: #00d4aa; }
.status-warn { color: #f0a500; }
.status-fail { color: #e84545; }
input {
    background: #111;
    color: #fff;
    border: 1px solid #1e2a38;
    padding: 8px 12px;
    width: 350px;
    border-radius: 4px;
    font-family: 'Share Tech Mono', monospace;
    font-size: 13px;
}
input:focus { outline: 1px solid #00d4aa; }
pre {
    background: #111;
    padding: 10px;
    border: 1px solid #1e2a38;
    border-radius: 4px;
    font-size: 12px;
}
.status-bar {
    font-family: 'Share Tech Mono', monospace;
    font-size: 11px;
    color: #4a6fa5;
    margin-top: 10px;
    padding: 6px 10px;
    background: #111518;
    border: 1px solid #1e2a38;
    border-radius: 4px;
    display: inline-block;
}
hr { border-color: #1e2a38; }
h3 { color: #c8d6e5; font-weight: 300; }
</style>
</head>
<body>

<div class="header-title">⬡ ARIA</div>
<div class="header-sub">AUTONOMOUS REAL-TIME IoT ASSISTANT — SENSOR MONITOR v0.1</div>
<hr>

<h3>Configuration</h3>
<input type="password" id="token" placeholder="Enter Blynk Auth Token" />
<div class="status-bar" id="status">⏳ Waiting for token...</div>

<h3>Live Sensor Values</h3>
<div class="metric-grid">
    <div class="metric-card">
        <div class="metric-label">Vibration</div>
        <div id="v0" class="metric-value status-ok">—</div>
    </div>
    <div class="metric-card">
        <div class="metric-label">Temperature</div>
        <div id="v1" class="metric-value status-ok">—</div>
    </div>
    <div class="metric-card">
        <div class="metric-label">Sound Level</div>
        <div id="v2" class="metric-value status-ok">—</div>
    </div>
    <div class="metric-card">
        <div class="metric-label">Belt Speed</div>
        <div id="v3" class="metric-value status-ok">—</div>
    </div>
    <div class="metric-card">
        <div class="metric-label">Error Code</div>
        <div id="v4" class="metric-value status-ok">—</div>
    </div>
    <div class="metric-card">
        <div class="metric-label">Machine Status</div>
        <div id="v5" class="metric-value status-ok">—</div>
    </div>
</div>

<h3>Raw JSON</h3>
<pre id="raw">Waiting for data...</pre>

<script>
const BASE = "https://blynk.cloud/external/api/get";
const PINS = ["v0","v1","v2","v3","v4","v5"];
let interval = null;

function getColor(type, value) {
    if (type === "vibration") {
        if (value < 4)  return "status-ok";
        if (value < 7)  return "status-warn";
        return "status-fail";
    }
    if (type === "temp") {
        if (value < 80)  return "status-ok";
        if (value < 110) return "status-warn";
        return "status-fail";
    }
    return "status-ok";
}

async function fetchData() {
    const token = document.getElementById("token").value.trim();
    if (!token) {
        document.getElementById("status").textContent = "⏳ Waiting for token...";
        return;
    }

    let data = {};
    try {
        for (let pin of PINS) {
            let res = await fetch(`${BASE}?token=${token}&${pin}`);
            let val = await res.text();
            data[pin] = isNaN(parseFloat(val)) ? val : parseFloat(val);
        }

        document.getElementById("v0").className = "metric-value " + getColor("vibration", data.v0);
        document.getElementById("v0").innerHTML = `${data.v0} <small>g</small>`;

        document.getElementById("v1").className = "metric-value " + getColor("temp", data.v1);
        document.getElementById("v1").innerHTML = `${data.v1} <small>°C</small>`;

        document.getElementById("v2").className = "metric-value status-ok";
        document.getElementById("v2").innerHTML = `${data.v2} <small>dB</small>`;

        document.getElementById("v3").className = "metric-value status-ok";
        document.getElementById("v3").innerHTML = `${data.v3} <small>%</small>`;

        document.getElementById("v4").className = data.v4 > 0 ? "metric-value status-warn" : "metric-value status-ok";
        document.getElementById("v4").innerHTML = data.v4 > 0
            ? `E-${String(data.v4).padStart(2,"0")}`
            : `E-00`;

        document.getElementById("v5").className = data.v5 === 1 ? "metric-value status-ok" : "metric-value status-fail";
        document.getElementById("v5").textContent = data.v5 === 1 ? "ONLINE" : "OFFLINE";

        document.getElementById("raw").textContent = JSON.stringify(data, null, 2);
        document.getElementById("status").textContent =
            "✅ Last updated: " + new Date().toLocaleTimeString();

    } catch(e) {
        document.getElementById("status").textContent = "❌ Error: " + e.message;
    }
}

// Start polling as soon as token is entered
document.getElementById("token").addEventListener("input", function() {
    if (interval) clearInterval(interval);
    if (this.value.trim().length > 10) {
        fetchData();
        interval = setInterval(fetchData, 3000);
    }
});
</script>
</body>
</html>
"""

components.html(html_content, height=750, scrolling=True)
