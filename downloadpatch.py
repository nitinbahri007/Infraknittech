import requests
from bs4 import BeautifulSoup
import re
import json
import sys
import os

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

BASE_URL = "https://catalog.update.microsoft.com"
SEARCH_TEXT = "2023-10 Servicing Stack Update for Windows 10 Version 22H2 for x64-based Systems"

# ================= STEP 1: SEARCH PAGE =================
print("\n================ STEP 1: SEARCH PAGE =================")

search_url = f"{BASE_URL}/Search.aspx"
resp = requests.get(search_url, params={"q": SEARCH_TEXT}, headers=HEADERS)

print("[+] HTTP Code:", resp.status_code)

if resp.status_code != 200:
    print("❌ Failed to load search page")
    sys.exit(1)

soup = BeautifulSoup(resp.text, "html.parser")

table = soup.find("table", id="ctl00_catalogBody_updateMatches")
if not table:
    print("❌ Update table not found")
    sys.exit(1)

rows = table.find_all("tr")[1:]
update_id = None
kb_id = None

for row in rows:
    cols = row.find_all("td")

    if len(cols) >= 2:
        title = cols[1].get_text(strip=True)
        print("Title:", title)

        # 🔥 KB number extract
        kb_match = re.search(r"\((KB\d+)\)", title)
        if kb_match:
            kb_id = kb_match.group(1)

    # 🔥 UpdateID extract
    for tag in row.find_all(attrs={"onclick": True}):
        m = re.search(
            r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",
            tag["onclick"]
        )
        if m:
            update_id = m.group(0)
            break

    if update_id and kb_id:
        print("✅ UpdateID:", update_id)
        print("✅ KB Folder:", kb_id)
        break

if not update_id or not kb_id:
    print("❌ UpdateID / KB not found")
    sys.exit(1)

# ================= STEP 2: DOWNLOAD DIALOG =================
print("\n================ STEP 2: DOWNLOAD DIALOG =================")

download_url = f"{BASE_URL}/DownloadDialog.aspx"

payload = {
    "updateIDs": json.dumps([{
        "size": 0,
        "languages": "",
        "uidInfo": update_id,
        "updateID": update_id
    }])
}

resp = requests.post(download_url, data=payload, headers=HEADERS)

if resp.status_code != 200:
    print("❌ Download dialog failed")
    sys.exit(1)

html = resp.text

# ================= STEP 3: EXTRACT MSU LINK =================
print("\n================ STEP 3: EXTRACT MSU LINK =================")

match = re.search(
    r"downloadInformation\[0\]\.files\[0\]\.url\s*=\s*'([^']+)'",
    html
)

if not match:
    print("❌ MSU link not found")
    sys.exit(1)

msu_url = match.group(1)
print("✅ MSU LINK FOUND:")
print(msu_url)

# ================= STEP 4: DOWNLOAD & SAVE =================
print("\n================ STEP 4: DOWNLOAD MSU =================")

# 🔥 Create KB folder
os.makedirs(kb_id, exist_ok=True)

filename = msu_url.split("/")[-1]
file_path = os.path.join(kb_id, filename)

print("⬇ Downloading to:", file_path)

r = requests.get(msu_url, stream=True)
r.raise_for_status()

total = int(r.headers.get("Content-Length", 0))
downloaded = 0

with open(file_path, "wb") as f:
    for chunk in r.iter_content(chunk_size=8192):
        if chunk:
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                percent = downloaded * 100 / total
                print(f"\r⬇ Downloading: {percent:.2f}%", end="")

print("\n\n✅ DOWNLOAD COMPLETE")
print("📁 Saved in folder:", kb_id)
print("📄 File:", file_path)

print("\n================ DONE =================")
s