from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow JS iframe to POST here

# In-memory store for latest sensor values
store = {
    "v0": 0.0,  # Vibration
    "v1": 0.0,  # Temperature
    "v2": 0.0,  # Sound Level
    "v3": 0.0,  # Belt Speed
    "v4": 0,    # Error Code
    "v5": 0,    # Machine Status
}

@app.route("/update", methods=["POST"])
def update():
    store.update(request.json)
    return jsonify({"status": "ok"})

@app.route("/data", methods=["GET"])
def data():
    return jsonify(store)

if __name__ == "__main__":
    app.run(port=5001)
