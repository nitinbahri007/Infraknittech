from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import socket, platform

app = Flask(__name__)

# 🔥 Store last heartbeat
last_heartbeat = {}

# ==============================
# ❤️ HEARTBEAT API
# ==============================
@app.route("/api/heartbeat", methods=["POST"])
def heartbeat():
    data = request.json or {}
    agent_id = data.get("agent_id")

    if not agent_id:
        return jsonify({"error": "agent_id missing"}), 400

    # 🔥 AUTO FALLBACK VALUES
    hostname = data.get("hostname") or socket.gethostname()
    ip_address = data.get("ip_address") or request.remote_addr
    os_name = data.get("os") or platform.system()
    os_version = data.get("os_version") or platform.version()
    os_architecture = data.get("os_arch") or platform.machine()
    agent_version = data.get("agent_version") or "1.0"

    now = datetime.now()
    last_heartbeat[agent_id] = now

    # ✅ LOG PRINT
    print(f"[{now.strftime('%H:%M:%S')}] ❤️ {agent_id} | {hostname} | {ip_address} | {os_name} {os_version} ({os_architecture}) | v{agent_version}")

    return jsonify({"status": "alive"})


# ==============================
# 📡 GET ONLINE AGENTS
# ==============================
@app.route("/api/agents", methods=["GET"])
def agents():
    now = datetime.now()
    output = []

    for agent_id, last_seen in last_heartbeat.items():
        diff = (now - last_seen).total_seconds()
        status = "online" if diff < 60 else "offline"

        output.append({
            "agent_id": agent_id,
            "last_seen": last_seen.strftime("%Y-%m-%d %H:%M:%S"),
            "status": status
        })

    return jsonify(output)


# ==============================
# 🧪 HEALTH CHECK
# ==============================
@app.route("/")
def home():
    return "Heartbeat Server Running ❤️"

# ==============================
# 🚀 RUN SERVER
# ==============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005, debug=True)