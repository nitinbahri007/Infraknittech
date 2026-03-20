import os
import re
import sys
import time
import shutil
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

print(f"\n📦 Package   : {package}")
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
# OUTPUT PATH — must be under $HOME
# WHY: Docker is installed via snap on this server.
# Snap sandboxes Docker and only allows bind-mounting paths
# under $HOME. /tmp, /opt, /var etc. are all blocked.
# Using ~/patches/ ensures Docker can always access the files.
# =========================
home        = os.path.expanduser("~")
output_path = os.path.join(home, "patches", f"{ip}_{patch_id}")
os.makedirs(output_path, exist_ok=True)
print(f"📁 Folder    : {output_path}")

# =========================
# DETECT NTOP / EXTERNAL
# =========================
is_ntop     = "ntop" in package.lower()
is_external = "external" in patch_type.lower() or is_ntop

# =========================
# NTOP: DOWNLOAD BOOTSTRAP .DEB ON HOST
# Copy into output_path so Docker volume can access it.
# =========================
if is_external:
    ntop_url    = f"https://packages.ntop.org/apt-stable/{version}/all/apt-ntop-stable.deb"
    ntop_in_vol = os.path.join(output_path, "ntop-bootstrap.deb")

    # Cleanup stale file if any
    if os.path.exists(ntop_in_vol):
        os.remove(ntop_in_vol)

    print(f"\n🌐 Downloading ntop bootstrap on HOST ...")
    print(f"   {ntop_url}")

    dl = subprocess.run(
        f"wget -q --show-progress --tries=3 '{ntop_url}' -O '{ntop_in_vol}'",
        shell=True
    )
    if dl.returncode != 0:
        print("   wget failed → trying curl ...")
        dl = subprocess.run(
            f"curl -fsSL --retry 3 '{ntop_url}' -o '{ntop_in_vol}'",
            shell=True
        )

    if dl.returncode != 0 or not os.path.isfile(ntop_in_vol):
        print(f"❌ Could not download ntop bootstrap.")
        cursor.close()
        conn.close()
        exit(1)

    # Validate it's a real .deb
    chk = subprocess.run(
        f"dpkg-deb --info '{ntop_in_vol}'",
        shell=True, capture_output=True, text=True
    )
    if chk.returncode != 0:
        print("❌ Downloaded file is not a valid .deb!")
        print(chk.stderr)
        cursor.close()
        conn.close()
        exit(1)

    size_kb = os.path.getsize(ntop_in_vol) // 1024
    print(f"   ✅ Bootstrap .deb valid ({size_kb} KB) → {ntop_in_vol}")

    docker_cmd = f"""
docker run --rm \
  -v {output_path}:/out \
  -w /out \
  {image} bash -c '
set -e
export DEBIAN_FRONTEND=noninteractive

echo "--- Step 1: install base deps ---"
apt-get update -qq
apt-get install -y \
    wget whiptail gnupg \
    software-properties-common \
    apt-transport-https \
    ca-certificates 2>&1 | tail -3

echo "--- Step 2: install ntop repo ---"
dpkg -i /out/ntop-bootstrap.deb || apt-get install -f -y

echo "--- Step 3: apt update with ntop repo ---"
apt-get update -qq

echo "--- Step 4: download {package} ---"
cd /out
if apt-get download {package} 2>&1; then
    echo "OK: {package} downloaded"
else
    echo "WARN: {package} not found — available ntop packages:"
    apt-cache search ntop | head -20
fi

echo "--- Step 5: download direct dependencies ---"
for dep in $(apt-cache depends {package} 2>/dev/null \
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
    docker_cmd = f"""
docker run --rm \
  -v {output_path}:/out \
  -w /out \
  {image} bash -c '
set -e
export DEBIAN_FRONTEND=noninteractive

echo "--- Step 1: apt update ---"
apt-get update -qq

echo "--- Step 2: download {package} ---"
if apt-get download {package} 2>&1; then
    echo "OK: {package} downloaded"
else
    echo "WARN: {package} not found"
fi

echo "--- Step 3: download direct dependencies ---"
for dep in $(apt-cache depends {package} 2>/dev/null \
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
skip        = {"ntop-bootstrap.deb", "apt-ntop-stable.deb", "apt-ntop.deb"}
patch_files = [f for f in all_files if f not in skip]

print("\n📊 RESULT:")
if patch_files:
    print(f"✅ SUCCESS → {len(patch_files)} .deb file(s) downloaded\n")
    for f in patch_files:
        size = os.path.getsize(os.path.join(output_path, f))
        print(f"   📦 {f}  ({size:,} bytes)")
    status = "SUCCESS"
else:
    print("❌ FAILED → No .deb files found")
    print(f"\n   💡 Manual debug:")
    print(f"      docker run --rm -v {output_path}:/out -it ubuntu:{version} bash")
    print(f"      # Inside: dpkg -i /out/ntop-bootstrap.deb && apt-get update && apt-cache search ntop")
    status = "FAILED"

print(f"\n📁 Location: {output_path}")

# Cleanup bootstrap deb from output folder
bootstrap = os.path.join(output_path, "ntop-bootstrap.deb")
if os.path.exists(bootstrap):
    os.remove(bootstrap)
    print("🧹 Bootstrap .deb removed from output folder")

# =========================
# CLOSE DB
# =========================
cursor.close()
conn.close()
print("🔒 Done")
