from flask import Flask, Blueprint, request, jsonify, send_file, after_this_request
import threading
from patch_worker import process_patch
import os, zipfile, tempfile, psutil, threading, time, gc
from datetime import datetime
from downloader import download_by_rows
from download_worker import download_by_rows
import os
#from db import get_db_connection   # 👈 yahin attach ho raha hai
from db import update_patch_progress,get_patch_progress_by_kb,get_all_progress_by_agent,get_db_connection,update_patch_install_progress


#app = Flask(__name__)
api_bp = Blueprint("api", __name__)
DOWNLOAD_DIR = "downloads"
pending_push = {}
last_heartbeat = {}
download_progress = {
    "status": "idle",
    "total": 0,
    "done": 0
}
# windows , redhat and linux 
@api_bp.route("/api/devices", methods=["GET"])
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
@api_bp.route("/api/window-patch-missing", methods=["GET"])
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
@api_bp.route("/api/window-patch-scan-logs", methods=["GET"])
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
@api_bp.route("/api/agent/heartbeat-status", methods=["GET"])
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
@api_bp.route("/api/redhat-patches-missing", methods=["GET"])
def get_redhat_patches():

    agent_ids = request.args.get("agent_id")

    if not agent_ids:
        return jsonify({"error": "agent_id required"}), 400

    # comma separated → list
    agent_list = [a.strip() for a in agent_ids.split(",") if a.strip()]

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    # dynamic placeholders
    placeholders = ",".join(["%s"] * len(agent_list))

    query = f"""
        SELECT
            id,
            agent_id,
            ip_address,
            package_name,
            version,
            repo,
            created_at
        FROM redhat_patch_list
        WHERE agent_id IN ({placeholders})
        ORDER BY created_at DESC
    """

    cur.execute(query, agent_list)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify({
        "agent_ids": agent_list,
        "count": len(rows),
        "data": rows
    })

# outages status for window , ubuntu and redhat 
@api_bp.route("/api/agent-outages", methods=["GET"])
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
"""
@api_bp.route("/api/window-download", methods=["POST"])
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
"""

# window download patch new one 

@api_bp.route("/api/window-download", methods=["POST"])
def api_download():
    data = request.get_json(force=True)

    if isinstance(data, dict):
        data = [data]

    results = []
    jobs = 0

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    for item in data:
        record_id = item.get("id")
        agent_id = item.get("agent_id")

        if not record_id or not agent_id:
            continue

        cursor.execute("""
            SELECT id, patch_title
            FROM patch_missing
            WHERE id = %s AND agent_id = %s
        """, (record_id, agent_id))

        row = cursor.fetchone()

        if not row:
            continue

        patch_title = row["patch_title"]

        threading.Thread(
            target=process_patch,
            args=(agent_id, patch_title),
            daemon=True
        ).start()

        jobs += 1

        results.append({
            "id": row["id"],
            "agent_id": agent_id,
            "patch_title": patch_title
        })

    cursor.close()
    conn.close()

    return jsonify({
        "job": jobs,
        "status": "accepted",
        "data": results
    })


# ================= Window PROGRESS API ================= 

# old progress bar 
"""
@api_bp.route("/api/window-progress-bar", methods=["GET"])
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
"""
# window latest progress bar latest

@api_bp.route("/api/window-progress-bar", methods=["GET"])
def api_progress():
    agent_ids = request.args.get("agent_id")
    kbs = request.args.get("kb")

    if not agent_ids:
        return jsonify({"error": "agent_id required"}), 400

    # comma separated → list
    agent_ids = [a.strip() for a in agent_ids.split(",")]

    kb_list = None
    if kbs:
        kb_list = [k.strip() for k in kbs.split(",")]

    result = []

    for agent_id in agent_ids:

        if kb_list:
            for kb in kb_list:
                row = get_patch_progress_by_kb(agent_id, kb)
                if row:
                    result.append(row)

        else:
            rows = get_all_progress_by_agent(agent_id)
            result.extend(rows)

    return jsonify({
        "agents": agent_ids,
        "patches": result
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
"""
@api_bp.route("/api/heartbeat", methods=["POST"])
def heartbeat():
    agent_id = request.json.get("agent_id")
    last_heartbeat[agent_id] = datetime.now()
    return jsonify({"status": "alive", "memory": get_memory_stats()})
"""
# =========================================================
# FLAT ZIP (no extra folder)
# =========================================================
def zip_flat(path):

    fd, zip_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)   # Windows lock avoid karne ke liye close

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
# WINDOW SCHEDULE PUSH OLD 
# =========================================================
"""
@api_bp.route("/api/window-schedule-push", methods=["POST"])
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

    return jsonify({
        "status": "scheduled",
        "agent_id": agent_id
    })
"""
# =========================================================
# WINDOW SCHEDULE PUSH new 
# =========================================================
"""
@api_bp.route("/api/window-schedule-push", methods=["POST"])
def schedule_push():

    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    agent_id = str(data.get("agent_id", "")).strip()
    folder = data.get("folder")

    if not agent_id:
        return jsonify({"error": "agent_id required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            "SELECT status FROM devices WHERE TRIM(agent_id)=%s",
            (agent_id,)
        )
        device = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if not device:
        return jsonify({
            "error": "agent not found",
            "agent_id": agent_id
        }), 404

    status = str(device.get("status", "")).strip().lower()

    print("Agent ID:", agent_id)
    print("DB Status:", device.get("status"))
    print("Normalized Status:", status)

    # Agent offline
    if status != "online":
        return jsonify({
            "status": "could not process if agent is offline",
            "agent_id": agent_id,
            "agent_status": status
        }), 200

    # Schedule push
    if folder:
        pending_push[agent_id] = {
            "mode": "folder",
            "folder": folder
        }

        # Stage 1
        log_push(agent_id, folder, "scheduled", 0, "Patch scheduled")

    else:
        pending_push[agent_id] = {
            "mode": "agent",
            "folder": None
        }

        log_push(agent_id, "full_agent", "scheduled", 0, "Full agent scheduled")

    return jsonify({
        "status": "scheduled",
        "agent_id": agent_id,
        "agent_status": status,
        "mode": pending_push[agent_id]["mode"],
        "folder": pending_push[agent_id]["folder"]
    }), 200

"""
# FOLDER MISSING STATUS 

#import os

@api_bp.route("/api/window-schedule-push", methods=["POST"])
def schedule_push():

    global pending_push

    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    agent_id = str(data.get("agent_id", "")).strip()
    folder = data.get("folder")

    if not agent_id:
        return jsonify({"error": "agent_id required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            "SELECT status FROM devices WHERE TRIM(agent_id)=%s",
            (agent_id,)
        )
        device = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if not device:
        return jsonify({
            "error": "agent not found",
            "agent_id": agent_id
        }), 404

    status = str(device.get("status", "")).strip().lower()

    print("Agent ID:", agent_id)
    print("DB Status:", device.get("status"))
    print("Normalized Status:", status)

    # =========================
    # Agent Offline Check
    # =========================
    if status != "online":
        print("Agent is offline, push cancelled")

        return jsonify({
            "status": "could not process if agent is offline",
            "agent_id": agent_id,
            "agent_status": status
        }), 200


    # =========================
    # Schedule Push
    # =========================
    if folder:

        pending_push[agent_id] = {
            "mode": "folder",
            "folder": folder
        }

        log_push(agent_id, folder, "scheduled", 0, "Patch scheduled")

    else:

        pending_push[agent_id] = {
            "mode": "agent",
            "folder": None
        }

        log_push(agent_id, "full_agent", "scheduled", 0, "Full agent scheduled")


    print("Push Scheduled For:", agent_id)
    print("Pending Queue:", pending_push)


    return jsonify({
        "status": "scheduled",
        "agent_id": agent_id,
        "agent_status": status,
        "mode": pending_push[agent_id]["mode"],
        "folder": pending_push[agent_id]["folder"]
    }), 200
    # ===============================
    # FOLDER EXIST CHECK
    # ===============================
    if folder:

        folder_path = os.path.join(DOWNLOAD_DIR, agent_id, folder)

        if not os.path.isdir(folder_path):
            return jsonify({
                "status": "folder missing",
                "agent_id": agent_id,
                "folder": folder
            }), 200   # <-- yaha change kiya

        pending_push[agent_id] = {
            "mode": "folder",
            "folder": folder
        }

        log_push(agent_id, folder, "scheduled", 0, "Patch scheduled")

    else:

        pending_push[agent_id] = {
            "mode": "agent",
            "folder": None
        }

        log_push(agent_id, "full_agent", "scheduled", 0, "Full agent scheduled")

    return jsonify({
        "status": "scheduled",
        "agent_id": agent_id,
        "agent_status": status,
        "mode": pending_push[agent_id]["mode"],
        "folder": pending_push[agent_id]["folder"]
    }), 200
# =========================================================
# WINDOW  GET UPDATE
# =========================================================

def log_push(agent_id, patch_name, status, progress, message):

    conn = get_db_connection()
    cursor = conn.cursor()

    # check if already failed
    cursor.execute("""
        SELECT status 
        FROM push_logs 
        WHERE agent_id=%s AND patch_name=%s
        ORDER BY id DESC LIMIT 1
    """, (agent_id, patch_name))

    row = cursor.fetchone()

    if row and row[0] == "failed":
        # already failed -> do nothing
        return

    cursor.execute("""
        INSERT INTO push_logs(agent_id, patch_name, status, progress, message, created_at)
        VALUES (%s,%s,%s,%s,%s,NOW())
    """, (agent_id, patch_name, status, progress, message))

    conn.commit()
    cursor.close()
    conn.close()
# old get update code     
"""
@api_bp.route("/api/get-update")
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
"""

# new get update code 
@api_bp.route("/api/get-update")
def get_update():

    agent_id = request.args.get("agent_id")

    if not agent_id:
        return jsonify({"error": "agent_id required"}), 400

    job = pending_push.get(agent_id)

    if not job:
        return jsonify({"status": "no_update"})

    patch_name = job.get("folder") or "full_agent"

    base = os.path.join(DOWNLOAD_DIR, agent_id)

    if not os.path.exists(base):
        log_push(agent_id, patch_name, "failed", 0, "Agent folder missing")
        return jsonify({"error": "agent folder missing"}), 404

    if job["mode"] == "agent":
        target = base
        log_push(agent_id, patch_name, "zipping", 0, "Zipping full agent")

    else:
        target = os.path.join(base, job["folder"])

        if not os.path.exists(target):
            log_push(agent_id, patch_name, "failed", 0, "Folder missing")
            return jsonify({"error": "folder missing"}), 404

        log_push(agent_id, patch_name, "zipping", 0, f"Zipping folder {job['folder']}")

    zip_path = zip_flat(target)

    pending_push.pop(agent_id, None)

    log_push(agent_id, patch_name, "sending", 100, "Sending update")

    response = send_file(
        zip_path,
        as_attachment=True,
        download_name=f"{agent_id}.zip"
    )

    @after_this_request
    def cleanup(response):
        try:
            gc.collect()
            os.remove(zip_path)
            print("Deleted:", zip_path)
        except Exception as e:
            print("Cleanup error:", e)
        return response

    log_push(agent_id, patch_name, "completed", 100, "Push completed")

    return response

# =========================================================
# LIVE STATUS old
# =========================================================
'''
@api_bp.route("/api/window-push-status", methods=["GET"])
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

'''
# =========================================================
# LIVE STATUS new
# =========================================================
@api_bp.route("/api/window-push-status", methods=["GET"])
def push_status():

    agent_id = request.args.get("agent_id")
    patch_name = request.args.get("patch_name")

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        query = """
            SELECT agent_id, patch_name, status, progress, message, updated_at
            FROM push_logs
            WHERE 1=1
        """

        params = []

        if agent_id:
            query += " AND agent_id = %s"
            params.append(agent_id)

        if patch_name:
            query += " AND patch_name = %s"
            params.append(patch_name)

        query += " ORDER BY updated_at DESC"

        cursor.execute(query, params)

        rows = cursor.fetchall()

        if not rows:
            return jsonify({"error": "No push record found"}), 404

        agents = list(set([r["agent_id"] for r in rows]))

        patches = []
        for r in rows:
            patches.append({
                "agent_id": r["agent_id"],
                "patch_name": r["patch_name"],
                "progress": r["progress"],
                "status": r["status"],
                "message": r["message"],
                "updated_at": r["updated_at"]
            })

        return jsonify({
            "agents": agents,
            "patches": patches
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500   
# =========================================================
# SERVER STATS
# =========================================================
@api_bp.route("/api/server-stats")
def stats():
    return jsonify({
        "memory": get_memory_stats(),
        "agents_alive": len(last_heartbeat),
        "pending_push": len(pending_push)
    })

@api_bp.route("/")
def home():
    return "🚀 Update Server Running"


@api_bp.route("/api/linux-missing-patches", methods=["GET", "POST"])
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

# ----------------------
# UBuntu patch download
# ----------------------

# ==============================
# DOWNLOAD FUNCTION
# ==============================

# ==============================
# API DOWNLOAD PATCHES
# ==============================
"""
@api_bp.route("/api/ubuntu-download", methods=["POST"])
def download_by_id():

    data = request.get_json()
    ids = data.get("ids")

    if not ids:
        return jsonify({"error": "ids required"}), 400

    # single id ko list me convert
    if not isinstance(ids, list):
        ids = [ids]

    conn = get_db_connection()
    cursor = conn.cursor()

    placeholders = ",".join(["%s"] * len(ids))

    query = f"""
"""
        SELECT id, ip_address, package_name, installed_version, latest_version, agent_id
        FROM linux_patches
        WHERE id IN ({placeholders})
    """
"""
    cursor.execute(query, ids)
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    if not rows:
        return jsonify({"error": "No patches found"}), 404

    packages = []

    for row in rows:
        patch_id, ip, pkg, installed_version, latest_version, agent_id = row

        packages.append({
            "id": patch_id,
            "ip_address": ip,
            "package_name": pkg,
            "installed_version": installed_version,
            "latest_version": latest_version,
            "agent_id": agent_id
        })

    # background thread start
    thread = threading.Thread(
        target=download_by_rows,
        args=(rows, download_progress),
        daemon=True
    )

    thread.start()

    return jsonify({
        "status": "started",
        "total": len(rows),
        "packages": packages
    })
"""

@api_bp.route("/api/ubuntu-download", methods=["POST"])
def download_by_id():
    data = request.get_json()
    ids  = data.get("ids")
 
    if not ids:
        return jsonify({"error": "ids required"}), 400
 
    # Single id → list
    if not isinstance(ids, list):
        ids = [ids]
 
    conn   = get_db_connection()
    cursor = conn.cursor()
 
    placeholders = ",".join(["%s"] * len(ids))
 
    # Fetch patch info + os_version + patch_type from devices join
    query = f"""
        SELECT
            p.id,
            d.ip_address,
            p.package_name,
            p.installed_version,
            p.latest_version,
            p.agent_id,
            d.os_version,
            p.patch_type
        FROM linux_patches p
        JOIN devices d ON p.agent_id = d.agent_id
        WHERE p.id IN ({placeholders})
    """
 
    cursor.execute(query, ids)
    rows = cursor.fetchall()
 
    cursor.close()
    conn.close()
 
    if not rows:
        return jsonify({"error": "No patches found"}), 404
 
    # Reset progress store for this batch
    download_progress.update({
        "status" : "started",
        "total"  : len(rows),
        "done"   : 0,
        "failed" : 0,
        "items"  : {}
    })
 
    # Build packages list for response
    packages = []
    for row in rows:
        patch_id, ip, pkg, installed_ver, latest_ver, agent_id, os_version, patch_type = row
        packages.append({
            "id"                : patch_id,
            "ip_address"        : ip,
            "package_name"      : pkg,
            "installed_version" : installed_ver,
            "latest_version"    : latest_ver,
            "agent_id"          : agent_id
        })
 
        # Pre-populate progress items
        download_progress["items"][str(patch_id)] = {
            "patch_id" : patch_id,
            "ip"       : ip,
            "package"  : pkg,
            "status"   : "queued",
            "files"    : [],
            "message"  : "Waiting..."
        }
 
    # Start background download thread
    thread = threading.Thread(
        target=download_by_rows,
        args=(rows, download_progress),
        daemon=True
    )
    thread.start()
 
    return jsonify({
        "status"   : "started",
        "total"    : len(rows),
        "packages" : packages
    })
 
 
# =========================
# GET /api/ubuntu-download-progress
# Returns live progress of current download batch
# =========================
@api_bp.route("/api/ubuntu-download-progress")
def progress():
    total   = download_progress.get("total", 0)
    done    = download_progress.get("done", 0)
    failed  = download_progress.get("failed", 0)
    percent = round((done / total * 100), 2) if total else 0
 
    return jsonify({
        "status"  : download_progress.get("status", "idle"),
        "total"   : total,
        "done"    : done,
        "failed"  : failed,
        "percent" : percent,
        "items"   : download_progress.get("items", {})
    })
# ==============================
# DOWNLOAD PROGRESS API
# ==============================
@api_bp.route("/api/download-progress")
def get_progress():
    return jsonify(download_progress)


# ===============================
# Ubuntu Download PROGRESS API
# ===============================
"""
@api_bp.route("/api/ubuntu-download-progress")
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
"""



# ===============================
# Ubuntu push Schedule API
# ===============================
"""
@api_bp.route("/api/ubuntu-patch-schedule", methods=["POST"])
def ubuntu_patch_schedule():

    data = request.json
    agent_id = data.get("agent_id")
    patch_file = data.get("patch_file")

    if not agent_id:
        return jsonify({"error": "agent_id required"}), 400

    if not patch_file:
        return jsonify({"error": "patch_file required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT status FROM devices WHERE agent_id = %s", (agent_id,))
    device = cursor.fetchone()

    cursor.close()
    conn.close()

    if not device:
        return jsonify({"error": "agent not found"}), 404

    # check agent status
    if device["status"] != "online":
        return jsonify({
            "status": "could not process if agent is offline",
            "agent_id": agent_id
        }), 400

    # schedule patch
    pending_ubuntu_patch[agent_id] = {
        "patch_file": patch_file
    }

    log_push(agent_id, "scheduled", 0, f"Ubuntu patch scheduled: {patch_file}")

    return jsonify({
        "status": "scheduled",
        "agent_id": agent_id,
        "patch_file": patch_file
    })
"""
# ===============================
# Ubuntu push PROGRESS API
# ===============================
"""
@api_bp.route("/api/linux-patch-check", methods=["POST"])
def linux_patch_check():

    data = request.get_json(force=True)
    agent_id = data.get("agent_id")

    if not agent_id:
        return jsonify({"error": "agent_id required"}), 400

    if agent_id in pending_ubuntu_patch:

        patch = pending_ubuntu_patch.pop(agent_id)

        return jsonify({
            "action": "install_patch",
            "patch_file": patch["patch_file"]
        })

    return jsonify({"action": "none"})
"""
# ===============================
# new  Ubuntu push  API
# ===============================

LINUX_PATCHES_DIR = "/opt/nms/Report/Agent/server/Infraknittech/linux_patches"

# =========================
# PUSH PROGRESS STORE
# =========================
push_progress = {
    "status" : "idle",
    "total"  : 0,
    "done"   : 0,
    "failed" : 0,
    "items"  : {}
}

# Pending patches — agent poll karta hai yahan se
# { agent_id: { "patch_ids": [141, 142] } }
pending_ubuntu_patch = {}

# =========================
# DB HELPERS
# =========================
def ensure_push_log_table():
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ubuntu_push_log (
                id        INT AUTO_INCREMENT PRIMARY KEY,
                agent_id  VARCHAR(100),
                patch_id  INT,
                package   VARCHAR(200),
                version   VARCHAR(100),
                file_name VARCHAR(300),
                status    VARCHAR(50),
                message   TEXT,
                pushed_at DATETIME
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"⚠️  Could not create ubuntu_push_log table: {e}")

def log_push_to_db(agent_id, patch_id, package, version, file_name, status, message):
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO ubuntu_push_log
                (agent_id, patch_id, package, version, file_name, status, message, pushed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (agent_id, patch_id, package, version, file_name, status, message,
              datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"⚠️  DB log error patch {patch_id}: {e}")

def log_patch_alert(agent_id, package, message, category):
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO patch_alert
                (agent_id, kb, message, category, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (agent_id, package, message, category,
              datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"⚠️  patch_alert insert error: {e}")


# =========================
# BACKGROUND PUSH WORKER
# HTTP push nahi — sirf pending_ubuntu_patch mein store karo
# Agent khud pull karega
# =========================
def push_worker(jobs, patch_info, devices, progress_store):
    progress_store["status"] = "running"
 
    for agent_id, patch_id in jobs:
        key     = f"{agent_id}_{patch_id}"
        device  = devices.get(agent_id)
        row     = patch_info.get(patch_id)
        package = row["package_name"] if row else "unknown"
        version = row["latest_version"] if row else ""
        ip      = row["ip_address"] if row else ""
 
        progress_store["items"][key]["status"]  = "processing"
        progress_store["items"][key]["message"] = "Validating..."
 
        # CHANGED — Fresh device status DB se fetch karo (cached dict purana ho sakta hai)
        try:
            _conn   = get_db_connection()
            _cursor = _conn.cursor(dictionary=True)
            _cursor.execute("SELECT status, ip_address FROM devices WHERE agent_id = %s", (agent_id,))
            fresh_device = _cursor.fetchone()
            _cursor.close()
            _conn.close()
            if fresh_device:
                device = fresh_device
        except Exception as e:
            print(f"Could not refresh device status: {e}")
 
        # CHECK 1: Agent offline
        if not device or device["status"].upper() != "ONLINE":
            msg = f"Agent is offline — cannot schedule patch {patch_id}"
            progress_store["items"][key].update({
                "status" : "failed",
                "message": msg,
                "reason" : "AGENT_OFFLINE"
            })
            progress_store["done"]   += 1
            progress_store["failed"] += 1
            log_push_to_db(agent_id, patch_id, package, version, "", "failed", msg)
            log_patch_alert(agent_id, package, msg, "AGENT_OFFLINE")  # CHANGED — log_push() call hataya
            continue
 
        # CHECK 2: Patch not found in DB
        if not row:
            msg = f"Patch {patch_id} not found in DB"
            progress_store["items"][key].update({
                "status" : "failed",
                "message": msg,
                "reason" : "PATCH_NOT_FOUND"
            })
            progress_store["done"]   += 1
            progress_store["failed"] += 1
            log_push_to_db(agent_id, patch_id, package, version, "", "failed", msg)
            log_patch_alert(agent_id, package, msg, "PUSH_FAILED")  # CHANGED — log_push() call hataya
            continue
 
        # CHECK 3: Folder missing
        patch_folder = os.path.join(LINUX_PATCHES_DIR, f"{ip}_{patch_id}")
        if not os.path.exists(patch_folder):
            msg = f"Patch folder is missing — please run download first"
            progress_store["items"][key].update({
                "status" : "failed",
                "message": msg,
                "reason" : "FOLDER_MISSING"
            })
            progress_store["done"]   += 1
            progress_store["failed"] += 1
            log_push_to_db(agent_id, patch_id, package, version, "", "failed", msg)
            log_patch_alert(agent_id, package, msg, "FOLDER_MISSING")  # CHANGED — log_push() call hataya
            continue
 
        # CHECK 4: No .deb files
        deb_files = [f for f in os.listdir(patch_folder) if f.endswith(".deb")]
        if not deb_files:
            msg = "Patch folder is empty — no .deb files found"
            progress_store["items"][key].update({
                "status" : "failed",
                "message": msg,
                "reason" : "FOLDER_EMPTY"
            })
            progress_store["done"]   += 1
            progress_store["failed"] += 1
            log_push_to_db(agent_id, patch_id, package, version, "", "failed", msg)
            log_patch_alert(agent_id, package, msg, "FOLDER_EMPTY")  # CHANGED — log_push() call hataya
            continue
 
        # ALL CHECKS PASSED
        # Store in pending_ubuntu_patch — agent will pull this
        if agent_id not in pending_ubuntu_patch:
            pending_ubuntu_patch[agent_id] = {"patch_ids": []}
 
        if patch_id not in pending_ubuntu_patch[agent_id]["patch_ids"]:
            pending_ubuntu_patch[agent_id]["patch_ids"].append(patch_id)
 
        msg = f"Scheduled — waiting for agent to pull ({len(deb_files)} files ready)"
        progress_store["items"][key].update({
            "status"      : "scheduled",
            "message"     : msg,
            "reason"      : "SUCCESS",
            "total_files" : len(deb_files)
        })
        progress_store["done"] += 1
 
        log_push_to_db(agent_id, patch_id, package, version, "", "scheduled", msg)
        log_patch_alert(agent_id, package, msg, "PATCH_SCHEDULED")  # CHANGED — log_push() call hataya
 
    progress_store["status"] = "completed"
 

# =========================
# POST /api/ubuntu-patch-schedule
# =========================
@api_bp.route("/api/ubuntu-patch-schedule", methods=["POST"])
def ubuntu_patch_schedule():
    ensure_push_log_table()
 
    data    = request.json
    patches = data.get("patches")
 
    if not patches or not isinstance(patches, list):
        return jsonify({"error": "patches list required"}), 400
 
    agent_ids = list(set(p["agent_id"] for p in patches if p.get("agent_id")))
 
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
 
    ph = ",".join(["%s"] * len(agent_ids))
    cursor.execute(f"""
        SELECT agent_id, status, ip_address
        FROM devices WHERE agent_id IN ({ph})
    """, agent_ids)
    devices = {row["agent_id"]: row for row in cursor.fetchall()}
 
    all_patch_ids = []
    for p in patches:
        ids = p.get("patch_ids", [])
        if not isinstance(ids, list):
            ids = [ids]
        all_patch_ids.extend([int(i) for i in ids])
    all_patch_ids = list(set(all_patch_ids))
 
    ph2 = ",".join(["%s"] * len(all_patch_ids))
    cursor.execute(f"""
        SELECT id, agent_id, ip_address, package_name, latest_version
        FROM linux_patches WHERE id IN ({ph2})
    """, all_patch_ids)
    patch_info = {row["id"]: row for row in cursor.fetchall()}
 
    cursor.close()
    conn.close()
 
    jobs       = []
    pre_errors = []
 
    for entry in patches:
        agent_id  = entry.get("agent_id")
        patch_ids = entry.get("patch_ids", [])
        if not isinstance(patch_ids, list):
            patch_ids = [patch_ids]
 
        if agent_id not in devices:
            pre_errors.append({
                "agent_id": agent_id,
                "status"  : "failed",
                "reason"  : "AGENT_NOT_FOUND",
                "message" : f"Agent '{agent_id}' not found in DB"
            })
            continue
 
        if devices[agent_id]["status"].upper() != "ONLINE":
            pre_errors.append({
                "agent_id": agent_id,
                "status"  : "failed",
                "reason"  : "AGENT_OFFLINE",
                "message" : f"Agent '{agent_id}' is offline"
            })
            continue
 
        for patch_id in patch_ids:
            patch_id = int(patch_id)
            row      = patch_info.get(patch_id)
 
            # CHANGED 20-03-2026 14:06 — schedule se pehle folder check karo
            if not row:
                pre_errors.append({
                    "agent_id": agent_id,
                    "patch_id": patch_id,
                    "status"  : "failed",
                    "reason"  : "PATCH_NOT_FOUND",
                    "message" : f"Patch {patch_id} not found in DB"
                })
                continue
 
            ip           = row["ip_address"]
            patch_folder = os.path.join(LINUX_PATCHES_DIR, f"{ip}_{patch_id}")
 
            if not os.path.exists(patch_folder):
                pre_errors.append({
                    "agent_id": agent_id,
                    "patch_id": patch_id,
                    "package" : row["package_name"],
                    "status"  : "failed",
                    "reason"  : "FOLDER_MISSING",
                    "message" : f"Patch folder missing — please run download first: {patch_folder}"
                })
                continue
 
            deb_files = [f for f in os.listdir(patch_folder) if f.endswith(".deb")]
            if not deb_files:
                pre_errors.append({
                    "agent_id": agent_id,
                    "patch_id": patch_id,
                    "package" : row["package_name"],
                    "status"  : "failed",
                    "reason"  : "FOLDER_EMPTY",
                    "message" : f"Patch folder empty — please run download first"
                })
                continue
 
            jobs.append((agent_id, patch_id))
 
    if not jobs:
        return jsonify({
            "status"    : "failed",
            "message"   : "No valid jobs — check pre_errors for details",
            "pre_errors": pre_errors
        }), 400
 
    push_progress.update({
        "status": "started",
        "total" : len(jobs),
        "done"  : 0,
        "failed": 0,
        "items" : {}
    })
 
    packages = []
    for agent_id, patch_id in jobs:
        row     = patch_info.get(patch_id, {})
        package = row.get("package_name", "unknown")
        key     = f"{agent_id}_{patch_id}"
 
        push_progress["items"][key] = {
            "agent_id"   : agent_id,
            "patch_id"   : patch_id,
            "package"    : package,
            "status"     : "queued",
            "total_files": 0,
            "message"    : "Waiting...",
            "reason"     : ""
        }
        packages.append({
            "agent_id": agent_id,
            "patch_id": patch_id,
            "package" : package
        })
 
    thread = threading.Thread(
        target=push_worker,
        args=(jobs, patch_info, devices, push_progress),
        daemon=True
    )
    thread.start()
 
    return jsonify({
        "status"    : "started",
        "total"     : len(jobs),
        "packages"  : packages,
        "pre_errors": pre_errors
    })
 

# =========================
# GET /api/ubuntu-push-progress
# =========================
@api_bp.route("/api/ubuntu-push-progress")
def ubuntu_push_progress():
    total   = push_progress.get("total", 0)
    done    = push_progress.get("done", 0)
    failed  = push_progress.get("failed", 0)
    percent = round((done / total * 100), 2) if total else 0

    return jsonify({
        "status" : push_progress.get("status", "idle"),
        "total"  : total,
        "done"   : done,
        "failed" : failed,
        "percent": percent,
        "items"  : push_progress.get("items", {})
    })


# =========================
# GET /api/ubuntu-patch-pending
# Agent har heartbeat pe yahan se pending patches leta hai
# =========================
@api_bp.route("/api/ubuntu-patch-pending", methods=["GET"])
def ubuntu_patch_pending():
    agent_id = request.args.get("agent_id")

    if not agent_id:
        return jsonify({"error": "agent_id required"}), 400

    pending = pending_ubuntu_patch.get(agent_id)

    if not pending:
        return jsonify({"patches": []})

    patch_ids = pending.get("patch_ids", [])
    if not patch_ids:
        return jsonify({"patches": []})

    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    ph = ",".join(["%s"] * len(patch_ids))
    cursor.execute(f"""
        SELECT p.id, p.package_name, p.latest_version, d.ip_address
        FROM linux_patches p
        JOIN devices d ON p.agent_id = d.agent_id
        WHERE p.id IN ({ph}) AND p.agent_id = %s
    """, (*patch_ids, agent_id))
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    patches = []
    for row in rows:
        patch_id     = row["id"]
        ip           = row["ip_address"]
        package      = row["package_name"]
        version      = row["latest_version"]
        patch_folder = os.path.join(LINUX_PATCHES_DIR, f"{ip}_{patch_id}")

        if not os.path.exists(patch_folder):
            continue

        deb_files = [f for f in os.listdir(patch_folder) if f.endswith(".deb")]
        if not deb_files:
            continue

        patches.append({
            "patch_id": patch_id,
            "package" : package,
            "version" : version,
            "files"   : [
                {
                    "name": f,
                    "url" : f"/api/ubuntu-patch-file/{patch_id}/{f}"
                }
                for f in deb_files
            ]
        })

    # Clear pending after sending
    if patches:
        del pending_ubuntu_patch[agent_id]
        print(f"📤 Sent {len(patches)} patch(es) to agent {agent_id[:12]}..")

    return jsonify({"patches": patches})


# =========================
# GET /api/ubuntu-patch-file/<patch_id>/<filename>
# Agent is URL se .deb file download karta hai
# =========================
@api_bp.route("/api/ubuntu-patch-file/<int:patch_id>/<path:filename>", methods=["GET"])
def ubuntu_patch_file(patch_id, filename):
    from urllib.parse import unquote, quote
 
    from urllib.parse import unquote
    # CHANGED 20-03-2026 12:49 — %3a → : decode karo
    decoded_name = unquote(filename)
 
    if not decoded_name.endswith(".deb"):
        return jsonify({"error": "Only .deb files allowed"}), 400
 
    for folder in os.listdir(LINUX_PATCHES_DIR):
        if folder.endswith(f"_{patch_id}"):
            folder_path = os.path.join(LINUX_PATCHES_DIR, folder)
 
            # CHANGED 20-03-2026 12:49 — 3 versions try karo:
            # 1. decoded naam (: wala)
            # 2. encoded naam (%3a wala) — purani files jo %3a se save huin
            # 3. folder scan — exact match dhundo
            encoded_name = decoded_name.replace(":", "%3a")
            found_path   = None
 
            for try_name in [decoded_name, encoded_name]:
                p = os.path.join(folder_path, try_name)
                if os.path.exists(p):
                    found_path = p
                    break
 
            # Agar dono nahi mile toh folder scan karo
            if not found_path:
                for f in os.listdir(folder_path):
                    if unquote(f) == decoded_name or f == encoded_name:
                        found_path = os.path.join(folder_path, f)
                        break
 
            if found_path:
                print(f"📦 Serving: {found_path}")
                return send_file(
                    found_path,
                    as_attachment=True,
                    download_name=decoded_name,
                    mimetype="application/octet-stream"
                )
 
    return jsonify({"error": f"File not found: {filename}"}), 404
 
 
# =========================
# POST /api/ubuntu-patch-callback
# Agent install ke baad yahan callback karta hai
# =========================
@api_bp.route("/api/ubuntu-patch-callback", methods=["POST"])
def ubuntu_patch_callback():
    data             = request.json
    agent_id         = data.get("agent_id")
    patch_id         = data.get("patch_id")
    package          = data.get("package", "")
    status           = data.get("status", "")
    message          = data.get("message", "")
    downloaded_files = data.get("downloaded_files", [])  # CHANGED 20-03-2026 13:06
    failed_files     = data.get("failed_files", [])      # CHANGED 20-03-2026 13:06
 
    if not all([agent_id, patch_id, status]):
        return jsonify({"error": "agent_id, patch_id, status required"}), 400
 
    # CHANGED 20-03-2026 13:06 — received/partial_received categories
    category_map = {
        "installed"        : "PATCH_INSTALLED",
        "failed"           : "PATCH_INSTALL_FAILED",
        "received"         : "PATCH_RECEIVED",
        "partial_received" : "PATCH_PARTIAL_RECEIVED",
    }
    category = category_map.get(status.lower(), "PATCH_STATUS_UPDATE")
 
    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        now    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
 
        # patch_alert — ek summary row
        cursor.execute("""
            INSERT INTO patch_alert
                (agent_id, kb, message, category, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (agent_id, package,
              message or f"Patch {status}: {package}",
              category, now))
 
        # CHANGED 20-03-2026 13:06 — har downloaded file ka alag log
        if downloaded_files:
            for fname in downloaded_files:
                cursor.execute("""
                    INSERT INTO ubuntu_push_log
                        (agent_id, patch_id, package, version, file_name, status, message, pushed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (agent_id, patch_id, package, "", fname, "received",
                      f"File received by agent", now))
 
        # CHANGED 20-03-2026 13:06 — har failed file ka alag log
        if failed_files:
            for fname in failed_files:
                cursor.execute("""
                    INSERT INTO ubuntu_push_log
                        (agent_id, patch_id, package, version, file_name, status, message, pushed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (agent_id, patch_id, package, "", fname, "failed",
                      f"File not received by agent", now))
 
        # Agar koi file list nahi aayi toh single callback row
        if not downloaded_files and not failed_files:
            cursor.execute("""
                INSERT INTO ubuntu_push_log
                    (agent_id, patch_id, package, version, file_name, status, message, pushed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (agent_id, patch_id, package, "", "callback", status, message, now))
 
        # linux_patches status update
        cursor.execute("""
            UPDATE linux_patches
            SET patch_status = %s, updated_at = %s
            WHERE id = %s AND agent_id = %s
        """, (status, now, patch_id, agent_id))
 
        conn.commit()
        cursor.close()
        conn.close()
 
        # push_progress memory update
        key = f"{agent_id}_{patch_id}"
        if key in push_progress.get("items", {}):
            push_progress["items"][key].update({
                "status"          : status,
                "message"         : message or f"Agent reported: {status}",
                "downloaded_files": downloaded_files,  # CHANGED 20-03-2026 13:06
                "failed_files"    : failed_files        # CHANGED 20-03-2026 13:06
            })
 
        return jsonify({"status": "ok", "recorded": category})
 
    except Exception as e:
        return jsonify({"error": str(e)}), 500 




if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
