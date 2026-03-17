from flask import Flask, request, jsonify, send_file
from datetime import datetime
import os
import zipfile
import tempfile
from db import get_db_connection

app = Flask(__name__)

# ================= CONFIG =================
DOWNLOAD_DIR = "downloads"
pending_push = {}         # {agent_id: folder}
last_heartbeat = {}


# =========================================================
# INSERT PUSH LOG
# =========================================================
def insert_log(agent_id, folder, status, progress, message):

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        query = """
        INSERT INTO push_logs(agent_id, folder, status, progress, message)
        VALUES (%s,%s,%s,%s,%s)
        """

        cursor.execute(query, (agent_id, folder, status, progress, message))
        conn.commit()

        cursor.close()
        conn.close()

    except Exception as e:
        print("DB ERROR:", e)


# =========================================================
# HEARTBEAT API
# =========================================================
@app.route("/api/heartbeat", methods=["POST"])
def heartbeat():

    data = request.json or {}
    agent_id = data.get("agent_id")

    if not agent_id:
        return jsonify({"error": "agent_id missing"}), 400

    last_heartbeat[agent_id] = datetime.now()

    print(f"💓 Heartbeat from {agent_id}")

    return jsonify({"status": "alive"})


# =========================================================
# ZIP HELPER
# =========================================================
def zip_folder(folder_path):

    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    zip_path = temp_zip.name

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:

        for root, dirs, files in os.walk(folder_path):

            for file in files:

                full = os.path.join(root, file)
                arc = os.path.relpath(full, folder_path)
                zipf.write(full, arc)

    return zip_path


# =========================================================
# ADMIN: SCHEDULE PUSH
# =========================================================
@app.route("/api/schedule-push", methods=["POST"])
def schedule_push():

    data = request.json

    agent_id = data.get("agent_id")
    folder = data.get("folder")

    if not agent_id or not folder:
        return jsonify({"error": "agent_id and folder required"}), 400

    pending_push[agent_id] = folder

    insert_log(agent_id, folder, "scheduled", 0, f"Folder scheduled: {folder}")

    print(f"📦 Push scheduled for {agent_id} -> {folder}")

    return jsonify({"status": "scheduled", "agent": agent_id})


# =========================================================
# AGENT POLL API
# =========================================================
@app.route("/api/get-update", methods=["GET"])
def get_update():

    agent_id = request.args.get("agent_id")

    if not agent_id:
        return jsonify({"error": "agent_id missing"}), 400

    if agent_id not in pending_push:
        return jsonify({"status": "no_update"})

    folder = pending_push[agent_id]

    folder_path = os.path.join(DOWNLOAD_DIR, agent_id, "patches", folder)

    if not os.path.exists(folder_path):

        insert_log(agent_id, folder, "failed", 0, "Patch folder not found")
        return jsonify({"error": f"{folder_path} not found"}), 404

    print(f"📦 Zipping folder for agent {agent_id}")

    insert_log(agent_id, folder, "zipping", 10, f"Zipping folder {folder}")

    try:

        zip_path = zip_folder(folder_path)

        insert_log(agent_id, folder, "sending", 50, "Sending update")

        pending_push.pop(agent_id, None)

        filename = f"{folder}.zip"

        return send_file(zip_path, as_attachment=True, download_name=filename)

    except Exception as e:

        insert_log(agent_id, folder, "failed", 0, str(e))
        return jsonify({"error": str(e)}), 500


# =========================================================
# AGENT STATUS UPDATE
# =========================================================
@app.route("/api/update-status", methods=["POST"])
def update_status():

    data = request.json

    agent_id = data.get("agent_id")
    folder = data.get("folder")
    status = data.get("status")
    progress = data.get("progress", 0)
    message = data.get("message", "")

    insert_log(agent_id, folder, status, progress, message)

    return jsonify({"status": "logged"})


# =========================================================
# HEALTH CHECK
# =========================================================
@app.route("/")
def home():
    return "🚀 Update Server Running"


# =========================================================
# START
# =========================================================
if __name__ == "__main__":

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    print("🚀 Server Started on port 5006")

    app.run(host="0.0.0.0", port=5006)