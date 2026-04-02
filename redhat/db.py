import mysql.connector
from datetime import datetime


# 🔌 Database Connection
def get_db_connection():
    return mysql.connector.connect(
        host="10.10.10.91",
        user="root",
        password="xxxx",
        database="infra_monitor",
        connection_timeout=5
    )


# 📋 Get all expected agents from devices table
def get_all_devices():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT agent_id FROM devices")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [r[0] for r in rows]


# 🟢🔴 Update device ONLINE/OFFLINE status
def update_device_status(agent_id, status):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE devices
        SET status=%s, updated_at=NOW()
        WHERE agent_id=%s
    """, (status, agent_id))
    conn.commit()
    cursor.close()
    conn.close()


# ⬇️ Start outage when agent goes offline
def start_outage(hostname):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Insert only if no open outage exists
        cursor.execute("""
            SELECT id FROM agent_outages
            WHERE hostname=%s AND down_end IS NULL
            LIMIT 1
        """, (hostname,))
        existing = cursor.fetchone()

        if not existing:
            cursor.execute(
                "INSERT INTO agent_outages (hostname, down_start) VALUES (%s, %s)",
                (hostname, datetime.now())
            )
            conn.commit()

        cursor.close()
        conn.close()
    except Exception as e:
        print("DB Error (start_outage):", e)


# ⬆️ End outage when agent comes back online
def end_outage(hostname):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, down_start FROM agent_outages
            WHERE hostname=%s AND down_end IS NULL
            ORDER BY down_start DESC LIMIT 1
        """, (hostname,))
        row = cursor.fetchone()

        if row:
            outage_id, start_time = row
            end_time = datetime.now()
            duration = int((end_time - start_time).total_seconds())

            cursor.execute("""
                UPDATE agent_outages
                SET down_end=%s, duration_seconds=%s
                WHERE id=%s
            """, (end_time, duration, outage_id))
            conn.commit()

        cursor.close()
        conn.close()
    except Exception as e:
        print("DB Error (end_outage):", e)

# ================= FETCH PATCHES =================
def get_patches_by_ip():
    """
    Fetch IP + patch_title mapped via agent_id
    Used by downloader
    """
    try:
        conn = get_db_connection()
        if not conn:
            return []

        cursor = conn.cursor(dictionary=True)

        query = """
            SELECT 
                d.ip_address,
                pm.patch_title
            FROM patch_missing pm
            JOIN devices d ON pm.agent_id = d.agent_id
            WHERE pm.patch_title IS NOT NULL
            ORDER BY d.ip_address
        """

        cursor.execute(query)
        rows = cursor.fetchall()

        cursor.close()
        conn.close()
        return rows

    except Exception as e:
        print("❌ Fetch patches error:", e)
        return []




def update_patch_progress(agent_id, title, kb, progress, status):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO patch_download_progress (agent_id, title, kb, progress, status)
        VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            progress = VALUES(progress),
            status = VALUES(status),
            updated_at = NOW()
    """, (agent_id, title, kb, progress, status))

    conn.commit()
    cur.close()
    conn.close()


# ================= INSTALL TABLE =================
def update_patch_install_progress(agent_id, kb, progress, status):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO patch_install_progress (agent_id, kb, progress, status)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            progress = VALUES(progress),
            status = VALUES(status),
            updated_at = NOW()
    """, (agent_id, kb, progress, status))

    conn.commit()
    cur.close()
    conn.close()


# ================= FETCH PROGRESS (OPTIONAL API) =================
def get_patch_progress(agent_id):
    """
    For Flask dashboard API
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT patch_title, kb, progress, status, updated_at
            FROM patch_install_progress
            WHERE agent_id = %s
            ORDER BY updated_at DESC
        """, (agent_id,))

        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows

    except Exception as e:
        print("❌ Fetch progress error:", e)
        return []

def get_patch_progress_by_kb(agent_id, kb):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT agent_id, kb, progress, status, updated_at
            FROM patch_install_progress
            WHERE agent_id = %s AND kb = %s
        """, (agent_id, kb))

        row = cursor.fetchone()

        cursor.close()
        conn.close()
        return row

    except Exception as e:
        print("DB error:", e)
        return None

def get_all_progress_by_agent(agent_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT agent_id, kb, progress, status, updated_at
            FROM patch_install_progress
            WHERE agent_id = %s
            ORDER BY updated_at DESC
        """, (agent_id,))

        rows = cursor.fetchall()

        cursor.close()
        conn.close()
        return rows

    except Exception as e:
        print("Agent progress error:", e)
        return []

