from flask import Flask, request, jsonify, render_template
from datetime import datetime
from db import (
    get_db_connection,
    get_all_devices,
    update_device_status,
    start_outage,
    end_outage
)
import threading
import time
import traceback
import socket
import platform
import os
from api import api_bp

from linuxpatchupload5 import process_uploaded_packages
app = Flask(__name__)

app.register_blueprint(api_bp)


# ================= CONFIG =================
HEARTBEAT_TIMEOUT = 40
last_heartbeat = {}
device_status = {}
expected_agents = []


# ================= HEARTBEAT NEW  =================
@app.route("/api/heartbeat", methods=["POST"])
def heartbeat():

    print("🔥 HEARTBEAT API CALLED")

    data = request.json or {}
    print("🔥 DATA RECEIVED:")
    print(data)
    agent_id = data.get("agent_id")

    if not agent_id:
        print("❌ agent_id missing")
        return jsonify({"error": "agent_id missing"}), 400

    hostname = data.get("hostname") or socket.gethostname()
    ip_address = data.get("ip_address") or request.remote_addr
    os_name = data.get("os_name") or platform.system()
    os_version = data.get("os_version") or platform.version()
    os_architecture = data.get("os_architecture") or platform.machine()
    agent_version = data.get("agent_version") or "1.0"

    now = datetime.now()

    print("📡 Heartbeat received")
    print("Agent ID:", agent_id)
    print("Hostname:", hostname)
    print("IP:", ip_address)
    print("OS:", os_name, os_version)
    print("Agent Version:", agent_version)

    last_heartbeat[agent_id] = now

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        print("💾 Updating DB...")

        # 🔥 NEW LOGIC: Same IP ke dusre agents disable karo
        cursor.execute("""
        UPDATE devices 
        SET status='DISABLED', updated_at=NOW()
        WHERE ip_address=%s AND agent_id != %s
        """, (ip_address, agent_id))

        # 🔥 EXISTING LOGIC (unchanged)
        cursor.execute("""
        INSERT INTO devices (
            agent_id, hostname, ip_address, os_name,
            os_version, os_architecture,
            agent_version, last_heartbeat, status, updated_at
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,NOW(),'ONLINE',NOW())
        ON DUPLICATE KEY UPDATE
            hostname=VALUES(hostname),
            ip_address=VALUES(ip_address),
            os_name=VALUES(os_name),
            os_version=VALUES(os_version),
            os_architecture=VALUES(os_architecture),
            agent_version=VALUES(agent_version),
            last_heartbeat=NOW(),
            status='ONLINE',
            updated_at=NOW()
        """, (
            agent_id,
            hostname,
            ip_address,
            os_name,
            os_version,
            os_architecture,
            agent_version
        ))

        conn.commit()

        print("✅ DB updated")
        print("Rows affected:", cursor.rowcount)

        cursor.close()
        conn.close()

        device_status[agent_id] = "ONLINE"

        print(f"[{now.strftime('%H:%M:%S')}] ❤️ {agent_id} ONLINE")

    except Exception as e:
        print("❌ DB ERROR:", e)
        traceback.print_exc()

    return jsonify({"status": "alive", "test": "nitin"}), 200
# ================= PATCH REPORT =================
@app.route("/api/report", methods=["POST"])
def receive_report():
    data = request.json
    print("📥 Patch report received")
    threading.Thread(
        target=process_report_background,
        args=(data,),
        daemon=True
    ).start()
    return jsonify({"status": "accepted"})


def process_report_background(data):
    try:
        agent_id = data.get("agent_id")
        sysinfo = data.get("system_info", {})
        patch_scan = data.get("patch_scan", {})

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO devices (
                agent_id, hostname, ip_address, os_name,
                os_version, os_architecture,
                last_seen, status, updated_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,NOW(),'ONLINE',NOW())
            ON DUPLICATE KEY UPDATE
                hostname=%s,
                ip_address=%s,
                os_name=%s,
                os_version=%s,
                os_architecture=%s,
                last_seen=NOW(),
                status='ONLINE',
                updated_at=NOW()
        """, (
            agent_id,
            sysinfo.get("hostname"),
            sysinfo.get("ip_address"),
            sysinfo.get("os_name"),
            sysinfo.get("os_version"),
            sysinfo.get("os_architecture"),
            sysinfo.get("hostname"),
            sysinfo.get("ip_address"),
            sysinfo.get("os_name"),
            sysinfo.get("os_version"),
            sysinfo.get("os_architecture")
        ))

        cursor.execute("""
            INSERT INTO patch_scan_logs
            (agent_id, scan_duration, scanned_at)
            VALUES (%s,%s,NOW())
        """, (agent_id, patch_scan.get("ScanDurationSeconds")))

        for patch in patch_scan.get("MissingUpdates", []):
            cursor.execute("""
                INSERT IGNORE INTO patch_missing
                (agent_id, patch_title, kb, severity, detected_at)
                VALUES (%s,%s,%s,%s,NOW())
            """, (
                agent_id,
                patch.get("Title"),
                patch.get("KB"),
                patch.get("Severity")
            ))

        conn.commit()
        cursor.close()
        conn.close()

        print(f"📊 Patch report processed for {agent_id}")

    except Exception:
        print("❌ Report processing error:")
        traceback.print_exc()

# ================= DEVICE REFRESH =================
def refresh_devices():
    global expected_agents
    while True:
        try:
            agents = get_all_devices()
            expected_agents = agents

            # Init device status map
            for a in agents:
                device_status.setdefault(a, "ONLINE")

            print("🔄 Agents:", expected_agents)

        except Exception as e:
            print("Refresh error:", e)

        time.sleep(30)


# ================= OFFLINE MONITOR =================
def monitor_agents():
    print("🛡 Offline monitor running")

    while True:
        now = datetime.now()

        for agent_id in expected_agents:
            last = last_heartbeat.get(agent_id)

            if not last or (now - last).total_seconds() > HEARTBEAT_TIMEOUT:
                if device_status.get(agent_id) != "OFFLINE":
                    print(f"[{now.strftime('%H:%M:%S')}] 🔴 {agent_id} OFFLINE")

                    try:
                        update_device_status(agent_id, "OFFLINE")
                        start_outage(agent_id)
                        device_status[agent_id] = "OFFLINE"
                    except Exception as e:
                        print("Offline error:", e)

        time.sleep(2)


# ================= DASHBOARD =================
@app.route("/dashboard")
def dashboard():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM devices")
    devices = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("dashboard.html", devices=devices)


@app.route("/")
def home():
    return "Infra Monitoring Server Running 🚀"

"""
UPLOAD_DIR = "uploads"

os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.route("/api/upload-packages", methods=["POST"])
def upload_packages():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400

    file = request.files["file"]
    agent_id = request.form.get("agent_id", "unknown")

    filename = f"{agent_id}_packages.txt"
    path = os.path.join(UPLOAD_DIR, filename)
    file.save(path)
"""
UPLOAD_DIR = "uploads"
# directory create ho jayegi agar exist nahi hai
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.route("/api/upload-packages", methods=["POST"])
def upload_packages():

    # ===============================
    # VALIDATION
    # ===============================
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    agent_id = request.form.get("agent_id", "unknown").strip()

    # ===============================
    # CREATE FOLDER IF NOT EXISTS
    # ===============================
    if not os.path.exists(UPLOAD_DIR):
        os.makedirs(UPLOAD_DIR)

    filename = f"{agent_id}_packages.txt"
    path = os.path.join(UPLOAD_DIR, filename)

    # ===============================
    # SAVE FILE
    # ===============================
    try:
        file.save(path)
        print(f"✅ File saved: {path}")
    except Exception as e:
        print("❌ File save failed:", e)
        return jsonify({"error": "File save failed"}), 500

    # ===============================
    # 🔥 TRIGGER PROCESSING (BACKGROUND)
    # ===============================
    try:
        print("🚀 Starting background processing...")

        threading.Thread(
            target=process_uploaded_packages,
            daemon=True
        ).start()

    except Exception as e:
        print("❌ Processing trigger failed:", e)

    # ===============================
    # RESPONSE
    # ===============================
    return jsonify({
        "status": "uploaded",
        "agent_id": agent_id,
        "file": filename,
        "path": path
    })



# ================= START =================
if __name__ == "__main__":
    print("🚀 Server Started")

    threading.Thread(target=refresh_devices, daemon=True).start()
    threading.Thread(target=monitor_agents, daemon=True).start()

    app.run(host="0.0.0.0", port=5000, threaded=True)
