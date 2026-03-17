from flask import Flask, request, jsonify, send_file, after_this_request
from datetime import datetime
import os, zipfile, tempfile, psutil, threading, time, gc
from db import get_db_connection

app = Flask(__name__)

DOWNLOAD_DIR = "downloads"
pending_push = {}
last_heartbeat = {}

# =========================================================
# MEMORY MONITOR
# =========================================================
def get_memory_stats():
    process = psutil.Process(os.getpid())
    vm = psutil.virtual_memory()
    return {
        "total_ram_mb": round(vm.total/1024/1024, 2),
        "used_ram_mb": round(vm.used/1024/1024, 2),
        "available_ram_mb": round(vm.available/1024/1024, 2),
        "percent_used": vm.percent,
        "process_ram_mb": round(process.memory_info().rss/1024/1024, 2)
    }

def memory_logger():
    while True:
        mem = get_memory_stats()
        print(f"🧠 RAM Used:{mem['used_ram_mb']}MB | Free:{mem['available_ram_mb']}MB | Proc:{mem['process_ram_mb']}MB")
        time.sleep(30)

# =========================================================
# DB LOGGER
# =========================================================
def log_push(agent_id, status, progress=0, msg=""):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO push_logs(agent_id, status, progress, message)
            VALUES (%s,%s,%s,%s)
        """, (agent_id, status, progress, msg))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print("DB error:", e)

# =========================================================
# HEARTBEAT
# =========================================================
@app.route("/api/heartbeat", methods=["POST"])
def heartbeat():
    agent_id = request.json.get("agent_id")
    last_heartbeat[agent_id] = datetime.now()
    return jsonify({"status": "alive", "memory": get_memory_stats()})

# =========================================================
# FLAT ZIP (no extra folder)
# =========================================================
def zip_flat(path):
    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    zip_path = temp_zip.name
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        if os.path.isfile(path):
            z.write(path, os.path.basename(path))
        else:
            for root, _, files in os.walk(path):
                for f in files:
                    full = os.path.join(root, f)
                    arc = os.path.relpath(full, path)
                    z.write(full, arc)
    return zip_path

# =========================================================
# SCHEDULE PUSH
# =========================================================
@app.route("/api/schedule-push", methods=["POST"])
def schedule_push():
    data = request.json
    agent_id = data.get("agent_id")
    folder = data.get("folder")

    if not agent_id:
        return jsonify({"error": "agent_id required"}), 400

    if folder:
        pending_push[agent_id] = {"mode": "folder", "folder": folder}
        log_push(agent_id, "scheduled", 0, f"Folder scheduled: {folder}")
    else:
        pending_push[agent_id] = {"mode": "agent", "folder": None}
        log_push(agent_id, "scheduled", 0, "Full agent scheduled")

    return jsonify({"status": "scheduled"})

# =========================================================
# GET UPDATE
# =========================================================
@app.route("/api/get-update")
def get_update():
    agent_id = request.args.get("agent_id")
    job = pending_push.get(agent_id)

    if not job:
        return jsonify({"status": "no_update"})

    base = os.path.join(DOWNLOAD_DIR, agent_id)
    if not os.path.exists(base):
        log_push(agent_id, "failed", 0, "Agent folder missing")
        return jsonify({"error": "agent folder missing"}), 404

    # Decide target
    if job["mode"] == "agent":
        target = base
        log_push(agent_id, "zipping", 0, "Zipping full agent")
    else:
        target = os.path.join(base, job["folder"])
        if not os.path.exists(target):
            log_push(agent_id, "failed", 0, "Folder missing")
            return jsonify({"error": "folder missing"}), 404
        log_push(agent_id, "zipping", 0, f"Zipping folder {job['folder']}")

    zip_path = zip_flat(target)
    pending_push.pop(agent_id, None)

    log_push(agent_id, "sending", 100, "Sending update")

    response = send_file(zip_path, as_attachment=True, download_name=f"{agent_id}.zip")

    # ✅ Safe cleanup AFTER response
    @after_this_request
    def cleanup(response):
        try:
            gc.collect()  # Windows unlock
            os.remove(zip_path)
            print("🧹 Deleted:", zip_path)
        except Exception as e:
            print("Cleanup error:", e)
        return response

    log_push(agent_id, "completed", 100, "Push complete")
    return response

# =========================================================
# LIVE STATUS
# =========================================================
@app.route("/api/push-status", methods=["GET"])
def push_status():
    agent_id = request.args.get("agent_id")

    if not agent_id:
        return jsonify({"error": "agent_id required"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT agent_id, status, progress, message, updated_at
            FROM push_logs
            WHERE agent_id = %s
            ORDER BY id DESC
            LIMIT 1
        """, (agent_id,))

        row = cursor.fetchone()

        if not row:
            return jsonify({"error": "No push record found"}), 404

        return jsonify(row)

    except Exception as e:
        return jsonify({"error": str(e)}), 500
# =========================================================
# SERVER STATS
# =========================================================
@app.route("/api/server-stats")
def stats():
    return jsonify({
        "memory": get_memory_stats(),
        "agents_alive": len(last_heartbeat),
        "pending_push": len(pending_push)
    })

@app.route("/")
def home():
    return "🚀 Update Server Running"

# =========================================================
# START
# =========================================================
if __name__ == "__main__":
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    threading.Thread(target=memory_logger, daemon=True).start()
    app.run(host="0.0.0.0", port=5006)