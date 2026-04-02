#!/usr/bin/env python3

"""
redhat_worker.py
Background download worker for RHEL 10 patches.
Imported by redhat_download_api.py
"""

import subprocess
import logging
from datetime import datetime
from pathlib import Path

from db import get_db_connection

# ============================================
# CONFIGURATION
# ============================================
RH_USERNAME  = "nitinbahri007@gmail.com"
RH_PASSWORD  = "Infraknit@2603#"
UBI_IMAGE    = "registry.access.redhat.com/ubi10/ubi"
DOWNLOAD_DIR = Path.home() / "rhel10-repo" / "patches"
# ============================================

logger = logging.getLogger(__name__)


def save_log_to_db(patch_id, ip_address, package_name, version, status, file_path=None, container_log=None):
    """Download status DB mein save karo."""
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO patch_download_log
              (patch_id, ip_address, package_name, version, status, file_path, container_log, downloaded_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              status        = VALUES(status),
              file_path     = VALUES(file_path),
              container_log = VALUES(container_log),
              downloaded_at = VALUES(downloaded_at)
            """,
            (patch_id, ip_address, package_name, version, status, file_path, container_log, datetime.now())
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"DB log save failed: {e}")


def download_by_redhat_rows(rows, progress):
    """
    Background thread mein saare RHEL packages download karo.
    rows = tuple: (id, ip_address, package_name, version, repo, agent_id)
    """

    # Step 1: Already downloaded check karo
    to_download = []
    for row in rows:
        patch_id, ip, pkg, version, repo, agent_id = row
        dest = DOWNLOAD_DIR / f"{ip}_{patch_id}"
        dest.mkdir(parents=True, exist_ok=True)
        existing = list(dest.glob(f"{pkg}-{version}*.rpm"))

        if existing:
            files_str = "|".join(str(f) for f in existing)
            progress["items"][str(patch_id)].update({
                "status"  : "done",
                "message" : "Already downloaded",
                "files"   : [str(f) for f in existing]
            })
            progress["done"] += 1
            save_log_to_db(patch_id, ip, pkg, version, "skipped", files_str, "Already exists")
        else:
            to_download.append(row)
            progress["items"][str(patch_id)].update({
                "status"  : "running",
                "message" : "Queued for download..."
            })
            save_log_to_db(patch_id, ip, pkg, version, "running", None, "Queued")

    if not to_download:
        progress["status"] = "completed"
        return

    # Step 2: Volume mounts banao
    volume_args = []
    for row in to_download:
        patch_id, ip, pkg, version, repo, agent_id = row
        folder_name = f"{ip}_{patch_id}"
        dest        = DOWNLOAD_DIR / folder_name
        volume_args += ["-v", f"{dest}:/repo/{folder_name}"]

    # Step 3: Per-package download commands
    pkg_commands = ""
    for row in to_download:
        patch_id, ip, pkg, version, repo, agent_id = row
        folder_name = f"{ip}_{patch_id}"
        pkg_commands += f"""
echo '------------------------------------------------------------'
echo '[DOWNLOAD] ID={patch_id} | {pkg}-{version}'
dnf download \\
  --destdir=/repo/{folder_name} \\
  --repo='{repo}' \\
  --resolve \\
  '{pkg}-{version}'
if [ $? -eq 0 ]; then
  echo "RESULT:SUCCESS:{patch_id}"
else
  echo "RESULT:FAILED:{patch_id}"
fi
"""

    # Step 4: Container script
    container_script = f"""
subscription-manager unregister 2>/dev/null || true
subscription-manager clean    2>/dev/null || true

echo '[INFO] Registering subscription...'
subscription-manager register \\
  --username='{RH_USERNAME}' \\
  --password='{RH_PASSWORD}'

if [ $? -ne 0 ]; then
  echo '[ERROR] Registration failed!'
  exit 1
fi

subscription-manager refresh

subscription-manager repos \\
  --enable=rhel-10-for-x86_64-baseos-rpms \\
  --enable=rhel-10-for-x86_64-appstream-rpms

if [ $? -ne 0 ]; then
  echo '[ERROR] Repos enable nahi hue!'
  subscription-manager unregister 2>/dev/null || true
  exit 1
fi

dnf install -y yum-utils 2>/dev/null

{pkg_commands}

subscription-manager unregister 2>/dev/null || true
"""

    cmd = [
        "podman", "run", "--rm",
        "--privileged",
        "--network", "host",
        *volume_args,
        UBI_IMAGE,
        "bash", "-c", container_script,
    ]

    # Step 5: Container chalao
    try:
        logger.info(f"Podman container start ho raha hai — {len(to_download)} packages...")
        result        = subprocess.run(cmd, capture_output=True, text=True)
        container_log = result.stdout + result.stderr
    except Exception as e:
        container_log = str(e)
        logger.error(f"Podman run failed: {e}")

    # Step 6: Results parse karo
    success_ids = set()
    failed_ids  = set()
    for line in container_log.splitlines():
        if line.startswith("RESULT:SUCCESS:"):
            success_ids.add(line.split(":")[-1].strip())
        elif line.startswith("RESULT:FAILED:"):
            failed_ids.add(line.split(":")[-1].strip())

    # Step 7: Progress update + DB log
    for row in to_download:
        patch_id, ip, pkg, version, repo, agent_id = row
        dest      = DOWNLOAD_DIR / f"{ip}_{patch_id}"
        rpm_files = list(dest.glob("*.rpm"))
        files_str = "|".join(str(f) for f in rpm_files)
        pid_str   = str(patch_id)

        if rpm_files or pid_str in success_ids:
            progress["items"][pid_str].update({
                "status"  : "done",
                "message" : f"Downloaded ({len(rpm_files)} file(s))",
                "files"   : [str(f) for f in rpm_files]
            })
            progress["done"] += 1
            save_log_to_db(patch_id, ip, pkg, version, "done", files_str, container_log)
        else:
            progress["items"][pid_str].update({
                "status"  : "failed",
                "message" : "Download failed",
                "files"   : []
            })
            progress["failed"] += 1
            save_log_to_db(patch_id, ip, pkg, version, "failed", None, container_log)

    progress["status"] = "completed"
