import requests
import gzip
import os
import re
from db import get_db_connection

UPLOAD_DIR = "uploads"

# ===============================
# DB CONNECTION
# ===============================
conn = get_db_connection()
cursor = conn.cursor()

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

# Optional mapping
AGENT_IP_MAP = {
    "c959c3c5-3ce6-4e0c-9b85-a6eac88ed6ef": "10.10.10.91"
}

# ===============================
# SAFE VERSION NORMALIZER
# ===============================
def normalize_version(v):
    if ":" in v:
        v = v.split(":", 1)[1]
    v = re.split(r"[-~]", v)[0]
    return v

# Windows-safe version compare
def debian_compare(v1, v2):
    n1 = normalize_version(v1)
    n2 = normalize_version(v2)

    def normalize(v):
        parts = re.split(r"[._]", v)
        safe_parts = []
        for p in parts:
            if p.isdigit():
                safe_parts.append(int(p))
            else:
                safe_parts.append(p)
        return safe_parts

    try:
        return normalize(n1) < normalize(n2)
    except:
        return False

# ===============================
# UBUNTU REPOS
# ===============================
REPOS = [
    "http://archive.ubuntu.com/ubuntu/dists/jammy/main/binary-amd64/Packages.gz",
    "http://archive.ubuntu.com/ubuntu/dists/jammy-updates/main/binary-amd64/Packages.gz",
    "http://security.ubuntu.com/ubuntu/dists/jammy-security/main/binary-amd64/Packages.gz",
    "http://archive.ubuntu.com/ubuntu/dists/jammy/universe/binary-amd64/Packages.gz",
    "http://archive.ubuntu.com/ubuntu/dists/jammy-updates/universe/binary-amd64/Packages.gz",
    "http://security.ubuntu.com/ubuntu/dists/jammy-security/universe/binary-amd64/Packages.gz"
]

print("Downloading Ubuntu metadata...")
latest = {}

for url in REPOS:
    data = gzip.decompress(requests.get(url).content).decode(errors="ignore")
    pkg = None
    for line in data.split("\n"):
        if line.startswith("Package:"):
            pkg = line.split(":")[1].strip()
        elif line.startswith("Version:") and pkg:
            latest[pkg] = line.split(":")[1].strip()

print("Repo packages loaded:", len(latest))

# ===============================
# FILTERS
# ===============================
EXTERNAL_KEYWORDS = ["mongo", "ntop", "nprobe", "ndpi", "pfring"]

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
# PROCESS FILES
# ===============================
for filename in os.listdir(UPLOAD_DIR):
    if not filename.endswith(".txt"):
        continue

    agent_id = filename.replace("_packages.txt", "")
    ip_address = AGENT_IP_MAP.get(agent_id, "unknown")
    filepath = os.path.join(UPLOAD_DIR, filename)

    print(f"\nScanning: {filename}")

    installed = {}
    with open(filepath) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 2:
                installed[parts[0]] = parts[1]

    for pkg, inst_ver in installed.items():
        pkg_lookup = PACKAGE_ALIASES.get(pkg, pkg)

        # Ubuntu repo match
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

        # INSERT DB
        cursor.execute(INSERT_QUERY, (
            agent_id,
            ip_address,
            pkg,
            inst_ver,
            latest_ver,
            patch_type
        ))

conn.commit()
cursor.close()
conn.close()

print("\n✅ DONE → Data saved in infra_monitor.linux_patches")