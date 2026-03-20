import os
import re
import sys
import time
import shutil
import threading
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

# =========================
# CONFIG
# =========================
LINUX_PATCHES_DIR = "/opt/nms/Report/Agent/server/Infraknittech/linux_patches"
SCRIPT_DIR        = os.path.dirname(os.path.abspath(__file__))

docker_map = {
    "20.04": "ubuntu:20.04",
    "22.04": "ubuntu:22.04",
    "24.04": "ubuntu:24.04",
}

package_map = {
    "apt-ntop": "ntopng",
}

# =========================
# PROGRESS STORE
# Shared dict updated by background threads
# =========================
download_progress = {}

# =========================
# HELPERS
# =========================
def normalize_version(v):
    m = re.search(r'\d+\.\d+', str(v))
    return m.group() if m else "22.04"

def is_already_downloaded(final_dest):
    if not os.path.exists(final_dest):
        return False
    return len([f for f in os.listdir(final_dest) if f.endswith(".deb")]) > 0

def cleanup_folder(path):
    if os.path.exists(path):
        shutil.rmtree(path)

# =========================
# SINGLE PATCH DOWNLOAD
# =========================
def download_single_patch(patch_id, ip, os_version, package, patch_type, progress_store):
    actual_package = package_map.get(package.lower(), package)
    version        = normalize_version(os_version)
    image          = docker_map.get(version, "ubuntu:22.04")
    final_dest     = os.path.join(LINUX_PATCHES_DIR, f"{ip}_{patch_id}")

    # Update progress → running
    progress_store["items"][str(patch_id)] = {
        "patch_id"   : patch_id,
        "ip"         : ip,
        "package"    : actual_package,
        "status"     : "running",
        "files"      : [],
        "message"    : "Downloading..."
    }

    # --- Already downloaded check ---
    if is_already_downloaded(final_dest):
        existing = [f for f in os.listdir(final_dest) if f.endswith(".deb")]
        progress_store["items"][str(patch_id)].update({
            "status" : "skipped",
            "files"  : existing,
            "message": f"Already downloaded ({len(existing)} files)"
        })
        progress_store["done"] += 1
        return "SKIPPED"

    # Temp path under $HOME (snap Docker only allows $HOME mounts)
    home        = os.path.expanduser("~")
    output_path = os.path.join(home, "patches", f"{ip}_{patch_id}")
    os.makedirs(output_path, exist_ok=True)

    is_ntop     = "ntop" in actual_package.lower()
    is_external = "external" in str(patch_type).lower() and not is_ntop

    if is_external:
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
for dep in $(apt-cache depends {actual_package} 2>/dev/null \
    | grep "  Depends:" | awk "{{print \$2}}" | tr -d "<>"); do
    apt-get download "$dep" 2>/dev/null || true
done
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
for dep in $(apt-cache depends {actual_package} 2>/dev/null \
    | grep "  Depends:" | awk "{{print \$2}}" | tr -d "<>"); do
    apt-get download "$dep" 2>/dev/null || true
done
'
"""

    result = subprocess.run(docker_cmd, shell=True, capture_output=True, text=True)

    time.sleep(1)
    skip        = {"ntop-bootstrap.deb", "apt-ntop-stable.deb", "apt-ntop.deb"}
    patch_files = [f for f in os.listdir(output_path)
                   if f.endswith(".deb") and f not in skip]

    # --- FAILED ---
    if not patch_files:
        cleanup_folder(output_path)
        progress_store["items"][str(patch_id)].update({
            "status" : "failed",
            "files"  : [],
            "message": "No .deb files downloaded"
        })
        progress_store["done"]   += 1
        progress_store["failed"] += 1
        return "FAILED"

    # --- SUCCESS → move files ---
    os.makedirs(final_dest, exist_ok=True)
    moved = []
    for f in patch_files:
        shutil.move(os.path.join(output_path, f), os.path.join(final_dest, f))
        moved.append(f)

    cleanup_folder(output_path)

    progress_store["items"][str(patch_id)].update({
        "status" : "success",
        "files"  : moved,
        "path"   : final_dest,
        "message": f"{len(moved)} files downloaded"
    })
    progress_store["done"] += 1
    return "SUCCESS"


# =========================
# BACKGROUND WORKER
# Called by threading.Thread
# =========================
def download_by_rows(rows, progress_store):
    progress_store["status"] = "running"
    progress_store["failed"] = 0

    MAX_WORKERS = 3
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for row in rows:
            # row = (patch_id, ip, pkg, installed_version, latest_version, agent_id, os_version, patch_type)
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
                patch_id, ip, os_version, pkg, patch_type, progress_store
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
