from flask import Flask, request, jsonify
from flask_cors import CORS
from collections import deque
import time

app = Flask(__name__)
CORS(app)

# ─── In-memory store ───
conversation = deque(maxlen=50)   # last 50 turns
status = {
    "connected": False,
    "last_updated": None,
    "error": None
}

@app.route("/conversation", methods=["POST"])
def add_turn():
    """Browser JS posts each conversation turn here"""
    data = request.json
    # Expected: { "role": "user"|"assistant", "text": "...", "ts": timestamp }
    data["ts"] = time.strftime("%H:%M:%S")
    conversation.append(data)
    return jsonify({"status": "ok"})

@app.route("/conversation", methods=["GET"])
def get_conversation():
    """Streamlit reads full conversation from here"""
    return jsonify(list(conversation))

@app.route("/status", methods=["POST"])
def update_status():
    """Browser JS posts connection status here"""
    status.update(request.json)
    status["last_updated"] = time.strftime("%H:%M:%S")
    return jsonify({"status": "ok"})

@app.route("/status", methods=["GET"])
def get_status():
    """Streamlit reads connection status from here"""
    return jsonify(status)

@app.route("/clear", methods=["POST"])
def clear():
    """Streamlit clear button calls this"""
    conversation.clear()
    return jsonify({"status": "cleared"})

if __name__ == "__main__":
    print("✅ Flask mailbox running on http://localhost:5001")
    app.run(port=5001, debug=False)
