import requests
import gzip
import os
import json
import re

UPLOAD_DIR = "uploads"

# ===============================
# PURE PYTHON VERSION COMPARE
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
# LOAD UBUNTU REPOS
# ===============================
REPOS = [
    "http://archive.ubuntu.com/ubuntu/dists/jammy/main/binary-amd64/Packages.gz",
    "http://archive.ubuntu.com/ubuntu/dists/jammy-updates/main/binary-amd64/Packages.gz",
    "http://security.ubuntu.com/ubuntu/dists/jammy-security/main/binary-amd64/Packages.gz"
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

    missing = []

    for pkg, inst_ver in installed.items():
        if pkg in latest:
            try:
                if debian_compare(inst_ver, latest[pkg]):
                    missing.append({
                        "package": pkg,
                        "installed": inst_ver,
                        "latest": latest[pkg]
                    })
            except:
                pass

    # ✅ FULL missing list (NO slicing)
    results[agent_id] = {
        "total_installed": len(installed),
        "missing_count": len(missing),
        "missing_preview": missing   # FULL LIST
    }

    print(f"Missing patches: {len(missing)}")

# ===============================
# SAVE REPORT
# ===============================
with open("patch_report.json", "w") as f:
    json.dump(results, f, indent=2)

print("\n✅ Report saved: patch_report.json")