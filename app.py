from flask import Flask, request, jsonify
import threading

from patch_worker import process_patch
from db import get_patch_progress_by_kb, get_all_progress_by_agent

app = Flask(__name__)


# ================= DOWNLOAD API =================
@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.get_json(force=True)

    if isinstance(data, dict):
        data = [data]

    jobs = 0

    for item in data:
        agent_id = item.get("agent_id")
        patch_title = item.get("patch_title")

        if not agent_id or not patch_title:
            continue

        threading.Thread(
            target=process_patch,
            args=(agent_id, patch_title),
            daemon=True
        ).start()

        jobs += 1

    return jsonify({"status": "accepted", "jobs": jobs})


# ================= PROGRESS API =================
@app.route("/api/progress", methods=["GET"])
def api_progress():
    agent_id = request.args.get("agent_id")
    kb = request.args.get("kb")

    if not agent_id:
        return jsonify({"error": "agent_id required"}), 400

    if kb:
        row = get_patch_progress_by_kb(agent_id, kb)
        return jsonify(row or {"status": "NOT_FOUND"})

    rows = get_all_progress_by_agent(agent_id)
    return jsonify({
        "agent_id": agent_id,
        "patches": rows
    })


# ================= START =================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005)