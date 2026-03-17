from flask import Flask, request, jsonify, render_template
from datetime import datetime
from db import (
    devices_col,
    patch_logs_col,
    patch_missing_col,
    get_all_devices,
    update_device_status,
    start_outage,
    end_outage
)
import threading
import time
import traceback

app = Flask(__name__)

# ================= CONFIG =================
HEARTBEAT_TIMEOUT = 5
last_heartbeat = {}
device_status = {}
expected_agents = []

# ================= HEARTBEAT =================
@app.route("/api/heartbeat", methods=["POST"])
def heartbeat():
    data = request.json or {}
    agent_id = data.get("agent_id")

    if not agent_id:
        return jsonify({"error": "agent_id missing"}), 400

    now = datetime.now()
    last_heartbeat[agent_id] = now

    try:
        devices_col.update_one(
            {"agent_id": agent_id},
            {
                "$set": {
                    "hostname": data.get("hostname"),
                    "ip_address": data.get("ip_address"),
                    "os_name": data.get("os"),
                    "agent_version": data.get("agent_version"),
                    "last_heartbeat": now,
                    "status": "ONLINE",
                    "updated_at": now
                },
                "$setOnInsert": {
                    "created_at": now
                }
            },
            upsert=True
        )

        if device_status.get(agent_id) != "ONLINE":
            print(f"🟢 {agent_id} BACK ONLINE")
            update_device_status(agent_id, "ONLINE")
            end_outage(agent_id)

        device_status[agent_id] = "ONLINE"
        print(f"❤️ Heartbeat from {agent_id}")

    except Exception:
        traceback.print_exc()

    return jsonify({"status": "alive"}), 200


# ================= PATCH REPORT =================
@app.route("/api/report", methods=["POST"])
def receive_report():
    data = request.json
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

        now = datetime.now()

        # Update device
        devices_col.update_one(
            {"agent_id": agent_id},
            {
                "$set": {
                    "hostname": sysinfo.get("hostname"),
                    "ip_address": sysinfo.get("ip_address"),
                    "os_name": sysinfo.get("os_name"),
                    "os_version": sysinfo.get("os_version"),
                    "os_architecture": sysinfo.get("os_architecture"),
                    "last_seen": now,
                    "status": "ONLINE",
                    "updated_at": now
                }
            },
            upsert=True
        )

        # Insert scan log
        patch_logs_col.insert_one({
            "agent_id": agent_id,
            "scan_duration": patch_scan.get("ScanDurationSeconds"),
            "scanned_at": now
        })

        # Insert missing patches
        for patch in patch_scan.get("MissingUpdates", []):
            patch_missing_col.update_one(
                {
                    "agent_id": agent_id,
                    "kb": patch.get("KB")
                },
                {
                    "$setOnInsert": {
                        "patch_title": patch.get("Title"),
                        "severity": patch.get("Severity"),
                        "detected_at": now
                    }
                },
                upsert=True
            )

        print(f"📊 Patch report processed for {agent_id}")

    except Exception:
        traceback.print_exc()


# ================= DEVICE REFRESH =================
def refresh_devices():
    global expected_agents
    while True:
        expected_agents = get_all_devices()
        time.sleep(30)


# ================= OFFLINE MONITOR =================
def monitor_agents():
    while True:
        now = datetime.now()

        for agent_id in expected_agents:
            last = last_heartbeat.get(agent_id)

            if not last or (now - last).total_seconds() > HEARTBEAT_TIMEOUT:
                if device_status.get(agent_id) != "OFFLINE":
                    print(f"🔴 {agent_id} OFFLINE")
                    update_device_status(agent_id, "OFFLINE")
                    start_outage(agent_id)
                    device_status[agent_id] = "OFFLINE"

        time.sleep(2)


# ================= DASHBOARD =================
@app.route("/dashboard")
def dashboard():
    devices = list(devices_col.find())
    return render_template("dashboard.html", devices=devices)


@app.route("/")
def home():
    return "Infra Patch Monitoring Server Running 🚀"


# ================= START =================
if __name__ == "__main__":
    print("🚀 Infra Patch Monitoring Server Started")

    threading.Thread(target=refresh_devices, daemon=True).start()
    threading.Thread(target=monitor_agents, daemon=True).start()

    app.run(host="0.0.0.0", port=5000, threaded=True)   