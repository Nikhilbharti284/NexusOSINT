# 🚀 NexusOSINT v12.2

> **Production-Grade Zero-API-Key OSINT Suite**  
> Fast, multi-threaded information gathering tool for Email, Phone, Domain, and Username Reconnaissance.

---

## 🔥 Features

- ⚡ **Zero API Keys Required:** Uses public endpoints, DoH, crt.sh, and WhatsMyName targets seamlessly.
- 🎯 **Auto-Target Detection:** Automatically detects target input type (Email, Phone Number, Domain, Username).
- 🚀 **Multithreaded Scanning:** Rapid enumeration for domain subdomains and active web profiles.
- 📊 **Comprehensive Reporting:** Automatically generates JSON and HTML footprinting reports.

---

## 🛠️ Quick Installation

```bash
# Clone Repository
git clone [https://github.com/Nikhilbharti284/NexusOSINT.git](https://github.com/Nikhilbharti284/NexusOSINT.git)
cd NexusOSINT

# Install Dependencies
pip install -r requirements.txt
# Single Target Scan (Auto-Detects Target Type)
python3 nexus.py target@example.com
python3 nexus.py +919876543210
python3 nexus.py example.com
python3 nexus.py username_007
docker build -t nexusosint .
docker run --rm nexusosint target@example.com
