#!/usr/bin/env python3

"""
RHEL 10 Patch Downloader — Multiple IDs + Multiple Agent IDs

Case 1: 1 ID,  1 Agent
  python3 download_patch.py --ids 963 --agent-ids 511a4389-12cb-41a4-9f43-18a58a6fd6bf

Case 2: 2 IDs, 1 Agent (same agent for all)
  python3 download_patch.py --ids 963 964 --agent-ids 511a4389-12cb-41a4-9f43-18a58a6fd6bf

Case 3: 2 IDs, 2 Agents (963→AgentA, 964→AgentB)
  python3 download_patch.py --ids 963 964 --agent-ids AAA-111 BBB-222
"""

import argparse
import subprocess
import logging
import sys
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


def build_id_agent_pairs(ids: list, agent_ids: list, logger: logging.Logger) -> list:
    """
    IDs aur Agent IDs ko pair karo:
    - 1 agent  → sab IDs ke liye same agent
    - N agents → 1:1 mapping (IDs count == agents count hona chahiye)
    Returns: [{"id": "963", "agent_id": "AAA"}, ...]
    """
    if len(agent_ids) == 1:
        # Case 1 & 2: Ek agent sab ke liye
        pairs = [{"id": pid, "agent_id": agent_ids[0]} for pid in ids]
    elif len(agent_ids) == len(ids):
        # Case 3: 1:1 mapping
        pairs = [{"id": pid, "agent_id": aid} for pid, aid in zip(ids, agent_ids)]
    else:
        logger.error(
            f"❌ Mismatch: {len(ids)} IDs hain but {len(agent_ids)} agent-ids hain. "
            "Ya 1 agent-id do (sab ke liye) ya IDs ke barabar agent-ids do."
        )
        sys.exit(1)
    return pairs


def fetch_packages(pairs: list, logger: logging.Logger) -> list:
    """DB se packages fetch karo — har (id, agent_id) pair ke liye."""
    logger.info(f"DB se {len(pairs)} packages fetch kar raha hoon...")
    results = []

    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        for pair in pairs:
            cursor.execute(
                """
                SELECT id, package_name, version, repo, ip_address, agent_id
                FROM redhat_patch_list
                WHERE id = %s AND agent_id = %s
                LIMIT 1
                """,
                (pair["id"], pair["agent_id"]),
            )
            row = cursor.fetchone()
            if row:
                results.append(row)
            else:
                logger.warning(f"⚠️  Not found in DB — ID={pair['id']}, Agent={pair['agent_id']}")

        cursor.close()
        conn.close()

    except Exception as e:
        logger.error(f"❌ DB connection failed: {e}")
        sys.exit(1)

    return results


def already_downloaded(dest: Path, pkg_name: str, pkg_ver: str) -> bool:
    return len(list(dest.glob(f"{pkg_name}-{pkg_ver}*.rpm"))) > 0


def download_via_podman(packages: list, logger: logging.Logger) -> dict:
    """Ek hi podman container mein saare packages download karo."""

    to_download = []
    skipped     = []

    for pkg in packages:
        dest = DOWNLOAD_DIR / f"{pkg['ip_address']}_{pkg['id']}"
        if already_downloaded(dest, pkg["package_name"], pkg["version"]):
            logger.warning(f"⚠️  SKIP (exists): {pkg['package_name']}-{pkg['version']} → {dest.name}")
            skipped.append(pkg)
        else:
            dest.mkdir(parents=True, exist_ok=True)
            to_download.append(pkg)

    if not to_download:
        logger.info("Saare packages already downloaded hain!")
        return {"success": [], "skipped": skipped, "failed": []}

    # Volume mounts — har package ka alag folder
    volume_args = []
    for pkg in to_download:
        folder_name = f"{pkg['ip_address']}_{pkg['id']}"
        dest        = DOWNLOAD_DIR / folder_name
        volume_args += ["-v", f"{dest}:/repo/{folder_name}"]

    # Download commands for each package
    pkg_commands = ""
    for pkg in to_download:
        folder_name = f"{pkg['ip_address']}_{pkg['id']}"
        pkg_commands += f"""
echo '------------------------------------------------------------'
echo '[DOWNLOAD] ID={pkg['id']} | {pkg['package_name']}-{pkg['version']}'
echo '          Agent : {pkg['agent_id']}'
echo '          Folder: {folder_name}'
dnf download \\
  --destdir=/repo/{folder_name} \\
  --repo='{pkg['repo']}' \\
  --resolve \\
  '{pkg['package_name']}-{pkg['version']}'
if [ $? -eq 0 ]; then
  echo "✅ SUCCESS: {pkg['id']}|{pkg['package_name']}"
else
  echo "❌ FAILED:  {pkg['id']}|{pkg['package_name']}"
fi
"""

    container_script = f"""
# Clean old registration
subscription-manager unregister 2>/dev/null || true
subscription-manager clean    2>/dev/null || true

# Register
echo '[INFO] Registering subscription...'
subscription-manager register \\
  --username='{RH_USERNAME}' \\
  --password='{RH_PASSWORD}'

if [ $? -ne 0 ]; then
  echo '[ERROR] Registration failed!'
  exit 1
fi

# Refresh + Enable repos
subscription-manager refresh
subscription-manager repos \\
  --enable=rhel-10-for-x86_64-baseos-rpms \\
  --enable=rhel-10-for-x86_64-appstream-rpms

if [ $? -ne 0 ]; then
  echo '[ERROR] Repos enable nahi hue!'
  subscription-manager unregister 2>/dev/null || true
  exit 1
fi

# Install yum-utils
dnf install -y yum-utils 2>/dev/null

# Download all packages
{pkg_commands}

# Unregister
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

    logger.info(f"\nPodman container start ho raha hai — {len(to_download)} packages...")
    subprocess.run(cmd, text=True)

    # Verify karo kaunse RPMs actually save hue
    success = []
    failed  = []
    for pkg in to_download:
        dest = DOWNLOAD_DIR / f"{pkg['ip_address']}_{pkg['id']}"
        if list(dest.glob("*.rpm")):
            success.append(pkg)
        else:
            failed.append(pkg)

    return {"success": success, "skipped": skipped, "failed": failed}


def main():
    parser = argparse.ArgumentParser(
        description="RHEL 10 Patch Downloader — Single / Multiple IDs + Agents",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--ids", required=True, nargs="+",
        help="Patch ID(s):\n  Single : --ids 963\n  Multiple: --ids 963 964 965"
    )
    parser.add_argument(
        "--agent-ids", required=True, nargs="+",
        help=(
            "Agent ID(s):\n"
            "  1 agent for all : --agent-ids AAA\n"
            "  Per ID mapping  : --agent-ids AAA BBB  (must match --ids count)"
        )
    )
    args = parser.parse_args()

    logger = setup_logger()

    logger.info("=" * 60)
    logger.info("  RHEL 10 Patch Downloader")
    logger.info(f"  IDs       : {', '.join(args.ids)}")
    logger.info(f"  Agent IDs : {', '.join(args.agent_ids)}")
    logger.info(f"  Total     : {len(args.ids)} package(s)")
    logger.info("=" * 60)

    # Step 1: ID ↔ Agent pair banao
    pairs = build_id_agent_pairs(args.ids, args.agent_ids, logger)

    # Step 2: DB se fetch karo
    rows = fetch_packages(pairs, logger)
    if not rows:
        logger.error("Koi bhi package DB mein nahi mila. Exit.")
        sys.exit(1)

    # Step 3: Table print karo
    logger.info(f"\n{'ID':<8} {'IP':<16} {'Package':<30} {'Version':<25} {'Agent'}")
    logger.info("-" * 100)
    for r in rows:
        logger.info(f"{r['id']:<8} {r['ip_address']:<16} {r['package_name']:<30} {r['version']:<25} {r['agent_id']}")
    logger.info("")

    # Step 4: Download
    result = download_via_podman(rows, logger)

    # Step 5: Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("  DOWNLOAD SUMMARY")
    logger.info(f"  ✅ Success : {len(result['success'])}")
    logger.info(f"  ⚠️  Skipped : {len(result['skipped'])}  (already downloaded)")
    logger.info(f"  ❌ Failed  : {len(result['failed'])}")
    logger.info("=" * 60)

    if result["failed"]:
        logger.error("\nFailed packages:")
        for pkg in result["failed"]:
            logger.error(f"  ❌ ID={pkg['id']} | {pkg['package_name']}-{pkg['version']} | Agent={pkg['agent_id']}")

    if result["success"]:
        logger.info("\nSaved locations:")
        for pkg in result["success"]:
            folder = DOWNLOAD_DIR / f"{pkg['ip_address']}_{pkg['id']}"
            logger.info(f"  ✅ {folder}")

    sys.exit(0 if not result["failed"] else 1)


if __name__ == "__main__":
    main()
