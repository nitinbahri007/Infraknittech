
                                #patch management
# Window
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
  "count": 5,
  "devices": [...]
}
```

---

## 2️⃣ Single Device Lookup

```
http://10.10.8.19:5000/api/devices?agent_id=082b88df-5f84-472d-abac-e5ebb5be3998
```

```json
{
  "count": 1,
  "devices": [
    {
      "agent_id": "082b88df-5f84-472d-abac-e5ebb5be3998",
      "hostname": "localhost.localdomain",
      "ip_address": "10.10.8.215",
      "os_name": "Red Hat Enterprise Linux",
      "status": "OFFLINE"
    }
  ]
}
```

---

## 3️⃣ Bulk Devices

```
http://10.10.8.19:5000/api/devices?agent_id=id1,id2,id3
```

```json
{
  "count": 3,
  "devices": [
    { "agent_id": "id1", "status": "ONLINE" },
    { "agent_id": "id2", "status": "OFFLINE" }
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
  "count": 2,
  "devices": [
    {
      "agent_id": "7e26d1a4-3609-4964-b56d-fed2a8560261",
      "hostname": "DESKTOP-P72C934",
      "status": "ONLINE"
    }
  ]
}
```

---

## 📦 Real Production Response

```json
{
  "count": 5,
  "devices": [
    {
      "agent_id": "082b88df-5f84-472d-abac-e5ebb5be3998",
      "agent_version": "1.0.0",
      "hostname": "localhost.localdomain",
      "id": 3,
      "ip_address": "10.10.8.215",
      "last_heartbeat": "Tue, 17 Feb 2026 06:03:22 GMT",
      "os_architecture": "x86_64",
      "os_name": "Red Hat Enterprise Linux",
      "os_version": "10.0 (Coughlan)",
      "status": "OFFLINE"
    }
  ]
}
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