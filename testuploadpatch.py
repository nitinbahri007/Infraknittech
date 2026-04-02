import requests
import gzip
import os
import re
import json
from db import get_db_connection

UPLOAD_DIR = "other_patches"
CACHE_FILE = "repo_cache.json"

# ===============================
# GLOBAL CACHE
# ===============================
latest = {}

# ===============================
# INSERT QUERY
# ===============================
INSERT_QUERY = """
INSERT INTO linux_patches_test
(agent_id, ip_address, package_name, installed_version, latest_version, patch_type)
VALUES (%s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
installed_version = VALUES(installed_version),
latest_version    = VALUES(latest_version),
patch_type        = VALUES(patch_type),
scan_time         = CURRENT_TIMESTAMP
"""

# ===============================
# GET IP
# ===============================
def get_ip_from_agent(cursor, agent_id):
    try:
        cursor.execute(
            "SELECT ip_address FROM devices WHERE agent_id=%s LIMIT 1",
            (agent_id,)
        )
        row = cursor.fetchone()
        return row[0] if row else "unknown"
    except Exception as e:
        print("DB error:", e)
        return "unknown"

# ===============================
# VERSION COMPARE
# ===============================
def normalize_version(v):
    if ":" in v:
        v = v.split(":", 1)[1]
    v = re.split(r"[-~]", v)[0]
    return v

def debian_compare(v1, v2):
    n1 = normalize_version(v1)
    n2 = normalize_version(v2)

    def normalize(v):
        parts = re.split(r"[._]", v)
        return [int(p) if p.isdigit() else p for p in parts]

    try:
        return normalize(n1) < normalize(n2)
    except:
        return False

# ===============================
# PROGRESS BAR
# ===============================
def progress_bar(current, total, prefix=""):
    if total == 0:
        return
    percent = int((current / total) * 100)
    bar = "█" * (percent // 5) + "-" * (20 - percent // 5)
    print(f"\r{prefix} |{bar}| {percent}%", end="")

# ===============================
# LOAD UBUNTU REPO (WITH CACHE)
# ===============================
def load_repo_data():
    global latest

    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            latest = json.load(f)
        print(f"⚡ Loaded repo from cache: {len(latest)} packages")
        return

    print("\n📥 Downloading Ubuntu metadata...\n")

    REPOS = [
        "http://archive.ubuntu.com/ubuntu/dists/jammy/main/binary-amd64/Packages.gz",
        "http://archive.ubuntu.com/ubuntu/dists/jammy-updates/main/binary-amd64/Packages.gz",
        "http://security.ubuntu.com/ubuntu/dists/jammy-security/main/binary-amd64/Packages.gz",
        "http://archive.ubuntu.com/ubuntu/dists/jammy/universe/binary-amd64/Packages.gz",
        "http://archive.ubuntu.com/ubuntu/dists/jammy-updates/universe/binary-amd64/Packages.gz",
        "http://security.ubuntu.com/ubuntu/dists/jammy-security/universe/binary-amd64/Packages.gz",
        "http://archive.ubuntu.com/ubuntu/dists/jammy/restricted/binary-amd64/Packages.gz",
        "http://archive.ubuntu.com/ubuntu/dists/jammy-updates/restricted/binary-amd64/Packages.gz",
        "http://security.ubuntu.com/ubuntu/dists/jammy-security/restricted/binary-amd64/Packages.gz",
        "http://archive.ubuntu.com/ubuntu/dists/jammy/multiverse/binary-amd64/Packages.gz",
        "http://archive.ubuntu.com/ubuntu/dists/jammy-updates/multiverse/binary-amd64/Packages.gz",
    ]

    for i, url in enumerate(REPOS, 1):
        print(f"\n🌐 Repo {i}/{len(REPOS)}: {url.split('dists/')[1]}")
        try:
            response = requests.get(url, timeout=60)
            if response.status_code != 200:
                print("❌ Failed:", url)
                continue

            data = gzip.decompress(response.content).decode(errors="ignore")
            pkg = None
            for line in data.split("\n"):
                if line.startswith("Package:"):
                    pkg = line.split(":", 1)[1].strip()
                elif line.startswith("Version:") and pkg:
                    latest[pkg] = line.split(":", 1)[1].strip()
                elif line.strip() == "":
                    pkg = None
            print("✅ Parsed")

        except Exception as e:
            print("❌ Repo error:", e)

    print(f"\n✅ Repo loaded: {len(latest)} packages")
    with open(CACHE_FILE, "w") as f:
        json.dump(latest, f)
    print("💾 Cache saved")

# ===============================
# FORMAT DETECT
# ===============================
def detect_format(filepath):
    """
    Format 1 — apt list --upgradable:
    apparmor/jammy-updates 3.0.4-2ubuntu2.5 amd64 [upgradable from: 3.0.4-2ubuntu2.4]

    Format 2 — dpkg installed list:
    adduser 3.118ubuntu5
    """
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or "Listing..." in line:
                continue
            if "upgradable from:" in line:
                return "apt"
            else:
                return "dpkg"
    return "dpkg"

# ===============================
# PARSE APT FORMAT
# ===============================
def parse_apt_format(filepath, agent_id, ip_address, cursor):
    count = 0
    with open(filepath) as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        if not line or "Listing..." in line:
            continue

        if "upgradable from:" not in line:
            continue

        try:
            pkg_name   = line.split("/")[0].strip()
            repo       = line.split("/")[1].split()[0].strip()
            latest_ver = line.split()[1].strip()
            inst_ver   = line.split("from:")[1].replace("]", "").strip()

            # Patch type
            if "security" in repo:
                patch_type = "security"
            elif repo == "stable":
                patch_type = "third_party"
            elif "updates" in repo:
                patch_type = "outdated"
            else:
                patch_type = "outdated"

            cursor.execute(INSERT_QUERY, (
                agent_id, ip_address,
                pkg_name, inst_ver, latest_ver, patch_type
            ))
            count += 1
            print(f"   ✅ {pkg_name}: {inst_ver} → {latest_ver} [{patch_type}]")

        except Exception as e:
            print(f"   ❌ Parse error: {line} → {e}")

    return count

# ===============================
# PARSE DPKG FORMAT
# ===============================
def parse_dpkg_format(filepath, agent_id, ip_address, cursor):
    count = 0

    installed = {}
    with open(filepath) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 2:
                installed[parts[0]] = parts[1]

    total = len(installed)
    processed = 0

    for pkg, inst_ver in installed.items():
        processed += 1
        progress_bar(processed, total, "   📦 Packages")

        # Repo mein check karo
        if pkg in latest:
            if not debian_compare(inst_ver, latest[pkg]):
                continue  # Already latest — skip

            latest_ver = latest[pkg]

            # Patch type
            if "security" in latest_ver.lower():
                patch_type = "security"
            else:
                patch_type = "outdated"

        else:
            # Repo mein nahi mila — third party / external
            patch_type = "third_party"
            latest_ver = "check_manually"

        try:
            cursor.execute(INSERT_QUERY, (
                agent_id, ip_address,
                pkg, inst_ver, latest_ver, patch_type
            ))
            count += 1
        except Exception as e:
            print(f"\n   ❌ Insert error: {pkg} → {e}")

    print()
    return count

# ===============================
# MAIN FUNCTION
# ===============================
def process_uploaded_packages():
    print("\n🚀 START PROCESSING\n")

    # Repo load — sirf dpkg format ke liye zaroorat hai
    # apt format ke liye repo ki zaroorat nahi
    repo_loaded = False

    conn   = get_db_connection()
    cursor = conn.cursor()

    try:
        files = [f for f in os.listdir(UPLOAD_DIR) if f.endswith(".txt")]

        if not files:
            print("⚠️ No files found in", UPLOAD_DIR)
            return

        print(f"📂 Found {len(files)} file(s)\n")

        for filename in files:
            agent_id   = filename.replace("_packages.txt", "")
            ip_address = get_ip_from_agent(cursor, agent_id)
            filepath   = os.path.join(UPLOAD_DIR, filename)

            print(f"{'='*50}")
            print(f"📦 File   : {filename}")
            print(f"   Agent  : {agent_id[:16]}...")
            print(f"   IP     : {ip_address}")

            # Format detect karo
            fmt = detect_format(filepath)
            print(f"   Format : {fmt.upper()}")

            if fmt == "apt":
                # apt list --upgradable format
                count = parse_apt_format(filepath, agent_id, ip_address, cursor)

            else:
                # dpkg installed list format — repo se compare karo
                if not repo_loaded:
                    load_repo_data()
                    repo_loaded = True
                count = parse_dpkg_format(filepath, agent_id, ip_address, cursor)

            print(f"\n   📊 Inserted: {count} patches")
            print()

        conn.commit()
        print("🎯 ALL DONE → DB updated\n")

    except Exception as e:
        print(f"\n❌ Processing error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        cursor.close()
        conn.close()

# ===============================
# DIRECT RUN
# ===============================
if __name__ == "__main__":
    process_uploaded_packages()
