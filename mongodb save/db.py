# db.py

from pymongo import MongoClient
from datetime import datetime

MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "infra_patch_monitor"

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

# Collections
devices_col = db.devices
outages_col = db.outages
patch_logs_col = db.patch_scan_logs
patch_missing_col = db.patch_missing

# Indexes
devices_col.create_index("agent_id", unique=True)
patch_missing_col.create_index([("agent_id", 1), ("kb", 1)], unique=True)

# ================= FUNCTIONS =================

def get_all_devices():
    return [d["agent_id"] for d in devices_col.find({}, {"agent_id": 1})]

def update_device_status(agent_id, status):
    devices_col.update_one(
        {"agent_id": agent_id},
        {"$set": {
            "status": status,
            "updated_at": datetime.now()
        }}
    )

def start_outage(agent_id):
    outages_col.insert_one({
        "agent_id": agent_id,
        "start_time": datetime.now(),
        "end_time": None,
        "status": "OPEN"
    })

def end_outage(agent_id):
    outages_col.update_one(
        {"agent_id": agent_id, "status": "OPEN"},
        {"$set": {
            "end_time": datetime.now(),
            "status": "CLOSED"
        }}
    )