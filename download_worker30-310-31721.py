import os
import re
import time
import shutil
import subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from db import get_db_connection

# =========================
# CONFIG
# =========================
LINUX_PATCHES_DIR = "/opt/nms/Report/Agent/server/Infraknittech/linux_patches"

# Pre-built images (faster — repos already configured)
# Run setup_docker_images() once to build these
ubuntu_docker_map = {
    "20.04": "nms-ubuntu:20.04",
    "22.04": "nms-ubuntu:22.04",
    "24.04": "nms-ubuntu:24.04",
}

rhel_docker_map = {
    "6" : "nms-rhel:6",
    "7" : "nms-rhel:7",
    "8" : "nms-rhel:8",
    "9" : "nms-rhel:9",
    "10": "nms-rhel:9",
}

# Fallback to official images if pre-built not available
ubuntu_fallback_map = {
    "20.04": "ubuntu:20.04",
    "22.04": "ubuntu:22.04",
    "24.04": "ubuntu:24.04",
}

rhel_fallback_map = {
    "6" : "centos:6",
    "7" : "centos:7",
    "8" : "rockylinux:8",
    "9" : "rockylinux:9",
    "10": "rockylinux:9",
}

# Ubuntu codename map
codename_map = {
    "20.04": "focal",
    "22.04": "jammy",
    "24.04": "noble",
}

# ntop repo uses version number not codename
ntop_version_map = {
    "20.04": "20.04",
    "22.04": "22.04",
    "24.04": "24.04",
}

# Package name aliases
package_map = {
    "apt-ntop": "ntopng",
}

# MongoDB package patterns
MONGODB_PACKAGES = [
    "mongodb",
    "mongodb-org",
    "mongod",
    "mongos",
]

# Full ntop family — all need ntop repo
NTOP_PACKAGES = [
    "ntopng",
    "ntop-license",
    "nprobe",
    "ndpi",
    "pfring",
    "pfring-dkms",
    "n2disk",
    "cento",
    "ntopng-data",
    "apt-ntop",
    "ntopng-dev",
    "nprobe-dev",
]

# RHEL version string indicators
RHEL_INDICATORS = [
    ".el", "el6", "el7", "el8", "el9", "el10",
]

# RHEL OS string keywords
RHEL_OS_KEYWORDS = [
    "rhel", "centos", "rocky", "fedora",
    "almalinux", "red hat", "redhat",
]

# Junk version strings
JUNK_VERSIONS = {
    "external_repo", "external", "outdated",
    "null", "none", "n/a", "unknown", "",
}

# Virtual/meta packages — no real .rpm/.deb exists
VIRTUAL_PACKAGES = [
    "python-unversioned-command",
    "python3-unversioned-command",
    "kernel-headers",
    "kernel-devel",
    "kernel-modules",
    "kernel-core",
    "glibc-all-langpacks",
]

# Parallel workers
MAX_WORKERS = 6


# =========================
# DOCKER IMAGE SETUP
# =========================
def setup_docker_images():
    """
    Build pre-configured Docker images with repos already set up.
    Run once at server start — saves time on every download.
    ✅ lsb-release + whiptail included for ntop support.
    """
    images = {
        "nms-ubuntu:22.04": """
FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq && \\
    apt-get install -y wget gnupg curl lsb-release whiptail \\
        software-properties-common ca-certificates 2>&1 | tail -3 && \\
    add-apt-repository universe -y && \\
    apt-get update -qq
""",
        "nms-ubuntu:20.04": """
FROM ubuntu:20.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq && \\
    apt-get install -y wget gnupg curl lsb-release whiptail \\
        software-properties-common ca-certificates 2>&1 | tail -3 && \\
    add-apt-repository universe -y && \\
    apt-get update -qq
""",
        "nms-ubuntu:24.04": """
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq && \\
    apt-get install -y wget gnupg curl lsb-release whiptail \\
        software-properties-common ca-certificates 2>&1 | tail -3 && \\
    add-apt-repository universe -y && \\
    apt-get update -qq
""",
        "nms-rhel:9": """
FROM rockylinux:9
RUN dnf update -y -q && \\
    dnf install -y dnf-plugins-core yum-utils && \\
    dnf clean all
""",
        "nms-rhel:8": """
FROM rockylinux:8
RUN dnf update -y -q && \\
    dnf install -y dnf-plugins-core yum-utils && \\
    dnf clean all
""",
    }

    home   = os.path.expanduser("~")
    built  = []
    failed = []

    for tag, dockerfile_content in images.items():
        check = subprocess.run(
            f"docker image inspect {tag}",
            shell=True, capture_output=True
        )
        if check.returncode == 0:
            print(f"✅ Image {tag} already exists — skipping")
            continue

        print(f"🔨 Building {tag}...")
        safe_tag        = tag.replace(":", "_").replace("/", "_")
        dockerfile_path = os.path.join(home, f"Dockerfile_{safe_tag}")

        with open(dockerfile_path, "w") as f:
            f.write(dockerfile_content.strip())

        result = subprocess.run(
            f"docker build -t {tag} -f {dockerfile_path} .",
            shell=True, capture_output=True, text=True, cwd=home
        )
        os.remove(dockerfile_path)

        if result.returncode == 0:
            print(f"✅ Built {tag}")
            built.append(tag)
        else:
            print(f"❌ Failed {tag}: {result.stderr[-300:]}")
            failed.append(tag)

    return {"built": built, "failed": failed}


def get_docker_image(os_type, version_key):
    """Returns pre-built image if available, else official fallback."""
    if os_type == "rhel":
        prebuilt = rhel_docker_map.get(version_key, "nms-rhel:9")
        fallback = rhel_fallback_map.get(version_key, "rockylinux:9")
    else:
        prebuilt = ubuntu_docker_map.get(version_key, "nms-ubuntu:22.04")
        fallback = ubuntu_fallback_map.get(version_key, "ubuntu:22.04")

    check = subprocess.run(
        f"docker image inspect {prebuilt}",
        shell=True, capture_output=True
    )
    if check.returncode == 0:
        return prebuilt, True
    else:
        print(f"⚠️  Pre-built {prebuilt} not found — fallback {fallback}")
        return fallback, False


# =========================
# HELPERS
# =========================
def sanitize_version(v):
    """Clean junk version strings like 'external_repo', 'outdated'."""
    if str(v).lower().strip() in JUNK_VERSIONS:
        return "unknown"
    return str(v).strip()


def normalize_ubuntu_version(v):
    """Extract X.Y from Ubuntu OS string."""
    m = re.search(r'\d+\.\d+', str(v))
    return m.group() if m else "22.04"


def normalize_rhel_version(os_version, installed_version=""):
    """Extract EL major version. e.g. '6.12.0-55.9.1.el10_0' → '10'"""
    for s in [str(installed_version), str(os_version)]:
        m = re.search(r'el(\d+)', s.lower())
        if m:
            return m.group(1)
    m = re.search(r'\d+', str(os_version))
    if m:
        return m.group()
    return "9"


def detect_os_type(os_version, patch_type, installed_version, latest_version):
    """Detect 'rhel' or 'ubuntu' from version strings."""
    for val in [str(installed_version), str(latest_version), str(patch_type)]:
        if any(ind in val.lower() for ind in RHEL_INDICATORS):
            return "rhel"
    if any(kw in str(os_version).lower() for kw in RHEL_OS_KEYWORDS):
        return "rhel"
    return "ubuntu"


def detect_repo(package, patch_type):
    """Detect Ubuntu repo type: 'mongodb' | 'ntopng' | 'standard'"""
    pkg = package.lower()
    pt  = str(patch_type).lower()
    if any(m in pkg for m in MONGODB_PACKAGES):
        return "mongodb"
    if any(n in pkg for n in NTOP_PACKAGES):
        return "ntopng"
    if "external" in pt:
        return "external"
    return "standard"


def is_virtual_package(package):
    """Check if package is virtual/meta with no real file."""
    return any(skip in package.lower() for skip in VIRTUAL_PACKAGES)


def is_already_downloaded(final_dest):
    if not os.path.exists(final_dest):
        return False
    return any(
        f.endswith(".deb") or f.endswith(".rpm")
        for f in os.listdir(final_dest)
    )


def cleanup_folder(path):
    if os.path.exists(path):
        shutil.rmtree(path)


# =========================
# DB FUNCTIONS
# ✅ FIXED: patch_download_log and patch_alert are now separate
#    patch_download_log → one row per file (22 files = 22 rows)
#    patch_alert        → ONE row per patch always
# =========================

def log_file_to_db(patch_id, ip, package, version,
                   file_path, status, now, container_log=""):
    """
    Insert ONE row into patch_download_log per file.
    Called in a loop for each downloaded file.
    Does NOT insert into patch_alert.
    """
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO patch_download_log
                (patch_id, ip_address, package_name, version,
                 file_path, status, downloaded_at, container_log)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (patch_id, ip, package, version,
              file_path, status, now, container_log))

        conn.commit()
        cursor.close()
        conn.close()

    except Exception as e:
        print(f"⚠️  log_file_to_db error patch {patch_id}: {e}")


def log_alert_to_db(agent_id, package, message, category):
    """
    Insert ONE row into patch_alert per patch.
    Called ONCE after all files are processed — not per file.
    """
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        now    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT INTO patch_alert
                (agent_id, kb, message, category, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (agent_id, package, message, category, now))

        conn.commit()
        cursor.close()
        conn.close()

    except Exception as e:
        print(f"⚠️  log_alert_to_db error: {e}")


def insert_running_log(patch_id, agent_id, ip, package, version):
    """
    Insert 'running' record immediately — refresh detects in-progress.
    Does NOT insert patch_alert (not a final state).
    """
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        now    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT INTO patch_download_log
                (patch_id, ip_address, package_name, version,
                 file_path, status, downloaded_at, container_log)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (patch_id, ip, package, version,
              "", "running", now, "🐳 Container started..."))

        conn.commit()
        cursor.close()
        conn.close()

    except Exception as e:
        print(f"⚠️  insert_running_log error: {e}")


def update_running_log_in_db(patch_id, container_log):
    """Update running record every 5 lines — refresh shows latest logs."""
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE patch_download_log
            SET container_log = %s
            WHERE patch_id = %s AND status = 'running'
            ORDER BY downloaded_at DESC
            LIMIT 1
        """, (container_log, patch_id))

        conn.commit()
        cursor.close()
        conn.close()

    except Exception as e:
        print(f"⚠️  update_running_log error: {e}")


def delete_running_log(patch_id):
    """Delete 'running' record before writing final status."""
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM patch_download_log
            WHERE patch_id = %s AND status = 'running'
        """, (patch_id,))

        conn.commit()
        cursor.close()
        conn.close()

    except Exception as e:
        print(f"⚠️  delete_running_log error: {e}")


# =========================
# STREAM DOCKER LOGS
# =========================
def run_docker_with_streaming(docker_cmd, patch_id, progress_store):
    """
    Stream Docker output line by line.
    - Memory update      → live polling same session
    - DB update every 5  → page refresh recovery
    """
    container_logs = []

    process = subprocess.Popen(
        docker_cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    print(f"🐳 Docker started patch {patch_id}")

    for line in process.stdout:
        line = line.strip()
        if not line:
            continue

        container_logs.append(line)
        print(f"[patch {patch_id}] {line}")

        if str(patch_id) in progress_store.get("items", {}):
            progress_store["items"][str(patch_id)].update({
                "status"         : "running",
                "message"        : line,
                "container_logs" : list(container_logs)
            })

        if len(container_logs) % 5 == 0:
            update_running_log_in_db(patch_id, "\n".join(container_logs))

    process.wait()
    print(f"🐳 Docker finished patch {patch_id} — exit: {process.returncode}")
    update_running_log_in_db(patch_id, "\n".join(container_logs))

    return process.returncode, container_logs


# =========================
# BUILD DOCKER COMMANDS
# =========================
def build_ubuntu_docker_cmd(repo_type, image, output_path,
                             version, actual_package):
    """
    Ubuntu apt based Docker command.
    ✅ ntop: always apt-get update first (wget needs it)
    ✅ ntop: version number URL (22.04) not codename (jammy)
    ✅ ntop: lsb-release + whiptail before dpkg
    """
    ntop_ver = ntop_version_map.get(version, "22.04")
    codename = codename_map.get(version, "jammy")

    fast_dep_snippet = f"""
apt-get download $(apt-cache depends --recurse \
    --no-recommends --no-suggests --no-conflicts \
    --no-breaks --no-replaces --no-enhances \
    {actual_package} 2>/dev/null \
    | grep "^\\w" | sort -u) 2>/dev/null || true
"""

    # ── MongoDB ──
    if repo_type == "mongodb":
        return f"""
docker run --rm \
  -v {output_path}:/out \
  -w /out \
  {image} bash -c '
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq 2>&1 | tail -3
apt-get install -y gnupg curl ca-certificates 2>&1 | tail -2
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc \
    | gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] \
https://repo.mongodb.org/apt/ubuntu {codename}/mongodb-org/7.0 multiverse" \
    | tee /etc/apt/sources.list.d/mongodb-org-7.0.list
apt-get update -qq
cd /out
apt-get download {actual_package} 2>&1 || true
{fast_dep_snippet}
echo "➡️  Files downloaded:"
ls -lh /out || true
'
"""

    # ── ntop family ──
    elif repo_type == "ntopng":
        return f"""
docker run --rm \
  -v {output_path}:/out \
  -w /out \
  {image} bash -c '
set -e
export DEBIAN_FRONTEND=noninteractive

echo "➡️  Updating package lists..."
apt-get update -qq 2>&1 | tail -3

echo "➡️  Installing required tools..."
apt-get install -y wget gnupg curl lsb-release whiptail ca-certificates 2>&1 | tail -3

echo "➡️  Downloading ntop repo package..."
wget -qO /tmp/apt-ntop-stable.deb \
    https://packages.ntop.org/apt-stable/{ntop_ver}/all/apt-ntop-stable.deb \
    || {{ echo "❌ Failed to fetch ntop repo for version {ntop_ver}"; exit 1; }}

echo "➡️  Installing ntop repo..."
dpkg -i /tmp/apt-ntop-stable.deb 2>&1 || true
apt-get install -f -y -qq 2>&1 | tail -3

echo "➡️  Updating package lists with ntop repo..."
apt-get update -qq 2>&1 | tail -5

echo "➡️  Downloading {actual_package}..."
cd /out
apt-get download {actual_package} 2>&1 || true
{fast_dep_snippet}

echo "➡️  Files downloaded:"
ls -lh /out || true
'
"""

    # ── Standard apt ──
    else:
        return f"""
docker run --rm \
  -v {output_path}:/out \
  -w /out \
  {image} bash -c '
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq 2>&1 | tail -3
cd /out
echo "➡️  Downloading {actual_package}..."
apt-get download {actual_package} 2>&1 || true
{fast_dep_snippet}
echo "➡️  Files downloaded:"
ls -lh /out || true
'
"""


def build_rhel_docker_cmd(image, output_path, actual_package, is_prebuilt):
    """RHEL dnf/yum based Docker command."""
    update_cmd = "" if is_prebuilt else "dnf update -y -q 2>&1 | tail -3 || true"

    return f"""
docker run --rm \
  -v {output_path}:/out \
  -w /out \
  {image} bash -c '
set -e
{update_cmd}
echo "➡️  Downloading {actual_package} with all dependencies..."
cd /out
dnf install --downloadonly --downloaddir=/out {actual_package} -y 2>&1 || \
dnf download {actual_package} --resolve --alldeps 2>&1 || \
yumdownloader --resolve {actual_package} 2>&1 || true
echo "➡️  Files downloaded:"
ls -lh /out || true
echo "➡️  Done."
'
"""


def build_docker_cmd(os_type, repo_type, image, output_path,
                     version, actual_package, is_prebuilt):
    """Master function — picks correct Docker command."""
    if os_type == "rhel":
        return build_rhel_docker_cmd(image, output_path, actual_package, is_prebuilt)
    else:
        return build_ubuntu_docker_cmd(
            repo_type, image, output_path,
            version, actual_package
        )


# =========================
# SINGLE PATCH DOWNLOAD
# =========================
def download_single_patch(patch_id, ip, os_version, package, patch_type,
                          agent_id, latest_version, installed_version,
                          progress_store):

    actual_package    = package_map.get(package.lower(), package)
    latest_version    = sanitize_version(latest_version)
    installed_version = sanitize_version(installed_version)

    # ── Detect OS type ──
    os_type = detect_os_type(os_version, patch_type, installed_version, latest_version)

    if os_type == "rhel":
        rhel_ver           = normalize_rhel_version(os_version, installed_version)
        image, is_prebuilt = get_docker_image("rhel", rhel_ver)
        version            = rhel_ver
        repo_type          = "rhel"
    else:
        version            = normalize_ubuntu_version(os_version)
        image, is_prebuilt = get_docker_image("ubuntu", version)
        repo_type          = detect_repo(actual_package, patch_type)

    final_dest = os.path.join(LINUX_PATCHES_DIR, f"{ip}_{patch_id}")

    print(
        f"📦 Patch {patch_id} | {actual_package} | "
        f"os: {os_type} | repo: {repo_type} | "
        f"image: {image} | prebuilt: {is_prebuilt}"
    )

    # ── Initialize progress_store ──
    progress_store["items"][str(patch_id)] = {
        "patch_id"      : patch_id,
        "ip"            : ip,
        "package"       : actual_package,
        "status"        : "running",
        "files"         : [],
        "message"       : "Starting download...",
        "container_logs": [],
        "os_type"       : os_type,
        "repo_type"     : repo_type
    }

    # =========================
    # VIRTUAL PACKAGE CHECK
    # =========================
    if is_virtual_package(actual_package):
        msg = f"Skipped — '{actual_package}' is a virtual/meta package"
        print(f"⏭️  {msg}")
        progress_store["items"][str(patch_id)].update({
            "status"         : "skipped",
            "files"          : [],
            "message"        : msg,
            "container_logs" : [f"⏭️  {msg}"]
        })
        progress_store["done"] += 1

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # ✅ 1 file log + 1 alert
        log_file_to_db(patch_id, ip, actual_package, latest_version,
                       "", "skipped", now, container_log=msg)
        log_alert_to_db(agent_id, actual_package, msg, "VIRTUAL_PACKAGE")
        return "SKIPPED"

    # =========================
    # ALREADY DOWNLOADED CHECK
    # =========================
    if is_already_downloaded(final_dest):
        existing = [
            f for f in os.listdir(final_dest)
            if f.endswith(".deb") or f.endswith(".rpm")
        ]
        msg = f"Already downloaded ({len(existing)} files)"
        progress_store["items"][str(patch_id)].update({
            "status"         : "skipped",
            "files"          : existing,
            "message"        : msg,
            "container_logs" : ["⏭️  Skipped — already downloaded"]
        })
        progress_store["done"] += 1

        now       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        file_path = os.path.join(final_dest, existing[0]) if existing else final_dest
        # ✅ 1 file log + 1 alert
        log_file_to_db(patch_id, ip, actual_package, latest_version,
                       file_path, "skipped", now,
                       container_log="Skipped — already downloaded")
        log_alert_to_db(agent_id, actual_package, msg, "ALREADY_DOWNLOADED")
        return "SKIPPED"

    # Temp output path
    home        = os.path.expanduser("~")
    output_path = os.path.join(home, "patches", f"{ip}_{patch_id}")
    os.makedirs(output_path, exist_ok=True)

    # Insert running into DB immediately
    insert_running_log(patch_id, agent_id, ip, actual_package, latest_version)

    # ── Build Docker command ──
    docker_cmd = build_docker_cmd(
        os_type, repo_type, image,
        output_path, version, actual_package, is_prebuilt
    )

    # ── Run Docker with live streaming ──
    returncode, container_logs = run_docker_with_streaming(
        docker_cmd, patch_id, progress_store
    )

    container_log_str = "\n".join(container_logs)
    time.sleep(1)

    skip = {"ntop-bootstrap.deb", "apt-ntop-stable.deb", "apt-ntop.deb"}
    patch_files = [
        f for f in os.listdir(output_path)
        if (f.endswith(".deb") or f.endswith(".rpm")) and f not in skip
    ]

    delete_running_log(patch_id)

    # =========================
    # FAILED
    # =========================
    if not patch_files:
        cleanup_folder(output_path)
        msg = "Could not download — network issue or package not found"
        progress_store["items"][str(patch_id)].update({
            "status"         : "failed",
            "files"          : [],
            "message"        : msg,
            "container_logs" : container_logs + [f"❌ {msg}"]
        })
        progress_store["done"]   += 1
        progress_store["failed"] += 1

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # ✅ 1 file log + 1 alert
        log_file_to_db(patch_id, ip, actual_package, latest_version,
                       "", "failed", now, container_log=container_log_str)
        log_alert_to_db(agent_id, actual_package, msg, "FAIL_TO_DOWNLOAD")
        return "FAILED"

    # =========================
    # SUCCESS
    # =========================
    os.makedirs(final_dest, exist_ok=True)
    moved = []
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for f in patch_files:
        shutil.move(os.path.join(output_path, f), os.path.join(final_dest, f))
        moved.append(f)

    cleanup_folder(output_path)

    msg = f"{len(moved)} file(s) downloaded successfully"
    progress_store["items"][str(patch_id)].update({
        "status"         : "success",
        "files"          : moved,
        "path"           : final_dest,
        "message"        : msg,
        "container_logs" : container_logs + [f"✅ {msg}"]
    })
    progress_store["done"] += 1

    # ✅ patch_download_log → one row per file (22 files = 22 rows)
    for f in moved:
        file_path = os.path.join(final_dest, f)
        log_file_to_db(patch_id, ip, actual_package, latest_version,
                       file_path, "downloaded", now,
                       container_log=container_log_str)

    # ✅ patch_alert → ONLY ONE row per patch regardless of file count
    log_alert_to_db(agent_id, actual_package, msg, "DOWNLOADED")

    return "SUCCESS"


# =========================
# BACKGROUND WORKER
# Called by threading.Thread from routes.py
# =========================
def download_by_ubuntu_rows(rows, progress_store):
    """
    Entry point from routes.py background thread.
    ✅ Ubuntu (.deb) and RHEL (.rpm) auto detection.
    ✅ MAX_WORKERS=6 parallel downloads.
    ✅ ntop fix: wget always available, version URL, lsb-release+whiptail.
    ✅ patch_alert: ONE alert per patch, not per file.
    ✅ Refresh recovery via DB running log.
    """
    progress_store["status"] = "running"
    progress_store["failed"] = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}

        for row in rows:
            patch_id          = row[0]
            ip                = row[1]
            pkg               = row[2]
            installed_version = row[3]
            latest_version    = row[4]
            agent_id          = row[5]
            os_version        = row[6] if len(row) > 6 else "22.04"
            patch_type        = row[7] if len(row) > 7 else ""

            f = executor.submit(
                download_single_patch,
                patch_id, ip, os_version, pkg, patch_type,
                agent_id, latest_version, installed_version,
                progress_store
            )
            futures[f] = patch_id

        for future in as_completed(futures):
            pid = futures[future]
            try:
                result = future.result()
                print(f"✅ Patch {pid} — {result}")
            except Exception as e:
                print(f"❌ Patch {pid} exception: {e}")
                delete_running_log(pid)
                progress_store["items"][str(pid)].update({
                    "status"         : "failed",
                    "message"        : str(e),
                    "container_logs" : [f"❌ Exception: {str(e)}"]
                })
                progress_store["done"]   += 1
                progress_store["failed"] += 1

    progress_store["status"] = "completed"
    print(
        f"🎉 All done — "
        f"total: {progress_store['total']}, "
        f"done: {progress_store['done']}, "
        f"failed: {progress_store['failed']}"
    )
