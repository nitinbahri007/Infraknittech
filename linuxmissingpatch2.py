import requests
import gzip
import os
import json
import re

UPLOAD_DIR = "uploads"

# ===============================
# VERSION NORMALIZER
# ===============================
def normalize_version(v):
    if ":" in v:
        v = v.split(":", 1)[1]
    v = re.split(r"[-~]", v)[0]
    return v

def debian_compare(v1, v2):
    n1 = normalize_version(v1)
    n2 = normalize_version(v2)

    def split(v):
        return [int(x) if x.isdigit() else x for x in re.split(r"[._]", v)]

    return split(n1) < split(n2)

# ===============================
# UBUNTU REPOS (MAIN + UNIVERSE)
# ===============================
REPOS = [
    # MAIN
    "http://archive.ubuntu.com/ubuntu/dists/jammy/main/binary-amd64/Packages.gz",
    "http://archive.ubuntu.com/ubuntu/dists/jammy-updates/main/binary-amd64/Packages.gz",
    "http://security.ubuntu.com/ubuntu/dists/jammy-security/main/binary-amd64/Packages.gz",

    # UNIVERSE
    "http://archive.ubuntu.com/ubuntu/dists/jammy/universe/binary-amd64/Packages.gz",
    "http://archive.ubuntu.com/ubuntu/dists/jammy-updates/universe/binary-amd64/Packages.gz",
    "http://security.ubuntu.com/ubuntu/dists/jammy-security/universe/binary-amd64/Packages.gz"
]

latest = {}

print("Downloading Ubuntu metadata...")

for url in REPOS:
    print("Fetching:", url)
    data = gzip.decompress(requests.get(url).content).decode(errors="ignore")

    pkg = None
    for line in data.split("\n"):
        if line.startswith("Package:"):
            pkg = line.split(":")[1].strip()
        elif line.startswith("Version:") and pkg:
            latest[pkg] = line.split(":")[1].strip()

print("Total repo packages:", len(latest))

# ===============================
# External filters
# ===============================
EXTERNAL_KEYWORDS = ["mongo", "ntop", "nprobe", "ndpi", "pfring"]

# ===============================
# META PACKAGES (Java)
# ===============================
META_PACKAGES = {
    "default-jre-headless",
    "default-jre",
    "default-jdk",
    "default-jdk-headless"
}

# ===============================
# PACKAGE ALIASES (ImageMagick fix)
# ===============================
PACKAGE_ALIASES = {
    "imagemagick-6.q16": "imagemagick",
    "imagemagick-7": "imagemagick"
}

# ===============================
# PROCESS uploads/
# ===============================
results = {}

for filename in os.listdir(UPLOAD_DIR):
    if not filename.endswith(".txt"):
        continue

    agent_id = filename.replace("_packages.txt", "")
    filepath = os.path.join(UPLOAD_DIR, filename)

    print(f"\n🔍 Scanning: {filename}")

    installed = {}

    with open(filepath) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 2:
                installed[parts[0]] = parts[1]

    outdated = []
    external = []

    for pkg, inst_ver in installed.items():

        # Normalize aliases (ImageMagick support)
        pkg_lookup = PACKAGE_ALIASES.get(pkg, pkg)

        # ===============================
        # UBUNTU REPO MATCH
        # ===============================
        if pkg_lookup in latest:

            # Java meta packages
            if pkg_lookup in META_PACKAGES:
                outdated.append({
                    "package": pkg,
                    "installed": inst_ver,
                    "latest": latest[pkg_lookup],
                    "type": "meta_package"
                })
                continue

            try:
                if debian_compare(inst_ver, latest[pkg_lookup]):
                    outdated.append({
                        "package": pkg,
                        "installed": inst_ver,
                        "latest": latest[pkg_lookup],
                        "type": "outdated"
                    })
            except:
                pass

        # ===============================
        # EXTERNAL PACKAGES
        # ===============================
        else:
            if any(k in pkg.lower() for k in EXTERNAL_KEYWORDS):
                external.append({
                    "package": pkg,
                    "installed": inst_ver,
                    "latest": "external_repo",
                    "type": "external_repo"
                })

    all_missing = outdated + external

    results[agent_id] = {
        "total_installed": len(installed),
        "missing_count": len(all_missing),
        "outdated_ubuntu": len(outdated),
        "external_packages": len(external),
        "missing_preview": all_missing
    }

    print(f"Outdated Ubuntu: {len(outdated)}")
    print(f"External Repo (Mongo/ntop): {len(external)}")
    print(f"Total Missing: {len(all_missing)}")

# ===============================
# SAVE REPORT
# ===============================
with open("patch_report.json", "w") as f:
    json.dump(results, f, indent=2)

print("\n✅ Report saved: patch_report.json")