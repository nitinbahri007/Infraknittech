import os
import re
from datetime import datetime

# db.py se connection import karo
from db import get_db_connection

PATCHES_DIR   = "redhat_patches"
REPO_BASE_DIR = "/root/rhel10-repo"

REPO_DIRS = [
    os.path.join(REPO_BASE_DIR, "rhel-10-for-x86_64-baseos-rpms"),
    os.path.join(REPO_BASE_DIR, "rhel-10-for-x86_64-appstream-rpms"),
]

# ===============================
# GET AGENT IP FROM devices TABLE
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
    except Exception as e:
        print(f"❌ IP fetch error: {e}")
        return "unknown"

# ===============================
# PARSE packages.txt (installed)
# Format: "libgcc 14.2.1-7.el10"
# ===============================
def parse_installed_packages(filepath):
    installed = {}
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(" ", 1)
            if len(parts) == 2:
                name    = parts[0].strip()
                version = parts[1].strip()
                installed[name] = version
    return installed

# ===============================
# PARSE REPO RPM FILES
# Format: name-version-release.arch.rpm
# ===============================
def parse_repo_packages(repo_dirs):
    repo        = {}
    rpm_pattern = re.compile(
        r'^(.+)-([^-]+)-([^-]+)\.(x86_64|noarch|i686)\.rpm$'
    )

    for repo_dir in repo_dirs:
        if not os.path.exists(repo_dir):
            print(f"⚠️  Repo dir not found: {repo_dir}")
            continue

        repo_name = os.path.basename(repo_dir)
        print(f"📂 Scanning: {repo_name}")

        for root, dirs, files in os.walk(repo_dir):
            for filename in files:
                if not filename.endswith(".rpm"):
                    continue
                m = rpm_pattern.match(filename)
                if not m:
                    continue

                name     = m.group(1)
                version  = m.group(2)
                release  = m.group(3)
                full_ver = f"{version}-{release}"

                if name not in repo:
                    repo[name] = {
                        "version": full_ver,
                        "repo"   : repo_name,
                        "rpm"    : filename
                    }
                else:
                    if full_ver > repo[name]["version"]:
                        repo[name] = {
                            "version": full_ver,
                            "repo"   : repo_name,
                            "rpm"    : filename
                        }

    print(f"✅ Total repo packages: {len(repo)}")
    return repo

# ===============================
# COMPARE installed vs repo
# ===============================
def compare_packages(installed, repo):
    outdated = []

    for pkg_name, installed_ver in installed.items():
        if pkg_name in repo:
            repo_ver = repo[pkg_name]["version"]
            if repo_ver != installed_ver:
                outdated.append({
                    "package_name"     : pkg_name,
                    "installed_version": installed_ver,
                    "repo_version"     : repo_ver,
                    "repo"             : repo[pkg_name]["repo"],
                })

    print(f"📊 Outdated packages: {len(outdated)}")
    return outdated

# ===============================
# INSERT INTO redhat_patch_list
# ===============================
def insert_patch_list(agent_id, ip_address, packages):
    conn   = get_db_connection()
    cursor = conn.cursor()

    inserted = 0
    updated  = 0

    for pkg in packages:
        try:
            cursor.execute("""
                SELECT id FROM redhat_patch_list
                WHERE agent_id=%s AND package_name=%s
            """, (agent_id, pkg["package_name"]))

            existing = cursor.fetchone()

            if existing:
                cursor.execute("""
                    UPDATE redhat_patch_list
                    SET version=%s, repo=%s, ip_address=%s, created_at=NOW()
                    WHERE agent_id=%s AND package_name=%s
                """, (
                    pkg["repo_version"],
                    pkg["repo"],
                    ip_address,
                    agent_id,
                    pkg["package_name"]
                ))
                updated += 1
            else:
                cursor.execute("""
                    INSERT INTO redhat_patch_list
                    (agent_id, ip_address, package_name, version, repo, created_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                """, (
                    agent_id,
                    ip_address,
                    pkg["package_name"],
                    pkg["repo_version"],
                    pkg["repo"]
                ))
                inserted += 1

        except Exception as e:
            print(f"❌ DB error [{pkg['package_name']}]: {e}")

    conn.commit()
    cursor.close()
    conn.close()

    return inserted, updated

# ===============================
# PROCESS ALL AGENTS
# ===============================
def process_all_agents():
    if not os.path.exists(PATCHES_DIR):
        print(f"❌ Patches dir not found: {PATCHES_DIR}")
        return

    files = [f for f in os.listdir(PATCHES_DIR) if f.endswith("_packages.txt")]

    if not files:
        print("⚠️  No package files found in redhat_patches/")
        return

    print(f"\n📂 Found {len(files)} agent file(s)")
    print("=" * 55)

    # Repo ek baar scan karo — sab agents ke liye same
    print("\n🔍 Scanning RHEL repo...")
    repo_packages = parse_repo_packages(REPO_DIRS)

    for filename in files:
        agent_id   = filename.replace("_packages.txt", "")
        filepath   = os.path.join(PATCHES_DIR, filename)
        ip_address = get_agent_ip(agent_id)

        print(f"\n➡️  Agent    : {agent_id}")
        print(f"   IP       : {ip_address}")

        installed = parse_installed_packages(filepath)
        print(f"   Installed: {len(installed)} packages")

        outdated = compare_packages(installed, repo_packages)

        if outdated:
            inserted, updated = insert_patch_list(agent_id, ip_address, outdated)
            print(f"   ✅ DB → Inserted: {inserted} | Updated: {updated}")
        else:
            print(f"   ✅ All packages up to date!")

    print("\n" + "=" * 55)
    print("✅ All agents processed!")


# ===============================
# MAIN
# ===============================
if __name__ == "__main__":
    print("🚀 RedHat Patch Comparison Script")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    process_all_agents()
