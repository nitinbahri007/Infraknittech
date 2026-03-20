import os
import subprocess
import time
from db import get_db_connection

BASE_DIR = "linux_patches"


# ===============================
# CREATE IP DIRECTORY
# ===============================
def prepare_ip_dir(ip):

    ip_dir = os.path.join(BASE_DIR, str(ip))

    os.makedirs(ip_dir, exist_ok=True)

    try:
        os.chmod(ip_dir, 0o755)
    except:
        pass

    try:
        subprocess.run(
            ["chown", "-R", "_apt:_apt", ip_dir],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except:
        pass

    return ip_dir


# ===============================
# RUN APT CLEAN + UPDATE
# ===============================
def refresh_apt_cache():

    try:
        print("Running apt clean...", flush=True)

        subprocess.run(
            ["apt", "clean"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        print("Running apt update...", flush=True)

        subprocess.run(
            ["apt", "update"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    except Exception as e:
        print("APT refresh failed:", e, flush=True)


# ===============================
# GET INSTALLED VERSION
# ===============================
def get_installed_version(pkg):

    try:
        return subprocess.check_output(
            ["dpkg-query", "-W", "-f=${Version}", pkg],
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
    except:
        return None


# ===============================
# GET LATEST VERSION
# ===============================
def get_latest_version(pkg):

    try:
        output = subprocess.check_output(
            ["apt-cache", "policy", pkg],
            stderr=subprocess.DEVNULL,
            text=True
        )

        for line in output.split("\n"):
            if "Candidate:" in line:
                version = line.split(":", 1)[1].strip()
                if version != "(none)":
                    return version

    except:
        return None


# ===============================
# DOWNLOAD PATCH
# ===============================
def download_patch(pkg, version, ip_dir):

    filename = f"{pkg}_{version}.deb"
    filepath = os.path.join(ip_dir, filename)

    for attempt in range(3):

        try:
            print(f"Attempt {attempt+1}: apt download {pkg}={version}", flush=True)

            subprocess.run(
                ["apt", "download", f"{pkg}={version}"],
                cwd=ip_dir,
                check=True
            )

            return "downloaded", filepath

        except Exception:
            print("Download failed, retrying...", flush=True)
            refresh_apt_cache()
            time.sleep(5)

    return "failed", ""


# ===============================
# MAIN DOWNLOAD FUNCTION
# ===============================
def download_by_rows(rows, progress):

    conn = get_db_connection()
    cursor = conn.cursor()

    total = len(rows)

    progress["total"] = total
    progress["done"] = 0
    progress["status"] = "downloading"

    refresh_apt_cache()

    for row in rows:

        patch_id, ip, pkg = row[:3]

        status = "skipped"
        filepath = ""
        latest = None

        try:

            ip_dir = prepare_ip_dir(ip)

            installed = get_installed_version(pkg)
            latest = get_latest_version(pkg)

            print("\n===================================", flush=True)
            print("IP :", ip, flush=True)
            print("Package :", pkg, flush=True)
            print("Installed :", installed, flush=True)
            print("Latest :", latest, flush=True)

            if not latest:
                status = "latest_not_found"

            elif installed == latest:
                status = "up_to_date"

            else:

                status, filepath = download_patch(pkg, latest, ip_dir)

                if status == "downloaded":
                    print("Download SUCCESS", flush=True)
                else:
                    print("Download FAILED", flush=True)

            print("===================================", flush=True)

        except Exception as e:
            status = "error"
            print("Error:", e, flush=True)

        cursor.execute(
            """
            INSERT INTO patch_download_log
            (patch_id, ip_address, package_name, version, file_path, status)
            VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (patch_id, ip, pkg, latest, filepath, status)
        )

        conn.commit()

        progress["done"] += 1

    cursor.close()
    conn.close()

    progress["status"] = "completed"
