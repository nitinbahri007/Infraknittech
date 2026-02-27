from flask import Flask, request, jsonify, send_file, after_this_request
import threading
from patch_worker import process_patch
import os, zipfile, tempfile, psutil, threading, time, gc
from datetime import datetime
from downloader import download_by_rows
#from db import get_db_connection   # 👈 yahin attach ho raha hai
from db import update_patch_progress,get_patch_progress_by_kb,get_all_progress_by_agent,get_db_connection,update_patch_install_progress


app = Flask(__name__)

DOWNLOAD_DIR = "downloads"
pending_push = {}
last_heartbeat = {}
download_progress = {
    "status": "idle",
    "total": 0,
    "done": 0
}
# windows , redhat and linux 
@app.route("/api/devices", methods=["GET"])
def get_devices():
    status = request.args.get("status")
    agent_ids = request.args.get("agent_id")      # comma-separated
    hostnames = request.args.get("hostname")      # comma-separated
    ip_addresses = request.args.get("ip_address") # comma-separated

    query = """
        SELECT
            id,
            agent_id,
            hostname,
            ip_address,
            os_name,
            os_version,
            os_architecture,
            agent_version,
            last_heartbeat,
            last_seen,
            status,
            updated_at
        FROM devices
        WHERE 1=1
    """
    params = []

    # status
    if status:
        query += " AND status = %s"
        params.append(status)

    # multiple agent_id
    if agent_ids:
        agent_list = [a.strip() for a in agent_ids.split(",") if a.strip()]
        placeholders = ",".join(["%s"] * len(agent_list))
        query += f" AND agent_id IN ({placeholders})"
        params.extend(agent_list)

    # multiple hostname
    if hostnames:
        host_list = [h.strip() for h in hostnames.split(",") if h.strip()]
        placeholders = ",".join(["%s"] * len(host_list))
        query += f" AND hostname IN ({placeholders})"
        params.extend(host_list)

    # multiple ip_address
    if ip_addresses:
        ip_list = [ip.strip() for ip in ip_addresses.split(",") if ip.strip()]
        placeholders = ",".join(["%s"] * len(ip_list))
        query += f" AND ip_address IN ({placeholders})"
        params.extend(ip_list)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(query, params)
    devices = cursor.fetchall()
    cursor.close()
    conn.close()

    return jsonify({
        "count": len(devices),
        "devices": devices
    })
#window patch missing
@app.route("/api/window-patch-missing", methods=["GET"])
def patch_missing():
    agent_id = request.args.get("agent_id")
    severity = request.args.get("severity")
    kb = request.args.get("kb")
    hostname = request.args.get("hostname")
    ip_address = request.args.get("ip_address")

    query = """
        SELECT 
            pm.id,
            pm.agent_id,
            COALESCE(d.hostname, 'N/A') AS hostname,
            COALESCE(d.ip_address, 'N/A') AS ip_address,
            pm.patch_id,
            pm.patch_title,
            pm.kb,
            pm.severity,
            pm.detected_at,
            pm.download_status,
            pm.deploy_status
        FROM patch_missing pm
        LEFT JOIN devices d 
            ON pm.agent_id = d.agent_id
        WHERE 1=1
    """

    params = []

    # ✅ Multiple agent_id
    if agent_id:
        agent_ids = agent_id.split(",")
        placeholders = ",".join(["%s"] * len(agent_ids))
        query += f" AND pm.agent_id IN ({placeholders})"
        params.extend(agent_ids)

    # ✅ Multiple severity
    if severity:
        severities = severity.split(",")
        placeholders = ",".join(["%s"] * len(severities))
        query += f" AND pm.severity IN ({placeholders})"
        params.extend(severities)

    # ✅ Multiple KB
    if kb:
        kbs = kb.split(",")
        placeholders = ",".join(["%s"] * len(kbs))
        query += f" AND pm.kb IN ({placeholders})"
        params.extend(kbs)

    # ✅ Multiple hostname
    if hostname:
        hostnames = hostname.split(",")
        placeholders = ",".join(["%s"] * len(hostnames))
        query += f" AND d.hostname IN ({placeholders})"
        params.extend(hostnames)

    # ✅ Multiple IP Address
    if ip_address:
        ips = ip_address.split(",")
        placeholders = ",".join(["%s"] * len(ips))
        query += f" AND d.ip_address IN ({placeholders})"
        params.extend(ips)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(query, params)
    patches = cursor.fetchall()

    # Convert to True/False
    for patch in patches:
        patch["download_status"] = bool(patch.get("download_status") or 0)
        patch["deploy_status"] = bool(patch.get("deploy_status") or 0)

    cursor.close()
    conn.close()

    return jsonify({
        "count": len(patches),
        "patch_missing": patches
    })

#window patch scan logs 
@app.route("/api/window-patch-scan-logs", methods=["GET"])
def patch_scan_logs():
    agent_id = request.args.get("agent_id")
    date_from = request.args.get("from")
    date_to = request.args.get("to")

    query = """
        SELECT
            id,
            agent_id,
            scan_duration,
            scanned_at
        FROM patch_scan_logs
        WHERE 1=1
    """
    params = []

    if agent_id:
        query += " AND agent_id = %s"
        params.append(agent_id)

    if date_from:
        query += " AND scanned_at >= %s"
        params.append(date_from)

    if date_to:
        query += " AND scanned_at <= %s"
        params.append(date_to)

    query += " ORDER BY scanned_at DESC"

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(query, params)
    logs = cursor.fetchall()
    cursor.close()
    conn.close()

    return jsonify({
        "count": len(logs),
        "patch_scan_logs": logs
    })
# heartbeat status for windows , redhat and ubuntu    
@app.route("/api/agent/heartbeat-status", methods=["GET"])
def heartbeat_status():
    agent_id = request.args.get("agent_id")

    if not agent_id:
        return jsonify({"error": "agent_id required"}), 400

    agent_id = agent_id.strip()

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT
            agent_id,
            last_heartbeat,
            NOW() AS server_time,
            CASE
                WHEN last_heartbeat IS NULL THEN '00:00:00'
                ELSE SEC_TO_TIME(
                    TIMESTAMPDIFF(SECOND, last_heartbeat, NOW())
                )
            END AS time_ago,
            CASE
                WHEN last_heartbeat IS NULL THEN 'OFFLINE'
                WHEN TIMESTAMPDIFF(SECOND, last_heartbeat, NOW()) <= 300
                    THEN 'ONLINE'
                ELSE 'OFFLINE'
            END AS status
        FROM devices
        WHERE agent_id = %s
    """, (agent_id,))

    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return jsonify({"error": "agent not found"}), 404

    return jsonify(row)

#redhat patch missing update 
@app.route("/api/redhat-patches-missing", methods=["GET"])
def get_redhat_patches():
    agent_id = request.args.get("agent_id")

    if not agent_id:
        return jsonify({"error": "agent_id required"}), 400

    agent_id = agent_id.strip()

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT
            id,
            agent_id,
            ip_address,
            package_name,
            version,
            repo,
            created_at
        FROM redhat_patch_list
        WHERE agent_id = %s
        ORDER BY created_at DESC
    """, (agent_id,))

    rows = cur.fetchall()

    cur.close()
    conn.close()

    if not rows:
        return jsonify({
            "agent_id": agent_id,
            "count": 0,
            "data": []
        })

    return jsonify({
        "agent_id": agent_id,
        "count": len(rows),
        "data": rows
    })

# outages status for window , ubuntu and redhat 
@app.route("/api/agent-outages", methods=["GET"])
def get_agent_outages():
    hostname = request.args.get("hostname")
    date_from = request.args.get("from")
    date_to = request.args.get("to")
    min_duration = request.args.get("min_duration")

    query = """
        SELECT
            id,
            hostname,
            down_start,
            down_end,
            duration_seconds
        FROM agent_outages
        WHERE 1=1
    """
    params = []

    if hostname:
        query += " AND hostname = %s"
        params.append(hostname)

    if date_from:
        query += " AND down_start >= %s"
        params.append(date_from)

    if date_to:
        query += " AND down_start <= %s"
        params.append(date_to)

    if min_duration:
        query += " AND duration_seconds >= %s"
        params.append(min_duration)

    query += " ORDER BY down_start DESC"

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify({"count": len(rows), "agent_outages": rows})



# window download patch
@app.route("/api/window-download", methods=["POST"])
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


# ================= Window PROGRESS API =================
@app.route("/api/window-progress-bar", methods=["GET"])
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
# WINDOW SCHEDULE PUSH
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
# WINDOW  GET UPDATE
# =========================================================
@app.route("/api/window-get-update")
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
@app.route("/api/window-push-status", methods=["GET"])
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


@app.route("/api/linux-missing-patches", methods=["GET", "POST"])
def linux_missing_patches():
    try:
        data = request.get_json(silent=True) if request.method == "POST" else request.args

        agent_ids = data.get("agent_id")
        ip = data.get("ip")
        packages = data.get("package")
        patch_type = data.get("patch_type")

        # convert comma string → list
        if isinstance(agent_ids, str) and "," in agent_ids:
            agent_ids = agent_ids.split(",")

        if isinstance(packages, str) and "," in packages:
            packages = packages.split(",")

        query = """
            SELECT 
                lp.id,
                lp.agent_id,
                d.hostname,
                lp.ip_address,
                lp.package_name,
                lp.installed_version,
                lp.latest_version,
                lp.patch_type,
                lp.scan_time
            FROM linux_patches lp
            LEFT JOIN devices d ON lp.agent_id = d.agent_id
            WHERE 1=1
        """

        params = []

        # ----------------------
        # MULTI AGENT
        # ----------------------
        if agent_ids:
            if isinstance(agent_ids, list):
                placeholders = ",".join(["%s"] * len(agent_ids))
                query += f" AND lp.agent_id IN ({placeholders})"
                params.extend(agent_ids)
            else:
                query += " AND lp.agent_id = %s"
                params.append(agent_ids)

        # ----------------------
        # IP FILTER
        # ----------------------
        if ip:
            query += " AND lp.ip_address = %s"
            params.append(ip)

        # ----------------------
        # MULTI PACKAGE SUPPORT
        # ----------------------
        if packages:
            if isinstance(packages, list):
                placeholders = ",".join(["%s"] * len(packages))
                query += f" AND lp.package_name IN ({placeholders})"
                params.extend(packages)
            else:
                query += " AND lp.package_name LIKE %s"
                params.append(f"%{packages}%")

        # ----------------------
        # PATCH TYPE
        # ----------------------
        if patch_type:
            query += " AND lp.patch_type = %s"
            params.append(patch_type)

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, params)
        patches = cursor.fetchall()

        cursor.close()
        conn.close()

        return jsonify({
            "status": "success",
            "count": len(patches),
            "data": patches
        })

    except Exception as e:
        print("API ERROR:", e)
        return jsonify({"status": "error", "message": str(e)}), 500




@app.route("/api/ubuntu-download", methods=["POST"])
def download_by_id():
    data = request.get_json()
    ids = data.get("ids")  # can be single or list

    if not ids:
        return jsonify({"error": "ids required"}), 400

    # single → list
    if not isinstance(ids, list):
        ids = [ids]

    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch rows
    placeholders = ",".join(["%s"] * len(ids))
    cursor.execute(f"""
        SELECT id, ip_address, package_name, latest_version
        FROM linux_patches
        WHERE id IN ({placeholders})
    """, ids)

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return jsonify({"error": "No patches found"}), 404

    # Background download
    thread = threading.Thread(
        target=download_by_rows,
        args=(rows, download_progress),
        daemon=True
    )
    thread.start()

    return jsonify({
        "status": "started",
        "total": len(rows),
        "ids": ids
    })

# ===============================
# Ubuntu Download PROGRESS API
# ===============================
@app.route("/api/ubuntu-download-progress")
def progress():
    total = download_progress.get("total", 0)
    done = download_progress.get("done", 0)
    percent = (done / total * 100) if total else 0

    return jsonify({
        "status": download_progress.get("status"),
        "total": total,
        "done": done,
        "percent": round(percent, 2),
        "items": download_progress.get("items", {})
    })



# ===============================
# Ubuntu push Schedule API
# ===============================

# ===============================
# Ubuntu push PROGRESS API
# ===============================




if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)