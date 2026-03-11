import os
import subprocess
import time
from db import get_db_connection

DOWNLOAD_DIR = "linux_patches"


# ===============================
# ENSURE DOWNLOAD DIRECTORY
# ===============================
def prepare_download_dir():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    try:
        os.chmod(DOWNLOAD_DIR, 0o755)
    except:
        pass

    try:
        subprocess.run(
            ["chown", "-R", "_apt:_apt", DOWNLOAD_DIR],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except:
        pass


prepare_download_dir()


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
# DOWNLOAD PATCH WITH RETRY
# ===============================
def download_patch(pkg, version):

    for attempt in range(3):

        try:
            print(f"Attempt {attempt+1}: apt download {pkg}={version}", flush=True)

            subprocess.run(
                ["apt", "download", f"{pkg}={version}"],
                cwd=DOWNLOAD_DIR,
                check=True
            )

            return "downloaded"

        except Exception:
            print("Download failed, retrying...", flush=True)

            # Refresh apt cache before retry
            refresh_apt_cache()

            time.sleep(5)

    return "failed"


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

    # Refresh apt once before starting downloads
    refresh_apt_cache()

    for row in rows:

        patch_id, ip, pkg = row[:3]

        status = "skipped"
        filepath = ""
        latest = None

        try:

            installed = get_installed_version(pkg)
            latest = get_latest_version(pkg)

            print("\n===================================", flush=True)
            print("Package :", pkg, flush=True)
            print("Installed :", installed, flush=True)
            print("Latest :", latest, flush=True)

            if not latest:
                status = "latest_not_found"
                print("Latest version not found", flush=True)

            elif installed == latest:
                status = "up_to_date"
                print("Already latest version", flush=True)

            else:
                status = download_patch(pkg, latest)

                if status == "downloaded":
                    print("Download SUCCESS", flush=True)
                else:
                    print("Download FAILED", flush=True)

            print("===================================", flush=True)

        except Exception as e:
            status = "error"
            print("Error:", e, flush=True)

        # ===============================
        # SAVE DOWNLOAD LOG
        # ===============================
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
