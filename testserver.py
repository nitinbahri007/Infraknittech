from flask import Flask, request, jsonify
from datetime import datetime, timedelta

app = Flask(__name__)

# Store last heartbeat
last_heartbeat = {}

# ==============================
# ❤️ HEARTBEAT API
# ==============================
@app.route("/api/heartbeat", methods=["POST"])
def heartbeat():
    data = request.json or {}
    now = datetime.now()

    print("\n==============================")
    print("📥 HEARTBEAT RECEIVED")
    print("==============================")

    # Print raw payload
    for k, v in data.items():
        print(f"{k}: {v}")

    agent_id = data.get("agent_id")

    if not agent_id:
        return jsonify({"error": "agent_id missing"}), 400

    last_heartbeat[agent_id] = now

    print(f"🕒 Time: {now.strftime('%H:%M:%S')}")
    print("================================\n")

    return jsonify({"status": "alive"})


# ==============================
# 📡 GET ALL AGENTS
# ==============================
@app.route("/api/agents", methods=["GET"])
def agents():
    now = datetime.now()
    output = []

    for agent_id, last_seen in last_heartbeat.items():
        diff = (now - last_seen).total_seconds()

        status = "online" if diff < 30 else "offline"

        output.append({
            "agent_id": agent_id,
            "last_seen": last_seen.strftime("%Y-%m-%d %H:%M:%S"),
            "status": status
        })

    return jsonify(output)


# ==============================
# ❤️ HEALTH CHECK
# ==============================
@app.route("/")
def home():
    return "Heartbeat Server Running on 10.10.8.19 ❤️"


# ==============================
# 🚀 RUN SERVER
# ==============================
if __name__ == "__main__":
    # IMPORTANT: 0.0.0.0 for network access
    app.run(host="0.0.0.0", port=5005, debug=True)