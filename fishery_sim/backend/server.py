# server.py
import json
import logging
import threading
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from simulation import FisherySimulation

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Resolve paths relative to this file so the server works from any CWD
BASE_DIR = Path(__file__).parent
FRONTEND_DIR = (BASE_DIR / "../frontend").resolve()
DATA_DIR = BASE_DIR / "data"

app = Flask(__name__, static_folder=str(FRONTEND_DIR))
CORS(app)
sim = FisherySimulation()


@app.route("/")
def index():
    return send_from_directory(str(FRONTEND_DIR), "index.html")


@app.route("/App.jsx")
def jsx():
    return send_from_directory(str(FRONTEND_DIR), "App.jsx")


@app.route("/api/state")
def get_state():
    path = DATA_DIR / "current_state.json"
    if not path.exists():
        return jsonify({
            "round": 0,
            "total_rounds": 30,
            "agents": [],
            "lake": {"current": 100, "max": 100, "history": [100], "status": "healthy"},
            "conversations": [],
            "norm_tracker": []
        })
    with open(path) as f:
        return jsonify(json.load(f))


@app.route("/api/agent/<name>")
def get_agent(name):
    # Sanitise name to prevent path traversal
    safe_name = Path(name).name
    path = DATA_DIR / "agent_histories" / f"{safe_name}.json"
    if not path.exists():
        return jsonify([])
    with open(path) as f:
        return jsonify(json.load(f))


@app.route("/api/log")
def get_log():
    path = DATA_DIR / "full_log.json"
    if not path.exists():
        return jsonify([])
    with open(path) as f:
        return jsonify(json.load(f))


@app.route("/api/control", methods=["POST"])
def control():
    data = request.json
    action = data.get("action")

    if action == "pause":
        sim.pause()
        return jsonify({"status": "paused"})

    elif action == "resume":
        sim.resume()
        return jsonify({"status": "running"})

    elif action == "step":
        if not sim.running:
            # Step runs synchronously so UI gets updated state after it returns
            t = threading.Thread(target=sim.step, daemon=True)
            t.start()
            t.join(timeout=120)
        return jsonify({"status": "stepped"})

    elif action == "start":
        if not sim.running:
            def _run_with_logging():
                try:
                    sim.run()
                except Exception as e:
                    import traceback
                    logging.error(f"Simulation thread crashed: {e}\n{traceback.format_exc()}")
                    sim.running = False
            t = threading.Thread(target=_run_with_logging, daemon=True)
            t.start()
        return jsonify({"status": "started"})

    elif action == "speed":
        delay = float(data.get("value", 3))
        sim.set_speed(delay)
        return jsonify({"status": "speed_set", "delay": sim.round_delay})

    return jsonify({"error": "unknown action"}), 400


@app.route("/api/status")
def status():
    return jsonify({
        "running": sim.running,
        "paused": sim.paused,
        "round": sim.current_round,
        "total_rounds": 30
    })


if __name__ == "__main__":
    app.run(debug=False, port=5000, threaded=True)
