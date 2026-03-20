import os
import re
import sys
import time
from db import get_db_connection

# =========================
# INPUT
# =========================
if len(sys.argv) != 3:
    print("❌ Usage: python3 script.py <agent_id> <patch_id>")
    exit()

agent_id = sys.argv[1]
patch_id = sys.argv[2]

print(f"🎯 Agent ID : {agent_id}")
print(f"🎯 Patch ID : {patch_id}")

# =========================
# DB CONNECTION
# =========================
conn = get_db_connection()
cursor = conn.cursor(dictionary=True)
print("✅ DB Connected")

# =========================
# FETCH DATA
# =========================
query = """
SELECT d.ip_address, d.os_version, p.package_name
FROM devices d
JOIN linux_patches p ON d.agent_id = p.agent_id
WHERE d.agent_id = %s AND p.id = %s
"""

cursor.execute(query, (agent_id, patch_id))
row = cursor.fetchone()

if not row:
    print("❌ No data found")
    exit()

ip = row["ip_address"]
os_version = row["os_version"]
package = row["package_name"]

print("\n📦 Package:", package)

# =========================
# VERSION
# =========================
def normalize(v):
    match = re.search(r'\d+\.\d+', v)
    return match.group() if match else "22.04"

version = normalize(os_version)

docker_map = {
    "20.04": "ubuntu:20.04",
    "22.04": "ubuntu:22.04",
    "24.04": "ubuntu:24.04"
}

image = docker_map.get(version, "ubuntu:22.04")

# =========================
# PATH
# =========================
output_path = f"/tmp/patches/{ip}_{patch_id}"
os.makedirs(output_path, exist_ok=True)

container = f"patch_{patch_id}"

print(f"📁 Folder: {output_path}")

# =========================
# RUN CONTAINER
# =========================
run_cmd = f"""
docker run -d --name {container} {image} bash -c "
apt update &&
cd /tmp &&
apt-get download {package} &&
for dep in $(apt-cache depends {package} | grep 'Depends:' | awk '{{print $2}}'); do
    apt-get download $dep || true
done &&
sleep 5
"
"""

os.system(run_cmd)

print("⏳ Waiting for download...")
time.sleep(10)

# =========================
# COPY ONLY .deb FILES
# =========================
print("📂 Copying .deb files...")

copy_cmd = f"docker cp {container}:/tmp/. {output_path}"
os.system(copy_cmd)

# =========================
# REMOVE CONTAINER
# =========================
os.system(f"docker rm -f {container}")

# =========================
# VERIFY
# =========================
files = [f for f in os.listdir(output_path) if f.endswith(".deb")]

print("\n📊 RESULT:")
if files:
    print(f"✅ SUCCESS → {len(files)} files\n")
    for f in files:
        print("📦", f)
else:
    print("❌ FAILED → No files")

print(f"\n📁 Location: {output_path}")

# =========================
# CLOSE
# =========================
cursor.close()
conn.close()
print("🔒 Done")
