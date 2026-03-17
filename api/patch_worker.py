import requests
from bs4 import BeautifulSoup
import re
import json
import os
from tqdm import tqdm

from db import (
    update_patch_progress,
    update_patch_install_progress,
    get_db_connection
)

HEADERS = {"User-Agent": "Mozilla/5.0"}
BASE_URL = "https://catalog.update.microsoft.com"


# ================= ALERT =================
def insert_patch_alert(agent_id, kb, message, category):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO patch_alert (agent_id, kb, message, category)
        VALUES (%s, %s, %s, %s)
    """, (agent_id, kb, message, category))
    conn.commit()
    cur.close()
    conn.close()


# ================= DOWNLOAD =================
def download_file(agent_id, msu_url, file_path, kb, title):
    try:
        r = requests.get(msu_url, stream=True, timeout=60)
        r.raise_for_status()

        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        last_sent = -1

        # 🔹 Start state
        update_patch_progress(agent_id, title, kb, 0, "DOWNLOADING")
        update_patch_install_progress(agent_id, kb, 0, "DOWNLOADING")

        with open(file_path, "wb") as f, tqdm(
            total=total,
            unit="B",
            unit_scale=True,
            desc=kb
        ) as bar:

            for chunk in r.iter_content(chunk_size=8192):
                if not chunk:
                    continue

                f.write(chunk)
                size = len(chunk)
                downloaded += size
                bar.update(size)

                if total > 0:
                    percent = int((downloaded / total) * 100)

                    if percent != last_sent:
                        last_sent = percent

                        # 🔥 LIVE UPDATE BOTH TABLES
                        update_patch_progress(agent_id, title, kb, percent, "DOWNLOADING")
                        update_patch_install_progress(agent_id, kb, percent, "DOWNLOADING")

        # ================= SUCCESS =================
        update_patch_progress(agent_id, title, kb, 100, "DOWNLOADED")

        # install queue ready
        update_patch_install_progress(agent_id, kb, 0, "READY_TO_INSTALL")

        insert_patch_alert(agent_id, kb, f"{kb} download completed", "DOWNLOAD")

    except Exception as e:
        print("❌ Download failed:", e)

        # 🧹 Remove partial file
        if os.path.exists(file_path):
            os.remove(file_path)

        update_patch_progress(agent_id, title, kb, 0, "PENDING")
        update_patch_install_progress(agent_id, kb, 0, "PENDING")

        insert_patch_alert(
            agent_id,
            kb,
            f"{kb} could not download due to network issue",
            "FAIL_TO_DOWNLOAD"
        )


# ================= SEARCH + PROCESS =================
def process_patch(agent_id, patch_title):
    try:
        print(f"🔍 [{agent_id}] {patch_title}")

        resp = requests.get(
            f"{BASE_URL}/Search.aspx",
            params={"q": patch_title},
            headers=HEADERS
        )

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", id="ctl00_catalogBody_updateMatches")

        if not table:
            update_patch_progress(agent_id, patch_title, "", 0, "NOT_FOUND")
            return

        rows = table.find_all("tr")[1:]
        update_id = None
        kb_id = None

        for row in rows:
            cols = row.find_all("td")

            if len(cols) >= 2:
                title = cols[1].get_text(strip=True)
                kb_match = re.search(r"\((KB\d+)\)", title)
                if kb_match:
                    kb_id = kb_match.group(1)

            for tag in row.find_all(attrs={"onclick": True}):
                m = re.search(r"[a-f0-9\-]{36}", tag["onclick"])
                if m:
                    update_id = m.group(0)
                    break

            if update_id and kb_id:
                break

        if not update_id:
            update_patch_progress(agent_id, patch_title, "", 0, "FAILED")
            return

        payload = {
            "updateIDs": json.dumps([{
                "size": 0,
                "languages": "",
                "uidInfo": update_id,
                "updateID": update_id
            }])
        }

        resp = requests.post(
            f"{BASE_URL}/DownloadDialog.aspx",
            data=payload,
            headers=HEADERS
        )

        match = re.search(
            r"downloadInformation\[0\]\.files\[0\]\.url\s*=\s*'([^']+)'",
            resp.text
        )

        if not match:
            update_patch_progress(agent_id, patch_title, kb_id, 0, "FAILED")
            return

        msu_url = match.group(1)

        base_dir = os.path.join("downloads", agent_id, kb_id)
        os.makedirs(base_dir, exist_ok=True)

        filename = msu_url.split("/")[-1]
        file_path = os.path.join(base_dir, filename)

        # already downloaded
        if os.path.exists(file_path):
            update_patch_progress(agent_id, patch_title, kb_id, 100, "DOWNLOADED")
            update_patch_install_progress(agent_id, kb_id, 0, "READY_TO_INSTALL")
            return

        download_file(agent_id, msu_url, file_path, kb_id, patch_title)

    except Exception as e:
        print("🔥 Worker crash:", e)
        update_patch_progress(agent_id, patch_title, "", 0, "FAILED")