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

# ===============================
# GET IP FROM DEVICES TABLE
# ===============================
def get_ip_from_agent(agent_id):

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
# SAFE VERSION NORMALIZER
# ===============================
def normalize_version(v):

    if ":" in v:
        v = v.split(":", 1)[1]

    v = re.split(r"[-~]", v)[0]

    return v


# ===============================
# VERSION COMPARISON
# ===============================
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

    try:

        response = requests.get(url, timeout=60)

        if response.status_code != 200:

            print("Repo download failed:", url)

            continue

        data = gzip.decompress(response.content).decode(errors="ignore")

        pkg = None

        for line in data.split("\n"):

            if line.startswith("Package:"):

                pkg = line.split(":",1)[1].strip()

            elif line.startswith("Version:") and pkg:

                version = line.split(":",1)[1].strip()

                latest[pkg] = version

            elif line.strip() == "":

                pkg = None

    except Exception as e:

        print("Repo download error:", url, e)


print("Repo packages loaded:", len(latest))


# ===============================
# FILTERS
# ===============================
#EXTERNAL_KEYWORDS = ["mongo", "ntop", "nprobe", "ndpi", "pfring"]
#EXTERNAL_KEYWORDS = ["mongo", "mysql", "ntop", "nprobe", "ndpi", "pfring", "python", "zypper", "xserver", "xmms2-plugin", "xubuntu", "xfonts", "xf", "xfs"]
#EXTERNAL_KEYWORDS = ["mongo", "mysql", "ntop", "nprobe", "ndpi", "pfring", "python", "py", "zypper", "xserver", "xmms2-plugin", "xubuntu", "xfonts", "xf", "xfs", "sp", "sq", "sql", "s", "ruby", "rt", "rsyslog", "r", "q"]
EXTERNAL_KEYWORDS = ["mongo", "mysql", "ntop", "nprobe", "ndpi", "pfring", "python", "py", "zypper", "xserver", "xmms2-plugin", "xubuntu", "xfonts", "xf", "xfs", "sp", "sq", "sql", "s", "ruby", "rt", "rsyslog", "r", "q", "a", "b", "c", "d","e","f","g","h","i","j","k","m","n","o","p","l","q","r","s","t","u","v","w","x","y","z", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]
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

    ip_address = get_ip_from_agent(agent_id)

    filepath = os.path.join(UPLOAD_DIR, filename)

    print("\nScanning:", filename)
    print("Agent ID:", agent_id)
    print("IP Address:", ip_address)

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


        # ===============================
        # INSERT DB
        # ===============================
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

            print("Insert error:", e)


# ===============================
# COMMIT
# ===============================
conn.commit()

cursor.close()

conn.close()

print("\n✅ DONE → Data saved in infra_monitor.linux_patches")
