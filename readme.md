# 📦 Patch Management API

A lightweight Patch Management backend for managing **Windows, Red Hat (RHEL), and Ubuntu agents, devices, and updates**.

Built for enterprise environments like **SOC, NOC, data centers, and infrastructure automation platforms**, enabling centralized patch visibility and control across heterogeneous operating systems.

# 🏗 How It Works (Architecture)

The Patch Management system follows a **centralized architecture** where all intelligence resides on the server, while nodes (agents) operate in controlled environments.

---

## 🔧 Architecture Overview
         🌐 Internet Access (Required Only Here)
                    │
                    ▼
        ┌──────────────────────────┐
        │   Patch Management Server│
        │--------------------------│
        │ • Patch Repository       │
        │ • Scan Engine            │
        │ • Deployment Engine      │
        │ • API Layer              │
        └───────────┬──────────────┘
                    │
   ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│ 🪟 Windows │ │ 🐧 Ubuntu │ │ 🟥 RHEL │
│ Nodes │ │ Nodes │ │ Nodes │
│───────────────│ │───────────────│ │───────────────│
│ No Internet │ │ No Internet │ │ No Internet │
│ Agent-Based │ │ Agent-Based │ │ Agent-Based │
│ Secure LAN │ │ Secure LAN │ │ Secure LAN │
└───────────────┘ └───────────────┘ └───────────────┘

## ⚙ How It Works

### 1️⃣ Central Server (Internet Required)
The Patch Management Server is the brain of the system.

**Responsibilities:**
- Fetch patches from internet repositories
- Maintain patch cache
- Scan devices for missing updates
- Deploy patches to nodes
- Provide REST APIs

**Supported repositories:**
- Microsoft Update Catalog
- Ubuntu APT repositories
- RHEL YUM/DNF repositories

---

### 2️⃣ Nodes / Agents (No Internet Required)
Endpoints do **NOT require internet access**.

**Supported nodes:**
- Windows Servers / Desktops
- Ubuntu Linux
- Red Hat Enterprise Linux

**Node responsibilities:**
- Register with server
- Report patch status
- Receive deployment commands
- Install patches locally
---

## 🚀 Core Capabilities

This platform provides end-to-end patch lifecycle management across multiple operating systems.

---

### ✅ Device Inventory
- Pull all registered agents/devices
- Multi-OS support (Windows, Ubuntu, RHEL)
- Online / Offline visibility
- UUID-based tracking

---

### 🔍 Missing Patch Detection
- Detect missing patches on a specific device
- OS-aware patch scanning:
  - Windows → KB updates
  - Ubuntu → APT packages
  - RHEL → YUM/DNF advisories
- Severity tagging (Critical / Important / Optional)

---

### 📥 Patch Download
- Download patches to central repository
- OS-specific handling:
  - Windows → KB packages
  - Ubuntu → APT mirrors
  - RHEL → RPM repositories
- Patch caching for reuse

---

### 🚀 Patch Deployment
Deploy patches to a specific device or group.

Supported operations:
- Single device deployment
- Bulk deployment
- OS-aware execution:
  - Windows → PowerShell / WUSA
  - Ubuntu → APT automation
  - RHEL → YUM/DNF automation

---

## 🖥 Supported Operating Systems

| OS | Status |
|----|--------|
| Windows Server / Desktop | ✅ Supported |
| Ubuntu 18+ / 20+ / 22+ | ✅ Supported |
| Red Hat Enterprise Linux | ✅ Supported |
| Rocky / AlmaLinux | 🔜 Planned |

---

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