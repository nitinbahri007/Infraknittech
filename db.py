import mysql.connector


def get_db_connection():
    """
    Create and return a new database connection.
    Auto reconnect enabled for stability.
    """
    return mysql.connector.connect(
        host="10.10.10.91",
        user="root",
        password="USn7ets2020#",
        database="infra_monitor",
        autocommit=False,
        connection_timeout=5
    )

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