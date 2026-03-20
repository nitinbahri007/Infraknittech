import os
import re
import sys
import time
import subprocess
from db import get_db_connection

# =========================
# INPUT
# =========================
if len(sys.argv) != 3:
    print("❌ Usage: python3 containersingle2.py <agent_id> <patch_id>")
    exit(1)

agent_id = sys.argv[1]
patch_id = sys.argv[2]

print(f"🎯 Agent ID : {agent_id}")
print(f"🎯 Patch ID : {patch_id}")

# =========================
# DB CONNECTION
# =========================
conn   = get_db_connection()
cursor = conn.cursor(dictionary=True)
print("✅ DB Connected")

# =========================
# FETCH DATA
# =========================
query = """
SELECT d.ip_address, d.os_version, p.package_name, p.patch_type
FROM devices d
JOIN linux_patches p ON d.agent_id = p.agent_id
WHERE d.agent_id = %s AND p.id = %s
"""
cursor.execute(query, (agent_id, patch_id))
row = cursor.fetchone()

if not row:
    print("❌ No data found for given agent_id and patch_id")
    cursor.close()
    conn.close()
    exit(1)

ip         = row["ip_address"]
os_version = row["os_version"]
package    = row["package_name"]
patch_type = row["patch_type"] or ""

# Normalize package name:
# DB may store 'apt-ntop' but actual package is 'ntopng'
package_map = {
    "apt-ntop": "ntopng",
}
actual_package = package_map.get(package.lower(), package)
if actual_package != package:
    print(f"\n⚠️  Package name mapped: '{package}' → '{actual_package}'")

print(f"\n📦 Package   : {actual_package}")
print(f"🔹 PatchType : {patch_type}")
print(f"🔹 IP        : {ip}")
print(f"🔹 OS        : {os_version}")

# =========================
# NORMALIZE VERSION
# =========================
def normalize(v):
    m = re.search(r'\d+\.\d+', v)
    return m.group() if m else "22.04"

version = normalize(os_version)

docker_map = {
    "20.04": "ubuntu:20.04",
    "22.04": "ubuntu:22.04",
    "24.04": "ubuntu:24.04",
}
image = docker_map.get(version, "ubuntu:22.04")
print(f"🐳 Docker    : {image}")

# =========================
# OUTPUT PATH
# IMPORTANT: Must be under $HOME — this server uses snap Docker
# which only allows bind-mounting paths under $HOME.
# /tmp, /opt, /var are all blocked by snap sandbox.
# =========================
home        = os.path.expanduser("~")
output_path = os.path.join(home, "patches", f"{ip}_{patch_id}")
os.makedirs(output_path, exist_ok=True)
print(f"📁 Folder    : {output_path}")

# =========================
# DETECT NTOP / EXTERNAL
# Note: ntopng is available in standard Ubuntu universe repo.
# No external ntop repo needed for ntopng.
# =========================
is_ntop     = "ntop" in actual_package.lower()
is_external = "external" in patch_type.lower() and not is_ntop

# =========================
# BUILD DOCKER COMMAND
# Key fixes:
#   1. -w /out sets working directory so apt-get download
#      saves files directly into the volume folder
#   2. universe repo enabled for ntopng
#   3. No ntop external repo needed for ntopng
# =========================
if is_external:
    # True external repo package (non-ntop)
    docker_cmd = f"""
docker run --rm \
  -v {output_path}:/out \
  -w /out \
  {image} bash -c '
set -e
export DEBIAN_FRONTEND=noninteractive

echo "--- Step 1: apt update ---"
apt-get update -qq
apt-get install -y software-properties-common 2>&1 | tail -3
add-apt-repository universe -y 2>/dev/null || true
apt-get update -qq

echo "--- Step 2: download {actual_package} ---"
cd /out
if apt-get download {actual_package} 2>&1; then
    echo "OK: {actual_package} downloaded"
else
    echo "WARN: {actual_package} not found"
    apt-cache search {actual_package.split("-")[0]} | head -10
fi

echo "--- Step 3: download dependencies ---"
for dep in $(apt-cache depends {actual_package} 2>/dev/null \
    | grep "  Depends:" \
    | awk "{{print \$2}}" \
    | tr -d "<>"); do
    apt-get download "$dep" 2>/dev/null \
        && echo "OK dep: $dep" \
        || echo "SKIP dep: $dep"
done

echo "--- Output files ---"
ls -lh /out/*.deb 2>/dev/null || echo "No .deb files"
'
"""

else:
    # Standard Ubuntu / ntopng — universe repo is enough
    docker_cmd = f"""
docker run --rm \
  -v {output_path}:/out \
  -w /out \
  {image} bash -c '
set -e
export DEBIAN_FRONTEND=noninteractive

echo "--- Step 1: apt update + enable universe ---"
apt-get update -qq
apt-get install -y software-properties-common 2>&1 | tail -3
add-apt-repository universe -y 2>/dev/null || true
apt-get update -qq

echo "--- Step 2: download {actual_package} ---"
cd /out
if apt-get download {actual_package} 2>&1; then
    echo "OK: {actual_package} downloaded"
else
    echo "WARN: {actual_package} not found"
    apt-cache search {actual_package.split("-")[0]} | head -10
fi

echo "--- Step 3: download dependencies ---"
for dep in $(apt-cache depends {actual_package} 2>/dev/null \
    | grep "  Depends:" \
    | awk "{{print \$2}}" \
    | tr -d "<>"); do
    apt-get download "$dep" 2>/dev/null \
        && echo "OK dep: $dep" \
        || echo "SKIP dep: $dep"
done

echo "--- Output files ---"
ls -lh /out/*.deb 2>/dev/null || echo "No .deb files"
'
"""

# =========================
# RUN DOCKER
# =========================
print(f"\n⬇️  Running Docker ...")
print("─" * 50)
result = subprocess.run(docker_cmd, shell=True)
print("─" * 50)

if result.returncode != 0:
    print(f"⚠️  Docker exited with code {result.returncode}")

# =========================
# VERIFY OUTPUT FILES
# =========================
time.sleep(1)
all_files   = [f for f in os.listdir(output_path) if f.endswith(".deb")]
patch_files = [f for f in all_files]

print("\n📊 RESULT:")
if patch_files:
    print(f"✅ SUCCESS → {len(patch_files)} .deb file(s) downloaded\n")
    for f in patch_files:
        size = os.path.getsize(os.path.join(output_path, f))
        print(f"   📦 {f}  ({size:,} bytes)")
else:
    print("❌ FAILED → No .deb files found")
    print(f"\n   💡 Manual debug:")
    print(f"      docker run --rm -v {output_path}:/out -w /out -it ubuntu:{version} bash")
    print(f"      # Inside: apt-get update && add-apt-repository universe && apt-get download {actual_package}")

print(f"\n📁 Location: {output_path}")

# =========================
# CLOSE DB
# =========================
cursor.close()
conn.close()
print("🔒 Done")
