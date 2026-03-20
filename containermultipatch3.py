import os
import re
import sys
import time
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from db import get_db_connection

# =========================
# USAGE
# --------------------------
# Single:
#   python3 containersingle2.py <agent_id> <patch_id>
#
# Multiple patches, one agent:
#   python3 containersingle2.py <agent_id> 141,142,143
#
# Multiple agents + patches:
#   python3 containersingle2.py <agent1>:<id1,id2> <agent2>:<id3,id4>
#
# All patches of an agent:
#   python3 containersingle2.py <agent_id> all
#   python3 containersingle2.py <agent1>:all <agent2>:all
# =========================

# Final destination for all downloaded .deb files
LINUX_PATCHES_DIR = "/opt/nms/Report/Agent/server/Infraknittech/linux_patches"

# =========================
# PARSE ARGUMENTS
# =========================
jobs_input = []

if len(sys.argv) == 3 and ":" not in sys.argv[1]:
    jobs_input.append((sys.argv[1], sys.argv[2]))

elif len(sys.argv) >= 2 and ":" in sys.argv[1]:
    for arg in sys.argv[1:]:
        if ":" not in arg:
            print(f"❌ Invalid format '{arg}' — use agent_id:patch_id")
            exit(1)
        agent_id, patch_part = arg.split(":", 1)
        jobs_input.append((agent_id.strip(), patch_part.strip()))

else:
    print("❌ Usage:")
    print("   Single           : python3 containersingle2.py <agent_id> <patch_id>")
    print("   Multiple patches : python3 containersingle2.py <agent_id> 141,142,143")
    print("   Multiple agents  : python3 containersingle2.py <agent1>:<id1,id2> <agent2>:<id3>")
    print("   All patches      : python3 containersingle2.py <agent_id> all")
    exit(1)

print(f"📥 Input : {len(jobs_input)} agent(s)")
for agent_id, patch_part in jobs_input:
    print(f"   Agent: {agent_id} → Patches: {patch_part}")

# =========================
# DB CONNECTION
# =========================
conn   = get_db_connection()
cursor = conn.cursor(dictionary=True)
print("✅ DB Connected")

# =========================
# FETCH ALL PATCH DATA FROM DB
# =========================
jobs = []

for agent_id, patch_part in jobs_input:
    if patch_part.lower() == "all":
        cursor.execute("""
            SELECT p.id FROM linux_patches p
            WHERE p.agent_id = %s
        """, (agent_id,))
        rows      = cursor.fetchall()
        patch_ids = [str(r["id"]) for r in rows]
        print(f"   Agent {agent_id[:12]}.. → ALL → {len(patch_ids)} patches found")
    else:
        patch_ids = [p.strip() for p in patch_part.split(",")]

    for patch_id in patch_ids:
        cursor.execute("""
            SELECT d.ip_address, d.os_version, p.package_name, p.patch_type
            FROM devices d
            JOIN linux_patches p ON d.agent_id = p.agent_id
            WHERE d.agent_id = %s AND p.id = %s
        """, (agent_id, patch_id))
        row = cursor.fetchone()
        if row:
            jobs.append((agent_id, patch_id, row))
        else:
            print(f"   ⚠️  Agent {agent_id[:12]} Patch {patch_id} → Not found in DB, skipping")

cursor.close()
conn.close()

if not jobs:
    print("❌ No valid patches found to process")
    exit(1)

print(f"\n✅ Total jobs: {len(jobs)}")

# =========================
# HELPERS
# =========================
def normalize(v):
    m = re.search(r'\d+\.\d+', v)
    return m.group() if m else "22.04"

docker_map = {
    "20.04": "ubuntu:20.04",
    "22.04": "ubuntu:22.04",
    "24.04": "ubuntu:24.04",
}

package_map = {
    "apt-ntop": "ntopng",
}

def is_already_downloaded(final_dest):
    """Check if patch folder already has .deb files"""
    if not os.path.exists(final_dest):
        return False
    deb_files = [f for f in os.listdir(final_dest) if f.endswith(".deb")]
    return len(deb_files) > 0

def cleanup_folder(path):
    """Remove folder completely if it exists"""
    if os.path.exists(path):
        shutil.rmtree(path)

# =========================
# SINGLE PATCH DOWNLOAD FUNCTION
# =========================
def download_patch(agent_id, patch_id, row):
    ip             = row["ip_address"]
    os_version     = row["os_version"]
    package        = row["package_name"]
    patch_type     = row["patch_type"] or ""
    actual_package = package_map.get(package.lower(), package)
    version        = normalize(os_version)
    image          = docker_map.get(version, "ubuntu:22.04")

    prefix     = f"[{ip} | Patch {patch_id}]"
    final_dest = os.path.join(LINUX_PATCHES_DIR, f"{ip}_{patch_id}")

    # =========================
    # SKIP IF ALREADY DOWNLOADED
    # Check final destination — if .deb files exist, skip
    # =========================
    if is_already_downloaded(final_dest):
        existing = [f for f in os.listdir(final_dest) if f.endswith(".deb")]
        print(f"{prefix} ⏭️  SKIPPED → Already downloaded ({len(existing)} files in {final_dest})")
        return agent_id, patch_id, "SKIPPED", existing, final_dest

    # Temp download path under $HOME (snap Docker only allows $HOME mounts)
    home        = os.path.expanduser("~")
    output_path = os.path.join(home, "patches", f"{ip}_{patch_id}")
    os.makedirs(output_path, exist_ok=True)

    is_ntop     = "ntop" in actual_package.lower()
    is_external = "external" in patch_type.lower() and not is_ntop

    if actual_package != package:
        print(f"{prefix} ⚠️  Package mapped: '{package}' → '{actual_package}'")

    print(f"{prefix} 🚀 {actual_package} | {image}")
    print(f"{prefix} 📥 Temp  : {output_path}")
    print(f"{prefix} 📦 Final : {final_dest}")

    # -------------------------------------------------------
    # DOCKER COMMAND
    # -------------------------------------------------------
    if is_external:
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

    # Run Docker
    result = subprocess.run(docker_cmd, shell=True, capture_output=True, text=True)

    print(f"\n{prefix} 📋 Docker output:")
    print("─" * 50)
    print(result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)
    if result.returncode != 0:
        print(f"STDERR: {result.stderr[-500:]}")
    print("─" * 50)

    # Verify downloaded files in temp folder
    time.sleep(1)
    skip        = {"ntop-bootstrap.deb", "apt-ntop-stable.deb", "apt-ntop.deb"}
    patch_files = [f for f in os.listdir(output_path)
                   if f.endswith(".deb") and f not in skip]

    # =========================
    # FAILED — cleanup temp folder, do NOT create final_dest
    # =========================
    if not patch_files:
        print(f"{prefix} ❌ FAILED → No .deb files downloaded")
        print(f"{prefix} 🧹 Cleaning up temp folder...")
        cleanup_folder(output_path)   # remove ~/patches/{ip}_{patch_id}/
        # Note: final_dest was never created — no folder left behind
        print(f"{prefix} 💡 Debug:")
        print(f"   docker run --rm -v {output_path}:/out -w /out -it ubuntu:{version} bash")
        return agent_id, patch_id, "FAILED", [], None

    # =========================
    # SUCCESS — create final_dest and move files
    # Only create the folder when we have files to put in it
    # =========================
    os.makedirs(final_dest, exist_ok=True)

    print(f"\n{prefix} 📂 Moving files to: {final_dest}")
    moved_files = []
    for f in patch_files:
        src = os.path.join(output_path, f)
        dst = os.path.join(final_dest, f)
        shutil.move(src, dst)
        moved_files.append(f)
        print(f"{prefix}    ✅ {f}")

    # Cleanup temp folder
    cleanup_folder(output_path)
    print(f"{prefix} 🧹 Temp folder removed")
    print(f"{prefix} ✅ SUCCESS → {len(moved_files)} file(s) in {final_dest}")

    return agent_id, patch_id, "SUCCESS", moved_files, final_dest


# =========================
# PARALLEL EXECUTION
# MAX_WORKERS = 3 → 3 Docker containers at a time
# =========================
MAX_WORKERS = 3

print("\n" + "=" * 60)
print(f"🚀 Parallel download started | max {MAX_WORKERS} containers")
print("=" * 60 + "\n")

summary_success = []
summary_skipped = []
summary_failed  = []

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    futures = {
        executor.submit(download_patch, agent_id, patch_id, row): (agent_id, patch_id)
        for agent_id, patch_id, row in jobs
    }
    for future in as_completed(futures):
        agent_id, patch_id, status, files, path = future.result()
        if status == "SUCCESS":
            summary_success.append((agent_id, patch_id, files, path))
        elif status == "SKIPPED":
            summary_skipped.append((agent_id, patch_id, files, path))
        else:
            summary_failed.append((agent_id, patch_id))

# =========================
# FINAL SUMMARY
# =========================
print("\n" + "=" * 60)
print("📊 FINAL SUMMARY")
print("=" * 60)

print(f"\n✅ SUCCESS : {len(summary_success)} / {len(jobs)}")
for agent_id, patch_id, files, path in summary_success:
    total_mb = sum(os.path.getsize(os.path.join(path, f)) for f in files) / 1024 / 1024
    print(f"   Agent {agent_id[:12]}.. | Patch {patch_id:>5} → {len(files)} files | {total_mb:.1f} MB")
    print(f"   📁 {path}")

if summary_skipped:
    print(f"\n⏭️  SKIPPED : {len(summary_skipped)} / {len(jobs)} (already downloaded)")
    for agent_id, patch_id, files, path in summary_skipped:
        print(f"   Agent {agent_id[:12]}.. | Patch {patch_id:>5} → {len(files)} files already in {path}")

if summary_failed:
    print(f"\n❌ FAILED  : {len(summary_failed)} / {len(jobs)}")
    for agent_id, patch_id in summary_failed:
        print(f"   Agent {agent_id[:12]}.. | Patch {patch_id:>5} → No folder created")

print(f"\n🔒 Done")
