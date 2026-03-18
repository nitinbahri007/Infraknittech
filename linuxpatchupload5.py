import requests
import gzip
import os
import re
import json
from db import get_db_connection

UPLOAD_DIR = "uploads"
CACHE_FILE = "repo_cache.json"

# ===============================
# GLOBAL CACHE
# ===============================
latest = {}

# ===============================
# INSERT QUERY
# ===============================
INSERT_QUERY = """
INSERT INTO linux_patches
(agent_id, ip_address, package_name, installed_version, latest_version, patch_type)
VALUES (%s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
installed_version = VALUES(installed_version),
latest_version = VALUES(latest_version),
patch_type = VALUES(patch_type),
scan_time = CURRENT_TIMESTAMP
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
# VERSION FUNCTIONS
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
    percent = int((current / total) * 100)
    bar = "█" * (percent // 5) + "-" * (20 - percent // 5)
    print(f"\r{prefix} |{bar}| {percent}%", end="")


# ===============================
# LOAD UBUNTU REPO (WITH CACHE)
# ===============================
def load_repo_data():
    global latest

    # 🔥 Load cache
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
        "http://security.ubuntu.com/ubuntu/dists/jammy-security/universe/binary-amd64/Packages.gz"
    ]

    total_repos = len(REPOS)

    for i, url in enumerate(REPOS, 1):
        print(f"\n🌐 Repo {i}/{total_repos}")

        try:
            response = requests.get(url, timeout=60)

            if response.status_code != 200:
                print("❌ Failed:", url)
                continue

            print("⬇️ Downloaded")

            data = gzip.decompress(response.content).decode(errors="ignore")
            print("📦 Extracted")

            pkg = None
            for line in data.split("\n"):
                if line.startswith("Package:"):
                    pkg = line.split(":",1)[1].strip()

                elif line.startswith("Version:") and pkg:
                    latest[pkg] = line.split(":",1)[1].strip()

                elif line.strip() == "":
                    pkg = None

            print("✅ Parsed")

        except Exception as e:
            print("❌ Repo error:", url, e)

    print(f"\n✅ Repo loaded: {len(latest)} packages")

    # Save cache
    with open(CACHE_FILE, "w") as f:
        json.dump(latest, f)

    print("💾 Cache saved")


# ===============================
# FILTERS
# ===============================
EXTERNAL_KEYWORDS = ["mongo", "mysql", "ntop", "nprobe", "ndpi", "pfring", "python"]

META_PACKAGES = {
    "default-jre-headless",
    "default-jre",
    "default-jdk",
    "default-jdk-headless"
}

PACKAGE_ALIASES = {
    "imagemagick-6.q16": "imagemagick",
    "imagemagick-7": "imagemagick"
}


# ===============================
# 🔥 MAIN FUNCTION
# ===============================
def process_uploaded_packages():

    print("\n🚀 START PROCESSING\n")

    load_repo_data()

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        files = [f for f in os.listdir(UPLOAD_DIR) if f.endswith(".txt")]

        total_files = len(files)

        if total_files == 0:
            print("⚠️ No files found")
            return

        processed_files = 0

        for filename in files:

            processed_files += 1
            progress_bar(processed_files, total_files, "📂 Files")

            agent_id = filename.replace("_packages.txt", "")
            ip_address = get_ip_from_agent(cursor, agent_id)

            filepath = os.path.join(UPLOAD_DIR, filename)

            print(f"\n\n📦 Scanning: {filename} | IP: {ip_address}")

            installed = {}

            with open(filepath) as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) == 2:
                        installed[parts[0]] = parts[1]

            total_packages = len(installed)
            processed_packages = 0

            for pkg, inst_ver in installed.items():

                processed_packages += 1
                progress_bar(processed_packages, total_packages, "   📦 Packages")

                pkg_lookup = PACKAGE_ALIASES.get(pkg, pkg)

                if pkg_lookup in latest:

                    if pkg_lookup in META_PACKAGES:
                        patch_type = "meta_package"
                        latest_ver = latest[pkg_lookup]

                    else:
                        if not debian_compare(inst_ver, latest[pkg_lookup]):
                            continue

                        patch_type = "outdated"
                        latest_ver = latest[pkg_lookup]

                else:
                    if any(k in pkg.lower() for k in EXTERNAL_KEYWORDS):
                        patch_type = "external_repo"
                        latest_ver = "external_repo"
                    else:
                        continue

                try:
                    cursor.execute(
                        INSERT_QUERY,
                        (
                            agent_id,
                            ip_address,
                            pkg,
                            inst_ver,
                            latest_ver,
                            patch_type
                        )
                    )
                except Exception as e:
                    print("\n❌ Insert error:", e)

            print("\n✅ File Done")

        conn.commit()
        print("\n🎯 ALL DONE → DB updated")

    except Exception as e:
        print("\n❌ Processing error:", e)

    finally:
        cursor.close()
        conn.close()


# ===============================
# 🔥 DIRECT RUN SUPPORT
# ===============================
if __name__ == "__main__":
    process_uploaded_packages()
