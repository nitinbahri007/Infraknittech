import os
import subprocess
import requests
from db import get_db_connection

DOWNLOAD_DIR = "linux_patches"
BASE_URL = "http://archive.ubuntu.com/ubuntu/pool/main"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# ===============================
# GET INSTALLED VERSION
# ===============================
def get_installed_version(pkg):

    try:

        result = subprocess.check_output(
            ["dpkg-query", "-W", "-f=${Version}", pkg],
            stderr=subprocess.DEVNULL
        ).decode().strip()

        return result

    except:

        return None


# ===============================
# GET LATEST VERSION
# ===============================
def get_latest_version(pkg):

    try:

        result = subprocess.check_output(
            ["apt-cache", "policy", pkg]
        ).decode()

        for line in result.split("\n"):

            if "Candidate:" in line:

                return line.split(":")[1].strip()

    except:

        return None


# ===============================
# BUILD DOWNLOAD URL
# ===============================
def build_url(pkg, version):

    first_letter = pkg[0]

    version = version.replace(":", "%3a")

    return f"{BASE_URL}/{first_letter}/{pkg}/{pkg}_{version}_amd64.deb"


# ===============================
# DOWNLOAD PATCH
# ===============================
def download_by_rows(rows, progress):

    conn = get_db_connection()
    cursor = conn.cursor()

    total = len(rows)

    progress["total"] = total
    progress["done"] = 0
    progress["status"] = "downloading"

    for row in rows:

        patch_id, ip, pkg = row[:3]

        status = "skipped"
        filepath = ""
        latest_version = None

        try:

            installed_version = get_installed_version(pkg)
            latest_version = get_latest_version(pkg)

            print("\n===================================", flush=True)
            print("Package :", pkg, flush=True)
            print("Installed :", installed_version, flush=True)
            print("Latest :", latest_version, flush=True)

            if not installed_version or not latest_version:

                print("Version detect failed", flush=True)
                status = "version_not_found"

            elif installed_version == latest_version:

                print("Already latest → skip", flush=True)
                status = "up_to_date"

            else:

                url = build_url(pkg, latest_version)

                filename = f"{pkg}_{latest_version}.deb".replace(":", "%3a")

                filepath = os.path.join(DOWNLOAD_DIR, filename)

                print("Download URL :", url, flush=True)

                if os.path.exists(filepath):

                    status = "exists"
                    print("File already downloaded", flush=True)

                else:

                    r = requests.get(url, timeout=120)

                    if r.status_code == 200:

                        with open(filepath, "wb") as f:
                            f.write(r.content)

                        status = "downloaded"
                        print("Download SUCCESS", flush=True)

                    else:

                        status = f"http_{r.status_code}"
                        print("Download FAILED:", r.status_code, flush=True)

            print("===================================", flush=True)

        except Exception as e:

            status = "error"

            print("Error:", e, flush=True)

        # ===============================
        # SAVE DOWNLOAD LOG
        # ===============================
        cursor.execute("""

            INSERT INTO patch_download_log
            (patch_id, ip_address, package_name, version, file_path, status)

            VALUES (%s,%s,%s,%s,%s,%s)

        """, (patch_id, ip, pkg, latest_version, filepath, status))

        conn.commit()

        progress["done"] += 1

    cursor.close()
    conn.close()

    progress["status"] = "completed"
