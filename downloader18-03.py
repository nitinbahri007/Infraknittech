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
    progress["items"] = {}

    # initialize
    for row in rows:
        progress["items"][row[0]] = "pending"

    for row in rows:
        patch_id, ip, pkg, version = row
        status = "failed"

        try:
            filename = f"{pkg}_{version}.deb".replace(":", "%3a")
            filepath = os.path.join("linux_patches", filename)

            if os.path.exists(filepath):
                status = "exists"
            else:
                url = build_url(pkg, version)
                r = requests.get(url, timeout=30)

                if r.status_code == 200:
                    with open(filepath, "wb") as f:
                        f.write(r.content)
                    status = "completed"

        except Exception as e:
            print("Error:", pkg, e)

        # 🔥 per-ID update
        progress["items"][patch_id] = status
        progress["done"] += 1

    progress["status"] = "completed"