#!/usr/bin/env python3

"""
redhat_deploy_worker.py
Agent ko patch files serve karta hai aur install status track karta hai.
"""

import logging
from datetime import datetime
from pathlib import Path

from db import get_db_connection

DOWNLOAD_DIR = Path("/root/rhel10-repo/patches")

logger = logging.getLogger(__name__)


def get_pending_deploys(agent_id: str) -> list:
    """Agent ke pending deploys fetch karo."""
    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT *
            FROM redhat_deploy_queue
            WHERE agent_id = %s
              AND status = 'pending'
              AND (scheduled_at IS NULL OR scheduled_at <= NOW())
            ORDER BY created_at ASC
            """,
            (agent_id,)
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"get_pending_deploys error: {e}")
        return []


def update_deploy_status(deploy_id: int, status: str, message: str = None):
    """Deploy status update karo."""
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE redhat_deploy_queue
            SET status     = %s,
                message    = %s,
                deployed_at = CASE WHEN %s IN ('installed','failed') THEN NOW() ELSE deployed_at END,
                updated_at  = NOW()
            WHERE id = %s
            """,
            (status, message, status, deploy_id)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"update_deploy_status error: {e}")


def queue_deploy(patch_id: int, agent_id: str, scheduled_at: str = None) -> bool:
    """
    Download complete hone ke baad deploy queue mein add karo.
    patch_id = redhat_patch_list.id
    scheduled_at = "2026-03-31 10:00:00" or None (immediate)
    """
    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Patch info fetch karo
        cursor.execute(
            """
            SELECT id, agent_id, ip_address, package_name, version
            FROM redhat_patch_list
            WHERE id = %s AND agent_id = %s
            LIMIT 1
            """,
            (patch_id, agent_id)
        )
        patch = cursor.fetchone()
        if not patch:
            logger.error(f"Patch {patch_id} not found for agent {agent_id}")
            cursor.close()
            conn.close()
            return False

        # Downloaded RPM files find karo
        dest      = DOWNLOAD_DIR / f"{patch['ip_address']}_{patch_id}"
        rpm_files = list(dest.glob("*.rpm")) if dest.exists() else []

        if not rpm_files:
            logger.error(f"No RPM files found for patch {patch_id} in {dest}")
            cursor.close()
            conn.close()
            return False

        files_str = "|".join(str(f) for f in rpm_files)

        # Already queued check karo
        cursor.execute(
            """
            SELECT id FROM redhat_deploy_queue
            WHERE patch_id = %s AND agent_id = %s
              AND status IN ('pending', 'sent', 'installing')
            LIMIT 1
            """,
            (patch_id, agent_id)
        )
        existing = cursor.fetchone()
        if existing:
            logger.warning(f"Patch {patch_id} already in deploy queue")
            cursor.close()
            conn.close()
            return True

        # Queue mein insert karo
        cursor.execute(
            """
            INSERT INTO redhat_deploy_queue
              (agent_id, patch_id, ip_address, package_name, version, files, status, scheduled_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s)
            """,
            (
                agent_id,
                patch_id,
                patch['ip_address'],
                patch['package_name'],
                patch['version'],
                files_str,
                scheduled_at
            )
        )
        conn.commit()
        cursor.close()
        conn.close()

        logger.info(f"✅ Queued deploy: patch={patch_id}, agent={agent_id}, files={len(rpm_files)}")
        return True

    except Exception as e:
        logger.error(f"queue_deploy error: {e}")
        return False


def get_deploy_status(agent_id: str = None, patch_id: int = None) -> list:
    """Deploy status fetch karo — agent ya patch ke liye."""
    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if patch_id:
            cursor.execute(
                """
                SELECT * FROM redhat_deploy_queue
                WHERE patch_id = %s AND agent_id = %s
                ORDER BY created_at DESC LIMIT 1
                """,
                (patch_id, agent_id)
            )
        else:
            cursor.execute(
                """
                SELECT * FROM redhat_deploy_queue
                WHERE agent_id = %s
                ORDER BY created_at DESC
                """,
                (agent_id,)
            )

        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"get_deploy_status error: {e}")
        return []
