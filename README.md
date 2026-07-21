# 🚀 NexusOSINT v12.2

<p align="center">
  <img src="https://img.shields.io/badge/Version-v12.2-blue?style=for-the-badge&logo=python" alt="Version">
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License">
  <img src="https://img.shields.io/badge/API_Keys-Zero_Required-orange?style=for-the-badge" alt="Zero API Keys">
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker">
</p>

<p align="center">
  <b>Production-Grade, Zero-API-Key OSINT & Reconnaissance Suite</b><br>
  An all-in-one automated tool for Email, Phone Number, Domain, and Username intelligence gathering.
</p>

---

## 📌 Table of Contents
- [Features](#-features)
- [Architecture & Modules](#-architecture--modules)
- [Quick Installation](#-quick-installation)
- [Usage Guide](#-usage-guide)
- [Docker Deployment](#-docker-deployment)
- [Output & Reports](#-output--reports)
- [License](#-license)
- [Disclaimer](#-disclaimer)

---

## 🔥 Features

- ⚡ **Zero API Keys Required:** Runs natively using DNS-over-HTTPS (DoH), crt.sh, and public endpoints without requiring paid API tokens.
- 🎯 **Smart Auto-Target Detection:** Automatically detects target input type (Email, Phone, Domain, Username) and triggers relevant scanners.
- 🚀 **High-Speed Multithreading:** Parallel execution engine for rapid subdomain discovery and web profile scraping.
- 📄 **Rich Multi-Format Exports:** Automatically formats footprinting results into JSON and HTML reports.
- 🐳 **Containerized & Portable:** Fully Dockerized for seamless deployment across Linux, WSL, and cloud terminals.

---

## 🧩 Architecture & Modules

| Module | Target Type | Operations / Sources |
| :--- | :--- | :--- |
| **Email Recon** | Email Address | MX record checks, Breach verification lookup, Provider analysis |
| **Phone Recon** | Phone Number | Carrier identification, Line type detection, Regional validation |
| **Domain Recon** | Domain / Subdomain | Subdomain enumeration via `crt.sh`, DoH resolution, HTTP banners |
| **User Recon** | Username | Social media & platform footprinting via WhatsMyName targets |

---

## 🛠️ Quick Installation

### Prerequisites
- Python 3.8+
- `pip` package manager

### Setup Commands
```bash
# Clone Repository
git clone [https://github.com/Nikhilbharti284/NexusOSINT.git](https://github.com/Nikhilbharti284/NexusOSINT.git)
cd NexusOSINT

# Install Required Dependencies
pip install -r requirements.txt
```

---

## 🚀 Usage Guide

`NexusOSINT` automatically detects the type of target passed to it:

```bash
# 1. Email Reconnaissance
python3 nexus.py target@example.com

# 2. Phone Number Investigation
python3 nexus.py +919876543210

# 3. Domain Footprinting & Subdomain Enumeration
python3 nexus.py example.com

# 4. Username Social Footprinting
python3 nexus.py username_007
```

---

## 🐳 Docker Deployment

Run NexusOSINT in an isolated container environment without installing dependencies locally:

```bash
# Build Docker Image
docker build -t nexusosint .

# Run Containerized Scan
docker run --rm nexusosint target@example.com
```

---

## 📊 Output & Reports

Scan results are formatted and automatically saved to the output directory:
* **JSON Report:** `reports/scan_result.json` (Ideal for scripting and automation pipelines)
* **HTML Report:** `reports/scan_result.html` (Interactive browser-friendly presentation)

---

## 📜 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for more information.

---

## ⚖️ Disclaimer

This tool is strictly intended for legal security research, authorized penetration testing, and educational purposes. Do not execute scans against unauthorized targets.