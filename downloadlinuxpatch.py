import os
import requests
from db import get_db_connection

# ===============================
# CONFIG
# ===============================
DOWNLOAD_DIR = "linux_patches"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

BASE_URL = "http://archive.ubuntu.com/ubuntu/pool/main"

# ===============================
# DB READ
# ===============================
conn = get_db_connection()
cursor = conn.cursor()

cursor.execute("""
SELECT package_name, latest_version
FROM linux_patches
WHERE patch_type = 'outdated' and id=20;
""")

rows = cursor.fetchall()
conn.close()

print(f"Found {len(rows)} patches")

# ===============================
# DOWNLOAD FUNCTION
# ===============================
def build_url(pkg, version):
    first_letter = pkg[0]
    return f"{BASE_URL}/{first_letter}/{pkg}/{pkg}_{version}_amd64.deb"

# ===============================
# DOWNLOAD LOOP
# ===============================
for pkg, version in rows:
    try:
        filename = f"{pkg}_{version}.deb".replace(":", "%3a")
        filepath = os.path.join(DOWNLOAD_DIR, filename)

        if os.path.exists(filepath):
            print("✔ Already exists:", filename)
            continue

        url = build_url(pkg, version)
        print("⬇ Downloading:", pkg)

        r = requests.get(url, timeout=30)

        if r.status_code == 200:
            with open(filepath, "wb") as f:
                f.write(r.content)
            print("✅ Saved:", filename)
        else:
            print("❌ Not found:", pkg)

    except Exception as e:
        print("⚠ Error:", pkg, str(e))

print("\n🎉 Done! Patches stored in:", DOWNLOAD_DIR)