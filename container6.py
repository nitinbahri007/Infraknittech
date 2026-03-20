import os
import re
import time
from db import get_db_connection

print("🔌 Connecting to database...")

# =========================
# DB CONNECTION
# =========================
try:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if conn.is_connected():
        print("🟢 MySQL connection active")

    print("✅ DB Connected")

except Exception as e:
    print(f"❌ DB Connection Failed: {e}")
    exit()


# =========================
# FETCH DATA FROM DB
# =========================
query = """
SELECT 
    d.agent_id,
    d.ip_address,
    d.status,
    d.os_name,
    d.os_version,
    p.id AS patch_id,
    p.package_name
FROM devices d
JOIN linux_patches p ON d.agent_id = p.agent_id
WHERE d.os_name LIKE '%Linux%'
AND LOWER(p.patch_type) = 'outdated'
AND p.package_name IS NOT NULL
"""

print("\n📥 Fetching patches from DB...")
cursor.execute(query)
rows = cursor.fetchall()

print(f"📊 Total patches found in DB: {len(rows)}")

if not rows:
    print("⚠️ No patches found. Exiting...")
    exit()


# =========================
# GROUP BY DEVICE
# =========================
devices = {}

for row in rows:
    agent_id = row["agent_id"]

    if agent_id not in devices:
        devices[agent_id] = {
            "ip": row["ip_address"],
            "status": row["status"],
            "os_version": row["os_version"],
            "packages": []
        }

    devices[agent_id]["packages"].append({
        "id": row["patch_id"],
        "name": row["package_name"]
    })


print(f"🖥 Devices found: {len(devices)}")


# =========================
# NORMALIZE OS VERSION
# =========================
def normalize_version(v):
    match = re.search(r'\d+\.\d+', v)
    return match.group() if match else "22.04"


# =========================
# DOCKER IMAGE MAP
# =========================
docker_map = {
    "20.04": "ubuntu:20.04",
    "22.04": "ubuntu:22.04",
    "24.04": "ubuntu:24.04"
}


# =========================
# PROCESS DEVICES
# =========================
for i, (agent_id, device) in enumerate(devices.items(), start=1):

    print("\n" + "="*60)
    print(f"🚀 Device {i}/{len(devices)}")

    ip = device["ip"]
    status = device["status"]
    version = device["os_version"]
    packages = device["packages"]

    base_version = normalize_version(version)
    image = docker_map.get(base_version, "ubuntu:22.04")

    print(f"📡 IP: {ip}")
    print(f"📶 Status: {status}")
    print(f"🖥 OS: {version}")
    print(f"🐳 Docker: {image}")

    # =========================
    # PRINT PATCHES
    # =========================
    print("\n📦 Patches detected from DB:")
    for pkg in packages:
        print(f"   🔹 ID: {pkg['id']} | Package: {pkg['name']}")

    # =========================
    # OUTPUT PATH
    # =========================
    host_path = f"/tmp/patches/{ip}_{base_version}"
    os.makedirs(host_path, exist_ok=True)

    pkg_names = " ".join([pkg["name"] for pkg in packages])

    print("\n⬇️ Starting Docker download...")

    container_name = f"patch_dl_{ip.replace('.', '_')}"

    # =========================
    # RUN CONTAINER
    # =========================
    run_cmd = (
        f"docker run -d --name {container_name} {image} "
        f"bash -c \"apt update && apt-get install --download-only -y {pkg_names} && sleep 20\""
    )

    os.system(run_cmd)

    # Wait for download
    print("⏳ Waiting for download to complete...")
    time.sleep(25)

    # =========================
    # COPY FILES
    # =========================
    print("📂 Copying .deb files from container...")

    copy_cmd = f"docker cp {container_name}:/var/cache/apt/archives/. {host_path}"
    os.system(copy_cmd)

    # =========================
    # REMOVE CONTAINER
    # =========================
    os.system(f"docker rm -f {container_name}")

    # =========================
    # VERIFY FILES
    # =========================
    files = os.listdir(host_path)

    if files:
        print(f"\n✅ Download SUCCESS for {ip}")
        print(f"📁 Files downloaded: {len(files)}")

        for f in files:
            print(f"   📦 {f}")

    else:
        print(f"\n❌ ERROR: No files found for {ip}")


print("\n🎉 All devices processed!")

cursor.close()
conn.close()

print("🔒 DB Closed")
