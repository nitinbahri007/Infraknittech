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

print(f"📊 Total patches found: {len(rows)}")

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
            "packages": {}
        }

    # remove duplicate package
    devices[agent_id]["packages"][row["package_name"]] = row["patch_id"]

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

    print("\n" + "="*70)
    print(f"🚀 DEVICE {i}/{len(devices)}")
    print("="*70)

    ip = device["ip"]
    status = device["status"]
    version = device["os_version"]
    packages_dict = device["packages"]

    base_version = normalize_version(version)
    image = docker_map.get(base_version, "ubuntu:22.04")

    print(f"📡 IP Address     : {ip}")
    print(f"📶 Status         : {status}")
    print(f"🖥 OS Version     : {version}")
    print(f"🐳 Docker Image   : {image}")

    # =========================
    # PRINT PATCH LIST
    # =========================
    print("\n📦 PATCHES FROM DB:")
    for pkg, pid in packages_dict.items():
        print(f"   🔹 [{pid}] {pkg}")

    # =========================
    # OUTPUT PATH
    # =========================
    host_path = f"/tmp/patches/{ip}_{base_version}"
    os.makedirs(host_path, exist_ok=True)

    pkg_names = " ".join(packages_dict.keys())

    print("\n⬇️ Starting Download...")

    container_name = f"patch_dl_{ip.replace('.', '_')}"

    # Clean old container (if exists)
    os.system(f"docker rm -f {container_name} > /dev/null 2>&1")

    # =========================
    # RUN CONTAINER
    # =========================
    run_cmd = (
        f"docker run -d --name {container_name} {image} "
        f"bash -c \"apt update && apt-get install --download-only -y {pkg_names} && sleep 20\""
    )

    print("⚙️ Running container...")
    os.system(run_cmd)

    print("⏳ Waiting for download...")
    time.sleep(25)

    # =========================
    # COPY FILES
    # =========================
    print("📂 Copying files...")
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

    print("\n📊 RESULT:")
    if files:
        print(f"✅ SUCCESS → {len(files)} files downloaded")

        print("\n📥 DOWNLOADED PATCHES:")
        for pkg, pid in packages_dict.items():
            print(f"   ✅ [{pid}] {pkg}")

    else:
        print("❌ FAILED → No files found")

    print("\n📁 FILE LIST:")
    for f in files[:10]:   # only first 10 show
        print(f"   📦 {f}")

    if len(files) > 10:
        print(f"   ... +{len(files)-10} more files")


# =========================
# CLOSE DB
# =========================
cursor.close()
conn.close()

print("\n🎉 ALL DEVICES PROCESSED")
print("🔒 DB Connection Closed")
