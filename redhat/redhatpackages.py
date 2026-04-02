import os
import json
import mysql.connector
from datetime import datetime

# ===============================
# LOAD CONFIG
# ===============================
try:
    with open("config.json", "r") as f:
        config = json.load(f)
except Exception as e:
    print("❌ Failed to load config.json:", e)
    exit()

DB_HOST = config.get("DB_HOST", "localhost")
DB_USER = config.get("DB_USER")
DB_PASS = config.get("DB_PASS")
DB_NAME = config.get("DB_NAME")

PATCHES_DIR = config.get("REDHAT_PATCHES_DIR", "redhat_patches")

# ===============================
# DB CONNECTION
# ===============================
def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME
    )

# ===============================
# PARSE packages.txt
# Format: "package_name version-release.el10"
# ===============================
def parse_packages_file(filepath):
    packages = []
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(" ", 1)
            if len(parts) == 2:
                name    = parts[0].strip()
                version = parts[1].strip()

                # repo — version se el10/el9 nikalo
                repo = "unknown"
                if ".el10" in version:
                    repo = "rhel-10"
                elif ".el9" in version:
                    repo = "rhel-9"
                elif ".el8" in version:
                    repo = "rhel-8"

                packages.append({
                    "package_name": name,
                    "version"     : version,
                    "repo"        : repo
                })
    return packages

# ===============================
# INSERT INTO redhat_patch_list
# ===============================
def insert_packages(agent_id, ip_address, packages):
    conn   = get_db_connection()
    cursor = conn.cursor()

    inserted = 0
    skipped  = 0

    for pkg in packages:
        try:
            # Duplicate check — same agent_id + package_name
            cursor.execute("""
                SELECT id FROM redhat_patch_list
                WHERE agent_id=%s AND package_name=%s
            """, (agent_id, pkg["package_name"]))

            existing = cursor.fetchone()

            if existing:
                # Version update karo agar change hua
                cursor.execute("""
                    UPDATE redhat_patch_list
                    SET version=%s, repo=%s, ip_address=%s, created_at=NOW()
                    WHERE agent_id=%s AND package_name=%s
                """, (
                    pkg["version"],
                    pkg["repo"],
                    ip_address,
                    agent_id,
                    pkg["package_name"]
                ))
                skipped += 1
            else:
                cursor.execute("""
                    INSERT INTO redhat_patch_list
                    (agent_id, ip_address, package_name, version, repo, created_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                """, (
                    agent_id,
                    ip_address,
                    pkg["package_name"],
                    pkg["version"],
                    pkg["repo"]
                ))
                inserted += 1

        except Exception as e:
            print(f"❌ Insert error [{pkg['package_name']}]: {e}")

    conn.commit()
    cursor.close()
    conn.close()

    return inserted, skipped

# ===============================
# PROCESS ALL FILES IN redhat_patches/
# Filename format: <agent_id>_packages.txt
# ===============================
def process_all_agents():
    if not os.path.exists(PATCHES_DIR):
        print(f"❌ Folder not found: {PATCHES_DIR}")
        return

    files = [f for f in os.listdir(PATCHES_DIR) if f.endswith("_packages.txt")]

    if not files:
        print("⚠️ No package files found")
        return

    print(f"📂 Found {len(files)} file(s) in {PATCHES_DIR}/")
    print("=" * 50)

    for filename in files:
        # agent_id nikalo filename se
        agent_id   = filename.replace("_packages.txt", "")
        filepath   = os.path.join(PATCHES_DIR, filename)

        print(f"\n➡️  Processing: {filename}")
        print(f"   Agent ID : {agent_id}")

        # ip_address — devices table se nikalo
        ip_address = get_agent_ip(agent_id)
        print(f"   IP       : {ip_address}")

        try:
            packages = parse_packages_file(filepath)
            print(f"   Packages : {len(packages)} found")

            inserted, updated = insert_packages(agent_id, ip_address, packages)
            print(f"   ✅ Inserted: {inserted} | Updated: {updated}")

        except Exception as e:
            print(f"   ❌ Error: {e}")

    print("\n" + "=" * 50)
    print("✅ All agents processed!")

# ===============================
# GET IP FROM devices TABLE
# ===============================
def get_agent_ip(agent_id):
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT ip_address FROM devices WHERE agent_id=%s LIMIT 1",
            (agent_id,)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row[0] if row else "unknown"
    except:
        return "unknown"


# ===============================
# MAIN
# ===============================
if __name__ == "__main__":
    print("🚀 RedHat Package List — DB Import")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    process_all_agents()
