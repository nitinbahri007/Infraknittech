from flask import Flask, request, jsonify, render_template
from db import get_db_connection
import threading
import time
import traceback

app = Flask(__name__)

# ================= HEARTBEAT RECEIVER =================
@app.route("/api/heartbeat", methods=["POST"])
def heartbeat():
    data = request.json

    agent_id = data.get("agent_id")
    hostname = data.get("hostname")
    ip_address = data.get("ip_address")
    os_name = data.get("os")
    agent_version = data.get("agent_version")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO devices (agent_id, hostname, ip_address, os_name, agent_version, last_heartbeat, status, updated_at)
            VALUES (%s,%s,%s,%s,%s,NOW(),'ONLINE',NOW())
            ON DUPLICATE KEY UPDATE
                hostname=%s,
                ip_address=%s,
                os_name=%s,
                agent_version=%s,
                last_heartbeat=NOW(),
                status='ONLINE',
                updated_at=NOW()
        """, (
            agent_id, hostname, ip_address, os_name, agent_version,
            hostname, ip_address, os_name, agent_version
        ))

        conn.commit()
        cursor.close()
        conn.close()

        print(f"💓 Heartbeat received from {hostname} ({agent_id})")

    except Exception:
        print("❌ Heartbeat DB error:")
        traceback.print_exc()

    return jsonify({"status": "ok"})


# ================= PATCH ALERT RECEIVER =================
@app.route("/api/patch-alert", methods=["POST"])
def patch_alert():
    data = request.json
    print("🚨 Patch alert received:", data)
    return jsonify({"status": "alert received"})


@app.route("/api/repeat-patch-alert", methods=["POST"])
def repeat_patch_alert():
    data = request.json
    print("🔁 Repeat patch alert received:", data)
    return jsonify({"status": "repeat alert received"})


# ================= PATCH REPORT RECEIVER =================
@app.route("/api/report", methods=["POST"])
def receive_report():
    data = request.json
    print("📥 Patch report received:", data)
    threading.Thread(target=process_report_background, args=(data,), daemon=True).start()
    return jsonify({"status": "accepted"})


def process_report_background(data):
    try:
        agent_id = data.get("agent_id")
        sysinfo = data.get("system_info", {})
        patch_scan = data.get("patch_scan", {})

        conn = get_db_connection()
        cursor = conn.cursor()

        # Update device info
        cursor.execute("""
            INSERT INTO devices (agent_id, hostname, ip_address, os_name, os_version, os_architecture, last_seen, status, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,NOW(),'ONLINE',NOW())
            ON DUPLICATE KEY UPDATE 
                hostname=%s, ip_address=%s, os_name=%s,
                os_version=%s, os_architecture=%s,
                last_seen=NOW(), status='ONLINE', updated_at=NOW()
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

        # Insert scan log
        cursor.execute(
            "INSERT INTO patch_scan_logs (agent_id, scan_duration, scanned_at) VALUES (%s,%s,NOW())",
            (agent_id, patch_scan.get("ScanDurationSeconds"))
        )

        # ================= SAVE MISSING PATCHES =================
        missing_updates = patch_scan.get("MissingUpdates", [])

        if missing_updates:
            print(f"🛑 Processing {len(missing_updates)} missing patches")

            for patch in missing_updates:
                kb = patch.get("KB")

                cursor.execute("""
                    INSERT IGNORE INTO patch_missing (agent_id, patch_title, kb, severity, detected_at)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (
                    agent_id,
                    patch.get("Title"),
                    kb,
                    patch.get("Severity")
                ))

                if cursor.rowcount == 0:
                    print(f"ℹ️ Patch KB{kb} already recorded as missing")
                else:
                    print(f"🚨 New missing patch logged: KB{kb}")

        conn.commit()
        cursor.close()
        conn.close()

        print(f"📊 Patch report processed for {sysinfo.get('hostname')}")

    except Exception:
        print("❌ Report processing error:")
        traceback.print_exc()


# ================= AUTO ONLINE/OFFLINE MONITOR =================
def monitor_device_status():
    while True:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE devices
                SET status='OFFLINE'
                WHERE last_heartbeat IS NULL
                   OR last_heartbeat < (NOW() - INTERVAL 60 MINUTE)
            """)

            cursor.execute("""
                UPDATE devices
                SET status='ONLINE'
                WHERE last_heartbeat >= (NOW() - INTERVAL 60 MINUTE)
            """)

            conn.commit()
            cursor.close()
            conn.close()

            print("🩺 Device status check complete")

        except Exception:
            print("❌ Status monitor error:")
            traceback.print_exc()

        time.sleep(60)


def start_status_monitor():
    t = threading.Thread(target=monitor_device_status, daemon=True)
    t.start()


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
    return "Infra Patch Monitoring Server Running 🚀"


# ================= START SERVER =================
if __name__ == "__main__":
    start_status_monitor()
    app.run(host="0.0.0.0", port=5000, threaded=True)
