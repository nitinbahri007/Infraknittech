import os
import re
import time
import shutil
import subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from db import get_db_connection

# =========================
# CONFIG
# =========================
LINUX_PATCHES_DIR = "/opt/nms/Report/Agent/server/Infraknittech/linux_patches"

docker_map = {
    "20.04": "ubuntu:20.04",
    "22.04": "ubuntu:22.04",
    "24.04": "ubuntu:24.04",
}

codename_map = {
    "20.04": "focal",
    "22.04": "jammy",
    "24.04": "noble",
}

package_map = {
    "apt-ntop": "ntopng",
}

MONGODB_PACKAGES = ["mongodb", "mongodb-org", "mongod", "mongos"]


# =========================
# HELPERS
# =========================
def normalize_version(v):
    m = re.search(r'\d+\.\d+', str(v))
    return m.group() if m else "22.04"


def detect_repo(package, patch_type):
    """Detect repo type from package name."""
    pkg = package.lower()
    pt  = str(patch_type).lower()
    if any(m in pkg for m in MONGODB_PACKAGES):
        return "mongodb"
    if "ntop" in pkg:
        return "ntopng"
    if "external" in pt:
        return "external"
    return "standard"


def is_already_downloaded(final_dest):
    if not os.path.exists(final_dest):
        return False
    return len([f for f in os.listdir(final_dest) if f.endswith(".deb")]) > 0


def cleanup_folder(path):
    if os.path.exists(path):
        shutil.rmtree(path)


# =========================
# DB LOGGING
# =========================
def log_to_db(patch_id, agent_id, ip, package, version,
              file_path, status, message, category, container_log=""):
    """
    Insert into:
      1. patch_download_log  — file download record
      2. patch_alert         — alert/notification record
    """
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        now    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # --- patch_download_log ---
        cursor.execute("""
            INSERT INTO patch_download_log
                (patch_id, ip_address, package_name, version,
                 file_path, status, downloaded_at, container_log)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (patch_id, ip, package, version,
              file_path, status, now, container_log))

        # --- patch_alert ---
        cursor.execute("""
            INSERT INTO patch_alert
                (agent_id, kb, message, category, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (agent_id, package, message, category, now))

        conn.commit()
        cursor.close()
        conn.close()

    except Exception as e:
        print(f"⚠️  DB log error for patch {patch_id}: {e}")


def insert_running_log(patch_id, agent_id, ip, package, version):
    """
    Insert a 'running' record as soon as Docker starts.
    This way, if user refreshes page, progress endpoint
    can still detect that download is in progress.
    """
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        now    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT INTO patch_download_log
                (patch_id, ip_address, package_name, version,
                 file_path, status, downloaded_at, container_log)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (patch_id, ip, package, version,
              "", "running", now, "🐳 Container started..."))

        conn.commit()
        cursor.close()
        conn.close()
        print(f"✅ Running log inserted for patch {patch_id}")

    except Exception as e:
        print(f"⚠️  insert_running_log error for patch {patch_id}: {e}")


def update_running_log_in_db(patch_id, container_log):
    """
    Update the 'running' record every 5 Docker log lines.
    So on page refresh, user sees latest container output.
    """
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE patch_download_log
            SET container_log = %s
            WHERE patch_id = %s
              AND status = 'running'
            ORDER BY downloaded_at DESC
            LIMIT 1
        """, (container_log, patch_id))

        conn.commit()
        cursor.close()
        conn.close()

    except Exception as e:
        print(f"⚠️  update_running_log error for patch {patch_id}: {e}")


def delete_running_log(patch_id):
    """
    Delete the temporary 'running' record once download
    is complete. Final status is written separately by log_to_db().
    """
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM patch_download_log
            WHERE patch_id = %s
              AND status = 'running'
        """, (patch_id,))

        conn.commit()
        cursor.close()
        conn.close()

    except Exception as e:
        print(f"⚠️  delete_running_log error for patch {patch_id}: {e}")


# =========================
# STREAM DOCKER LOGS
# =========================
def run_docker_with_streaming(docker_cmd, patch_id, progress_store):
    """
    Runs docker command and streams output line by line.
    - Updates progress_store in memory  → same session polling
    - Updates DB every 5 lines          → page refresh recovery
    Returns: (returncode, container_logs list)
    """
    container_logs = []

    process = subprocess.Popen(
        docker_cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,   # merge stderr into stdout
        text=True,
        bufsize=1                   # line buffered
    )

    print(f"🐳 Docker started for patch {patch_id}")

    for line in process.stdout:
        line = line.strip()
        if not line:
            continue

        container_logs.append(line)
        print(f"[patch {patch_id}] {line}")

        # ── Live update memory progress_store ──
        if str(patch_id) in progress_store.get("items", {}):
            progress_store["items"][str(patch_id)].update({
                "status"         : "running",
                "message"        : line,
                "container_logs" : list(container_logs)
            })

        # ── Update DB every 5 lines so refresh shows latest logs ──
        if len(container_logs) % 5 == 0:
            update_running_log_in_db(patch_id, "\n".join(container_logs))

    process.wait()
    print(f"🐳 Docker finished for patch {patch_id} — exit code: {process.returncode}")

    # Final DB sync with all logs
    update_running_log_in_db(patch_id, "\n".join(container_logs))

    return process.returncode, container_logs


# =========================
# SINGLE PATCH DOWNLOAD
# =========================
def download_single_patch(patch_id, ip, os_version, package, patch_type,
                          agent_id, latest_version, progress_store):

    actual_package = package_map.get(package.lower(), package)
    version        = normalize_version(os_version)
    codename       = codename_map.get(version, "jammy")
    image          = docker_map.get(version, "ubuntu:22.04")
    final_dest     = os.path.join(LINUX_PATCHES_DIR, f"{ip}_{patch_id}")
    repo_type      = detect_repo(actual_package, patch_type)

    # ── Initialize progress_store item ──
    progress_store["items"][str(patch_id)] = {
        "patch_id"      : patch_id,
        "ip"            : ip,
        "package"       : actual_package,
        "status"        : "running",
        "files"         : [],
        "message"       : "Starting download...",
        "container_logs": []
    }

    # =========================
    # ALREADY DOWNLOADED CHECK
    # =========================
    if is_already_downloaded(final_dest):
        existing = [f for f in os.listdir(final_dest) if f.endswith(".deb")]
        msg      = f"Already downloaded ({len(existing)} files)"

        progress_store["items"][str(patch_id)].update({
            "status"         : "skipped",
            "files"          : existing,
            "message"        : msg,
            "container_logs" : ["⏭️  Skipped — already downloaded"]
        })
        progress_store["done"] += 1

        file_path = os.path.join(final_dest, existing[0]) if existing else final_dest
        log_to_db(patch_id, agent_id, ip, actual_package, latest_version,
                  file_path, "skipped", msg, "ALREADY_DOWNLOADED",
                  container_log="Skipped — already downloaded")
        return "SKIPPED"

    # Temp path under $HOME (snap Docker only allows $HOME mounts)
    home        = os.path.expanduser("~")
    output_path = os.path.join(home, "patches", f"{ip}_{patch_id}")
    os.makedirs(output_path, exist_ok=True)

    # ✅ Insert "running" into DB immediately so refresh can detect it
    insert_running_log(patch_id, agent_id, ip, actual_package, latest_version)

    # Common dependency download snippet
    dep_snippet = f"""
for dep in $(apt-cache depends {actual_package} 2>/dev/null \
    | grep "  Depends:" | awk "{{{{print \$2}}}}" | tr -d "<>"); do
    apt-get download "$dep" 2>/dev/null || true
done"""

    # ── Build Docker command based on repo type ──
    if repo_type == "mongodb":
        docker_cmd = f"""
docker run --rm \
  -v {output_path}:/out \
  -w /out \
  {image} bash -c '
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y gnupg curl software-properties-common 2>&1 | tail -3
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc \
    | gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] \
https://repo.mongodb.org/apt/ubuntu {codename}/mongodb-org/7.0 multiverse" \
    | tee /etc/apt/sources.list.d/mongodb-org-7.0.list
apt-get update -qq
cd /out
apt-get download {actual_package} 2>&1 || true
{dep_snippet}
'
"""
    else:
        docker_cmd = f"""
docker run --rm \
  -v {output_path}:/out \
  -w /out \
  {image} bash -c '
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y software-properties-common 2>&1 | tail -3
add-apt-repository universe -y 2>/dev/null || true
apt-get update -qq
cd /out
apt-get download {actual_package} 2>&1 || true
{dep_snippet}
'
"""

    # ── Run Docker with live log streaming ──
    returncode, container_logs = run_docker_with_streaming(
        docker_cmd, patch_id, progress_store
    )

    container_log_str = "\n".join(container_logs)

    time.sleep(1)

    skip        = {"ntop-bootstrap.deb", "apt-ntop-stable.deb", "apt-ntop.deb"}
    patch_files = [f for f in os.listdir(output_path)
                   if f.endswith(".deb") and f not in skip]

    # ── Remove "running" record before writing final status ──
    delete_running_log(patch_id)

    # =========================
    # FAILED — no .deb found
    # =========================
    if not patch_files:
        cleanup_folder(output_path)

        msg = "Could not download — network issue or package not found"
        progress_store["items"][str(patch_id)].update({
            "status"         : "failed",
            "files"          : [],
            "message"        : msg,
            "container_logs" : container_logs + [f"❌ {msg}"]
        })
        progress_store["done"]   += 1
        progress_store["failed"] += 1

        log_to_db(patch_id, agent_id, ip, actual_package, latest_version,
                  "", "failed", msg, "FAIL_TO_DOWNLOAD",
                  container_log=container_log_str)
        return "FAILED"

    # =========================
    # SUCCESS — move to final dest
    # =========================
    os.makedirs(final_dest, exist_ok=True)
    moved = []
    for f in patch_files:
        shutil.move(os.path.join(output_path, f), os.path.join(final_dest, f))
        moved.append(f)

    cleanup_folder(output_path)

    msg = f"{len(moved)} file(s) downloaded successfully"
    progress_store["items"][str(patch_id)].update({
        "status"         : "success",
        "files"          : moved,
        "path"           : final_dest,
        "message"        : msg,
        "container_logs" : container_logs + [f"✅ {msg}"]
    })
    progress_store["done"] += 1

    # Log each downloaded file to DB
    for f in moved:
        file_path = os.path.join(final_dest, f)
        log_to_db(patch_id, agent_id, ip, actual_package, latest_version,
                  file_path, "downloaded", msg, "DOWNLOADED",
                  container_log=container_log_str)

    return "SUCCESS"


# =========================
# BACKGROUND WORKER
# Called by threading.Thread from routes.py
# =========================
def download_by_ubuntu_rows(rows, progress_store):
    """
    Entry point called from routes.py in a background thread.
    Processes all patch rows using a thread pool (max 3 concurrent).
    """
    progress_store["status"] = "running"
    progress_store["failed"] = 0

    MAX_WORKERS = 3

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}

        for row in rows:
            patch_id      = row[0]
            ip            = row[1]
            pkg           = row[2]
            installed_ver = row[3]
            latest_ver    = row[4]
            agent_id      = row[5]
            os_version    = row[6] if len(row) > 6 else "22.04"
            patch_type    = row[7] if len(row) > 7 else ""

            f = executor.submit(
                download_single_patch,
                patch_id, ip, os_version, pkg, patch_type,
                agent_id, latest_ver, progress_store
            )
            futures[f] = patch_id

        for future in as_completed(futures):
            pid = futures[future]
            try:
                result = future.result()
                print(f"✅ Patch {pid} completed — {result}")
            except Exception as e:
                print(f"❌ Patch {pid} raised exception: {e}")

                # Cleanup running record if unexpected exception
                delete_running_log(pid)

                progress_store["items"][str(pid)].update({
                    "status"         : "failed",
                    "message"        : str(e),
                    "container_logs" : [f"❌ Exception: {str(e)}"]
                })
                progress_store["done"]   += 1
                progress_store["failed"] += 1

    progress_store["status"] = "completed"
    print(f"🎉 All patches done — "
          f"total: {progress_store['total']}, "
          f"done: {progress_store['done']}, "
          f"failed: {progress_store['failed']}")
