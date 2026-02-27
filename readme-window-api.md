
# Window API DOCUMENTATION 
------------------------------------------------------------------------------
# 🖥 Devices API 

Retrieve registered agents/devices from the Patch Server.

Supports:

* Full inventory fetch
* Single device lookup
* Bulk device queries
* Status-based filtering

---

## 🔹 Endpoint

**GET** `/api/devices`

Base URL:

```
http://10.10.8.19:5000
```

---

## 📌 Query Parameters

| Key        | Type   | Required | Single / Multiple | Description                              |
| ---------- | ------ | -------- | ----------------- | ---------------------------------------- |
| agent_id   | string | ❌ No     | ✅ Single + Bulk   | Single UUID or comma-separated agent IDs |
| status     | string | ❌ No     | ✅ Single          | ONLINE / OFFLINE filter                  |
| hostname   | string | ❌ No     | ✅ Single + Bulk   | Supports comma-separated hostnames       |
| ip_address | string | ❌ No     | ✅ Single + Bulk   | Supports comma-separated IP addresses    |



> ℹ️ All query parameters are optional.
> If no filters are provided, the API returns all registered devices.
> Bulk queries use comma-separated values.
> Example: `?agent_id=id1,id2,id3`

---

# 🧪 Postman Examples

---

## 1️⃣ Get All Devices

**GET**

```
http://10.10.8.19:5000/api/devices
```

**Response**

```json
{
count: 4,
devices: [
{
agent_id: "082b88df-5f84-472d-abac-e5ebb5be3998",
agent_version: "1.0.0",
hostname: "localhost.localdomain",
id: 3,
ip_address: "10.10.8.215",
last_heartbeat: "Tue, 17 Feb 2026 06:03:22 GMT",
last_seen: "Tue, 17 Feb 2026 06:03:22 GMT",
os_architecture: "x86_64",
os_name: "Red Hat Enterprise Linux",
os_version: "10.0 (Coughlan)",
status: "OFFLINE",
updated_at: "Tue, 24 Feb 2026 16:16:56 GMT"
},
{
agent_id: "7e26d1a4-3609-4964-b56d-fed2a8560261",
agent_version: "1.0",
hostname: "DESKTOP-P72C934",
id: 533,
ip_address: "10.10.10.247",
last_heartbeat: "Tue, 17 Feb 2026 23:37:01 GMT",
last_seen: "Tue, 17 Feb 2026 17:25:18 GMT",
os_architecture: "AMD64",
os_name: "Windows",
os_version: "10.0.19045",
status: "OFFLINE",
updated_at: "Tue, 24 Feb 2026 16:16:56 GMT"
},
{
agent_id: "61c3c6ea-cbfa-4813-b329-ddbcc13b35c8",
agent_version: "1.0",
hostname: "Nitin-android",
id: 2073,
ip_address: "10.10.8.19",
last_heartbeat: "Fri, 20 Feb 2026 13:06:15 GMT",
last_seen: "Fri, 20 Feb 2026 12:57:38 GMT",
os_architecture: "AMD64",
os_name: "Windows",
os_version: "10.0.19045",
status: "OFFLINE",
updated_at: "Tue, 24 Feb 2026 16:16:56 GMT"
},
{
agent_id: "3ba1b11e-6393-4e22-956b-1837aa5f3282",
agent_version: "1.0",
hostname: "DESKTOP-B1I444V",
id: 11573,
ip_address: "10.10.11.10",
last_heartbeat: "Fri, 27 Feb 2026 16:36:33 GMT",
last_seen: null,
os_architecture: "AMD64",
os_name: "Windows",
os_version: "10.0.19045",
status: "ONLINE",
updated_at: "Fri, 27 Feb 2026 16:36:33 GMT"
}
]
}
```

---

## 2️⃣ Single Device Lookup

```
http://10.10.8.19:5000/api/devices?agent_id=3ba1b11e-6393-4e22-956b-1837aa5f3282
```

```json
{
  "count": 1,
  "devices": [
    {
      "agent_id": "3ba1b11e-6393-4e22-956b-1837aa5f3282",
      "agent_version": "1.0",
      "hostname": "DESKTOP-B1I444V",
      "id": 11573,
      "ip_address": "10.10.11.10",
      "last_heartbeat": "Fri, 27 Feb 2026 16:08:00 GMT",
      "last_seen": null,
      "os_architecture": "AMD64",
      "os_name": "Windows",
      "os_version": "10.0.19045",
      "status": "ONLINE",
      "updated_at": "Fri, 27 Feb 2026 16:08:00 GMT"
    }
  ]
}
```

---

## 3️⃣ Bulk Devices agent wise 

```
http://10.10.8.19:5000/api/devices?agent_id=3ba1b11e-6393-4e22-956b-1837aa5f3282,61c3c6ea-cbfa-4813-b329-ddbcc13b35c8
```

```json
{
  "count": 2,
  "devices": [
    {
      "agent_id": "3ba1b11e-6393-4e22-956b-1837aa5f3282",
      "agent_version": "1.0",
      "hostname": "DESKTOP-B1I444V",
      "id": 11573,
      "ip_address": "10.10.11.10",
      "last_heartbeat": "Fri, 27 Feb 2026 16:09:30 GMT",
      "last_seen": null,
      "os_architecture": "AMD64",
      "os_name": "Windows",
      "os_version": "10.0.19045",
      "status": "ONLINE",
      "updated_at": "Fri, 27 Feb 2026 16:09:30 GMT"
    },
    {
      "agent_id": "61c3c6ea-cbfa-4813-b329-ddbcc13b35c8",
      "agent_version": "1.0",
      "hostname": "Nitin-android",
      "id": 2073,
      "ip_address": "10.10.8.19",
      "last_heartbeat": "Fri, 20 Feb 2026 13:06:15 GMT",
      "last_seen": "Fri, 20 Feb 2026 12:57:38 GMT",
      "os_architecture": "AMD64",
      "os_name": "Windows",
      "os_version": "10.0.19045",
      "status": "OFFLINE",
      "updated_at": "Tue, 24 Feb 2026 16:16:56 GMT"
    }
  ]
}
```

---

## 4️⃣ Filter by Status

```
http://10.10.8.19:5000/api/devices?status=ONLINE
```

```json
{
  "count": 1,
  "devices": [
    {
      "agent_id": "3ba1b11e-6393-4e22-956b-1837aa5f3282",
      "agent_version": "1.0",
      "hostname": "DESKTOP-B1I444V",
      "id": 11573,
      "ip_address": "10.10.11.10",
      "last_heartbeat": "Fri, 27 Feb 2026 16:10:30 GMT",
      "last_seen": null,
      "os_architecture": "AMD64",
      "os_name": "Windows",
      "os_version": "10.0.19045",
      "status": "ONLINE",
      "updated_at": "Fri, 27 Feb 2026 16:10:30 GMT"
    }
  ]
}
```
## 3️⃣ Bulk Devices ip address wise 


---

# 📦 Window missing patch listing 

**GET** `/api/window-patch-missing`

## 1️⃣ Get All  Window Missing Patches
```
http://10.10.8.19:5000/api/window-patch-missing

```

```json
{
  "count": 3,
  "patch_missing": [
    {
      "agent_id": "7e26d1a4-3609-4964-b56d-fed2a8560261",
      "deploy_status": false,
      "detected_at": "Tue, 17 Feb 2026 17:25:17 GMT",
      "download_status": false,
      "hostname": "DESKTOP-P72C934",
      "id": 1,
      "ip_address": "10.10.10.247",
      "kb": "5031539",
      "patch_id": null,
      "patch_title": "2023-10 Servicing Stack Update for Windows 10 Version 22H2 for x64-based Systems (KB5031539)",
      "severity": "Critical"
    },
    {
      "agent_id": "7e26d1a4-3609-4964-b56d-fed2a8560261",
      "deploy_status": false,
      "detected_at": "Tue, 17 Feb 2026 17:25:17 GMT",
      "download_status": false,
      "hostname": "DESKTOP-P72C934",
      "id": 2,
      "ip_address": "10.10.10.247",
      "kb": "5066791",
      "patch_id": null,
      "patch_title": "2025-10 Cumulative Update for Windows 10 Version 22H2 for x64-based Systems (KB5066791)",
      "severity": "Critical"
    },
    {
      "agent_id": "3ba1b11e-6393-4e22-956b-1837aa5f3282",
      "deploy_status": false,
      "detected_at": "Wed, 18 Feb 2026 13:27:32 GMT",
      "download_status": false,
      "hostname": "DESKTOP-B1I444V",
      "id": 5,
      "ip_address": "10.10.11.10",
      "kb": "5031539",
      "patch_id": null,
      "patch_title": "2023-10 Servicing Stack Update for Windows 10 Version 22H2 for x64-based Systems (KB5031539)",
      "severity": "Critical"
    }
  ]
}
```

## 📌 Query Parameters

| Key        | Type   | Required | Single / Multiple | Description |
|------------|--------|----------|------------------|-------------|
| agent_id   | string | ❌ No | ✅ Single + Bulk | Single UUID or comma-separated agent IDs |
| severity   | string | ❌ No | ✅ Single + Bulk | Patch severity (Critical, Important, Optional) |
| kb         | string | ❌ No | ✅ Single + Bulk | Filter by KB numbers (e.g. KB5021234) |
| hostname   | string | ❌ No | ✅ Single + Bulk | Supports comma-separated hostnames |
| ip_address | string | ❌ No | ✅ Single + Bulk | Supports comma-separated IP addresses |


## 1️⃣ Get Missing Patches list by agent id 

```
http://10.10.8.19:5000/api/window-patch-missing?agent_id=7e26d1a4-3609-4964-b56d-fed2a8560261
```
```json
{
  "count": 2,
  "patch_missing": [
    {
      "agent_id": "7e26d1a4-3609-4964-b56d-fed2a8560261",
      "deploy_status": false,
      "detected_at": "Tue, 17 Feb 2026 17:25:17 GMT",
      "download_status": false,
      "hostname": "DESKTOP-P72C934",
      "id": 1,
      "ip_address": "10.10.10.247",
      "kb": "5031539",
      "patch_id": null,
      "patch_title": "2023-10 Servicing Stack Update for Windows 10 Version 22H2 for x64-based Systems (KB5031539)",
      "severity": "Critical"
    },
    {
      "agent_id": "7e26d1a4-3609-4964-b56d-fed2a8560261",
      "deploy_status": false,
      "detected_at": "Tue, 17 Feb 2026 17:25:17 GMT",
      "download_status": false,
      "hostname": "DESKTOP-P72C934",
      "id": 2,
      "ip_address": "10.10.10.247",
      "kb": "5066791",
      "patch_id": null,
      "patch_title": "2025-10 Cumulative Update for Windows 10 Version 22H2 for x64-based Systems (KB5066791)",
      "severity": "Critical"
    }
  ]
}
```
## 2️⃣  Get Missing Patches list by multiple agent id (comma seprated) 
```
http://10.10.8.19:5000/api/window-patch-missing?agent_id=7e26d1a4-3609-4964-b56d-fed2a8560261,3ba1b11e-6393-4e22-956b-1837aa5f3282
```

```json
{"count":6,"patch_missing":[{"agent_id":"7e26d1a4-3609-4964-b56d-fed2a8560261","deploy_status":false,"detected_at":"Tue, 17 Feb 2026 17:25:17 GMT","download_status":false,"hostname":"DESKTOP-P72C934","id":1,"ip_address":"10.10.10.247","kb":"5031539","patch_id":null,"patch_title":"2023-10 Servicing Stack Update for Windows 10 Version 22H2 for x64-based Systems (KB5031539)","severity":"Critical"},{"agent_id":"7e26d1a4-3609-4964-b56d-fed2a8560261","deploy_status":false,"detected_at":"Tue, 17 Feb 2026 17:25:17 GMT","download_status":false,"hostname":"DESKTOP-P72C934","id":2,"ip_address":"10.10.10.247","kb":"5066791","patch_id":null,"patch_title":"2025-10 Cumulative Update for Windows 10 Version 22H2 for x64-based Systems (KB5066791)","severity":"Critical"},{"agent_id":"3ba1b11e-6393-4e22-956b-1837aa5f3282","deploy_status":false,"detected_at":"Wed, 18 Feb 2026 13:27:32 GMT","download_status":false,"hostname":"DESKTOP-B1I444V","id":5,"ip_address":"10.10.11.10","kb":"5031539","patch_id":null,"patch_title":"2023-10 Servicing Stack Update for Windows 10 Version 22H2 for x64-based Systems (KB5031539)","severity":"Critical"},{"agent_id":"3ba1b11e-6393-4e22-956b-1837aa5f3282","deploy_status":false,"detected_at":"Wed, 18 Feb 2026 13:27:32 GMT","download_status":false,"hostname":"DESKTOP-B1I444V","id":6,"ip_address":"10.10.11.10","kb":"5066747","patch_id":null,"patch_title":"2025-10 Cumulative Update for .NET Framework 3.5, 4.8 and 4.8.1 for Windows 10 Version 22H2 for x64 (KB5066747)","severity":"Important"},{"agent_id":"3ba1b11e-6393-4e22-956b-1837aa5f3282","deploy_status":false,"detected_at":"Wed, 18 Feb 2026 13:27:32 GMT","download_status":false,"hostname":"DESKTOP-B1I444V","id":7,"ip_address":"10.10.11.10","kb":"5066791","patch_id":null,"patch_title":"2025-10 Cumulative Update for Windows 10 Version 22H2 for x64-based Systems (KB5066791)","severity":"Critical"},{"agent_id":"3ba1b11e-6393-4e22-956b-1837aa5f3282","deploy_status":false,"detected_at":"Wed, 18 Feb 2026 13:27:32 GMT","download_status":false,"hostname":"DESKTOP-B1I444V","id":8,"ip_address":"10.10.11.10","kb":"890830","patch_id":null,"patch_title":"Windows Malicious Software Removal Tool x64 - v5.138 (KB890830)","severity":"NotRated"}]}
```




---
---

## ✅ Common Usage

| Scenario           | Query            |
| ------------------ | ---------------- |
| Inventory          | `/api/devices`   |
| Agent debug        | `?agent_id=`     |
| Live monitoring    | `?status=ONLINE` |
| Multi-node compare | Bulk agent IDs   |