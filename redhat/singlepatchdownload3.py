#!/usr/bin/env python3

"""
RHEL 10 Single Patch Downloader
Usage: python3 download_single_patch.py --id 963 --agent-id 511a4389-12cb-41a4-9f43-18a58a6fd6bf
"""

import argparse
import subprocess
import logging
import sys
from datetime import datetime
from pathlib import Path

# DB connection tumhari existing file se
from db import get_db_connection

# ============================================
# CONFIGURATION — YAHAN APNI VALUES DALO
# ============================================
RH_USERNAME  = "nitinbahri007@gmail.com"
RH_PASSWORD  = "Infraknit@2603#"
UBI_IMAGE    = "registry.access.redhat.com/ubi10/ubi"
DOWNLOAD_DIR = Path.home() / "rhel10-repo" / "patches"
LOG_DIR      = Path.home() / "rhel10-repo"
# ============================================


def setup_logger() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"download_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logger = logging.getLogger(__name__)
    logger.info(f"Log file: {log_file}")
    return logger


def fetch_package(patch_id: str, agent_id: str, logger: logging.Logger) -> dict | None:
    """DB se package info fetch karo using existing db.py connection."""
    logger.info(f"DB se fetch kar raha hoon — ID={patch_id}, Agent={agent_id}")
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT package_name, version, repo, ip_address
            FROM redhat_patch_list
            WHERE id = %s AND agent_id = %s
            LIMIT 1
            """,
            (patch_id, agent_id),
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not row:
            logger.error(f"❌ No package found for ID={patch_id}, Agent={agent_id}")
            return None

        return row

    except Exception as e:
        logger.error(f"❌ DB connection failed: {e}")
        return None


def already_downloaded(dest: Path, pkg_name: str, pkg_ver: str, logger: logging.Logger) -> bool:
    """Check karo agar RPM pehle se exist karta hai."""
    matches = list(dest.glob(f"{pkg_name}-{pkg_ver}*.rpm"))
    if matches:
        logger.warning(f"⚠️  Already exists — skipping: {matches[0].name}")
        return True
    return False


def download_via_podman(pkg_name: str, pkg_ver: str, pkg_repo: str, dest: Path, logger: logging.Logger) -> bool:
    """Podman container ke andar dnf download chalao."""

    dest.mkdir(parents=True, exist_ok=True)

    container_script = f"""

# Step 1: Pehle koi purana registration clean karo
echo '[INFO] Cleaning old registration...'
subscription-manager unregister 2>/dev/null || true
subscription-manager clean 2>/dev/null || true

# Step 2: Register karo (no --auto-attach)
echo '[INFO] Registering Red Hat subscription...'
subscription-manager register \\
  --username='{RH_USERNAME}' \\
  --password='{RH_PASSWORD}'

if [ $? -ne 0 ]; then
  echo '[ERROR] Registration failed!'
  exit 1
fi

# Step 3: Refresh karo
echo '[INFO] Refreshing subscription...'
subscription-manager refresh

# Step 4: Repos enable karo
echo '[INFO] Enabling repos...'
subscription-manager repos \\
  --enable=rhel-10-for-x86_64-baseos-rpms \\
  --enable=rhel-10-for-x86_64-appstream-rpms

if [ $? -ne 0 ]; then
  echo '[ERROR] Repos enable nahi hue!'
  subscription-manager unregister 2>/dev/null || true
  exit 1
fi

# Step 5: Verify
echo '[INFO] Enabled repos:'
subscription-manager repos --list-enabled

# Step 6: yum-utils install
echo '[INFO] Installing yum-utils...'
dnf install -y yum-utils

# Step 7: Package download
echo '[INFO] Downloading {pkg_name}-{pkg_ver} from {pkg_repo}...'
dnf download \\
  --destdir=/repo \\
  --repo='{pkg_repo}' \\
  --resolve \\
  '{pkg_name}-{pkg_ver}'

EXIT_CODE=$?

# Step 8: Unregister
echo '[INFO] Unregistering...'
subscription-manager unregister 2>/dev/null || true

exit $EXIT_CODE
"""

    cmd = [
        "podman", "run", "--rm",
        "--privileged",
        "-v", f"{dest}:/repo",
        UBI_IMAGE,
        "bash", "-c", container_script,
    ]

    logger.info("Podman container start ho raha hai...")
    logger.info(f"Package  : {pkg_name}-{pkg_ver}")
    logger.info(f"Repo     : {pkg_repo}")
    logger.info(f"Save in  : {dest}")

    result = subprocess.run(cmd, text=True)

    if result.returncode == 0:
        logger.info(f"✅ Download SUCCESS: {pkg_name}-{pkg_ver}")
        return True
    else:
        logger.error(f"❌ Download FAILED: {pkg_name}-{pkg_ver}")
        return False


def main():
    parser = argparse.ArgumentParser(description="RHEL 10 Single Patch Downloader")
    parser.add_argument("--id",       required=True, help="Patch ID (e.g. 963)")
    parser.add_argument("--agent-id", required=True, help="Agent UUID")
    args = parser.parse_args()

    logger = setup_logger()

    logger.info("=" * 50)
    logger.info("  RHEL 10 Single Patch Downloader")
    logger.info(f"  ID       : {args.id}")
    logger.info(f"  Agent ID : {args.agent_id}")
    logger.info("=" * 50)

    # Step 1: DB se package fetch
    row = fetch_package(args.id, args.agent_id, logger)
    if not row:
        logger.error("Package nahi mila. Script exit.")
        sys.exit(1)

    pkg_name   = row["package_name"]
    pkg_ver    = row["version"]
    pkg_repo   = row["repo"]
    ip_address = row["ip_address"]

    logger.info(f"Package    : {pkg_name}")
    logger.info(f"Version    : {pkg_ver}")
    logger.info(f"Repo       : {pkg_repo}")
    logger.info(f"IP Address : {ip_address}")

    # Step 2: Destination folder → patches/10.10.10.91_963/
    folder_name = f"{ip_address}_{args.id}"
    dest = DOWNLOAD_DIR / folder_name
    logger.info(f"Folder     : {dest}")

    # Step 3: Already downloaded check
    if already_downloaded(dest, pkg_name, pkg_ver, logger):
        logger.info("Already downloaded — kuch karne ki zaroorat nahi.")
        sys.exit(0)

    # Step 4: Podman se download
    success = download_via_podman(pkg_name, pkg_ver, pkg_repo, dest, logger)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
