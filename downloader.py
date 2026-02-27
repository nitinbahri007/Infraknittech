import os
import requests
from db import get_db_connection

BASE_URL = "http://archive.ubuntu.com/ubuntu/pool/main"
DOWNLOAD_DIR = "linux_patches"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def build_url(pkg, version):
    first_letter = pkg[0]
    return f"{BASE_URL}/{first_letter}/{pkg}/{pkg}_{version}_amd64.deb"


def download_by_rows(rows, progress):
    conn = get_db_connection()
    cursor = conn.cursor()

    total = len(rows)
    progress["total"] = total
    progress["done"] = 0
    progress["status"] = "downloading"

    for row in rows:
        patch_id, ip, pkg, version = row
        status = "failed"
        filepath = ""

        try:
            filename = f"{pkg}_{version}.deb".replace(":", "%3a")
            filepath = os.path.join(DOWNLOAD_DIR, filename)

            if os.path.exists(filepath):
                status = "exists"
            else:
                url = build_url(pkg, version)
                r = requests.get(url, timeout=30)

                if r.status_code == 200:
                    with open(filepath, "wb") as f:
                        f.write(r.content)
                    status = "downloaded"

        except Exception as e:
            print("Error:", pkg, e)

        # ✅ SAVE DOWNLOAD LOG
        cursor.execute("""
            INSERT INTO patch_download_log
            (patch_id, ip_address, package_name, version, file_path, status)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (patch_id, ip, pkg, version, filepath, status))

        conn.commit()
        progress["done"] += 1

    cursor.close()
    conn.close()
    progress["status"] = "completed"