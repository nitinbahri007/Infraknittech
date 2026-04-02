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

# CHANGED 20-03-2026 14:42 — codename map for external repos
codename_map = {
    "20.04": "focal",
    "22.04": "jammy",
    "24.04": "noble",
}

package_map = {
    "apt-ntop": "ntopng",
}

# CHANGED 20-03-2026 14:42 — MongoDB package patterns
MONGODB_PACKAGES = ["mongodb", "mongodb-org", "mongod", "mongos"]

# =========================
# HELPERS
# =========================
def normalize_version(v):
    m = re.search(r'\d+\.\d+', str(v))
    return m.group() if m else "22.04"

# CHANGED 20-03-2026 14:42 — detect repo type from package name
def detect_repo(package, patch_type):
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
def log_to_db(patch_id, agent_id, ip, package, version, file_path, status, message, category):
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
                (patch_id, ip_address, package_name, version, file_path, status, downloaded_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (patch_id, ip, package, version, file_path, status, now))

        # --- patch_alert ---
        # kb column → package_name (as per requirement)
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

    # CHANGED 20-03-2026 14:42 — detect repo type
    repo_type = detect_repo(actual_package, patch_type)

    # Update progress → running
    progress_store["items"][str(patch_id)] = {
        "patch_id" : patch_id,
        "ip"       : ip,
        "package"  : actual_package,
        "status"   : "running",
        "files"    : [],
        "message"  : "Downloading..."
    }

    # =========================
    # ALREADY DOWNLOADED CHECK
    # =========================
    if is_already_downloaded(final_dest):
        existing = [f for f in os.listdir(final_dest) if f.endswith(".deb")]
        msg      = f"Already downloaded ({len(existing)} files)"

        progress_store["items"][str(patch_id)].update({
            "status" : "skipped",
            "files"  : existing,
            "message": msg
        })
        progress_store["done"] += 1

        file_path = os.path.join(final_dest, existing[0]) if existing else final_dest
        log_to_db(patch_id, agent_id, ip, actual_package, latest_version,
                  file_path, "skipped", msg, "ALREADY_DOWNLOADED")
        return "SKIPPED"

    # Temp path under $HOME (snap Docker only allows $HOME mounts)
    home        = os.path.expanduser("~")
    output_path = os.path.join(home, "patches", f"{ip}_{patch_id}")
    os.makedirs(output_path, exist_ok=True)

    # Common dep download snippet
    dep_snippet = f"""
for dep in $(apt-cache depends {actual_package} 2>/dev/null \
    | grep "  Depends:" | awk "{{{{print \$2}}}}" | tr -d "<>"); do
    apt-get download "$dep" 2>/dev/null || true
done"""

    # CHANGED 20-03-2026 14:42 — repo based docker command
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
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu {codename}/mongodb-org/7.0 multiverse" \
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

    result = subprocess.run(docker_cmd, shell=True, capture_output=True, text=True)

    time.sleep(1)
    skip        = {"ntop-bootstrap.deb", "apt-ntop-stable.deb", "apt-ntop.deb"}
    patch_files = [f for f in os.listdir(output_path)
                   if f.endswith(".deb") and f not in skip]

    # =========================
    # FAILED
    # =========================
    if not patch_files:
        cleanup_folder(output_path)

        msg = "Could not download due to network issue or package not found"
        progress_store["items"][str(patch_id)].update({
            "status" : "failed",
            "files"  : [],
            "message": msg
        })
        progress_store["done"]   += 1
        progress_store["failed"] += 1

        # Log failed to DB
        log_to_db(patch_id, agent_id, ip, actual_package, latest_version,
                  "", "failed", msg, "FAIL_TO_DOWNLOAD")
        return "FAILED"

    # =========================
    # SUCCESS — move files to final dest
    # =========================
    os.makedirs(final_dest, exist_ok=True)
    moved = []
    for f in patch_files:
        shutil.move(os.path.join(output_path, f), os.path.join(final_dest, f))
        moved.append(f)

    cleanup_folder(output_path)

    msg = f"{len(moved)} files downloaded successfully"
    progress_store["items"][str(patch_id)].update({
        "status" : "success",
        "files"  : moved,
        "path"   : final_dest,
        "message": msg
    })
    progress_store["done"] += 1

    # Log each downloaded file to DB
    for f in moved:
        file_path = os.path.join(final_dest, f)
        log_to_db(patch_id, agent_id, ip, actual_package, latest_version,
                  file_path, "downloaded", msg, "DOWNLOADED")

    return "SUCCESS"


# =========================
# BACKGROUND WORKER
# Called by threading.Thread from routes.py
# =========================
def download_by_ubuntu_rows(rows, progress_store):
    progress_store["status"] = "running"
    progress_store["failed"] = 0

    MAX_WORKERS = 3
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for row in rows:
            patch_id       = row[0]
            ip             = row[1]
            pkg            = row[2]
            installed_ver  = row[3]
            latest_ver     = row[4]
            agent_id       = row[5]
            os_version     = row[6] if len(row) > 6 else "22.04"
            patch_type     = row[7] if len(row) > 7 else ""

            f = executor.submit(
                download_single_patch,
                patch_id, ip, os_version, pkg, patch_type,
                agent_id, latest_ver, progress_store
            )
            futures[f] = patch_id

        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                pid = futures[future]
                progress_store["items"][str(pid)].update({
                    "status" : "failed",
                    "message": str(e)
                })
                progress_store["done"]   += 1
                progress_store["failed"] += 1

    progress_store["status"] = "completed"
