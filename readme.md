# Developed by nitin bahri 
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
        │   Patch Management Server │
        │--------------------------│
        │ • Patch Repository        │
        │ • Scan Engine             │
        │ • Deployment Engine       │
        │ • API Layer               │
        └───────────┬──────────────┘
                    │
    ┌───────────────┼────────────────┐
    │               │                │
    ▼               ▼                ▼
| 🪟 Windows Node | 🐧 Ubuntu Node | 🟥 RHEL Node |
|----------------|---------------|-------------|
| No Internet<br>Agent-Based<br>Secure LAN | No Internet<br>Agent-Based<br>Secure LAN | No Internet<br>Agent-Based<br>Secure LAN |

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
| OS | Status | Documentation |
|----|--------|-------------|
| 🪟 Windows | ✅ Supported | ⭐ **[Windows API Docs](./readme-window-api.md)** |
| 🐧 Ubuntu | ✅ Supported |⭐ **[Ubuntu API Docs](./readme-ubuntu-api.md)** |
| 🟥 RHEL | ✅ Supported | ⭐ **[RHEL API Docs](./readme-redhat-api.md)** |
