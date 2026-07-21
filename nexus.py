#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NexusOSINT v12.2 – Production‑Grade Free OSINT Without API Keys            ║
║  Email/Phone/Domain/Username Auto‑Detect | Live Subdomains | Quiet Mode    ║
║  This tool is for educational & authorized security auditing only.          ║
║  Made by Nikhil                                                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
import argparse, concurrent.futures, csv, hashlib, json, logging, os, random, re, socket, sys, threading, time, urllib.parse
from datetime import datetime, timezone
from collections import defaultdict

# Suppress noisy urllib3 warnings (e.g., from dead endpoints)
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.getLogger("urllib3").setLevel(logging.ERROR)

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    import phonenumbers
    from phonenumbers import carrier, geocoder, timezone as pn_timezone
    from tabulate import tabulate
    from colorama import init, Fore, Style
    from bs4 import BeautifulSoup
    from fake_useragent import UserAgent
    from tqdm import tqdm
    init(autoreset=True)
except ImportError:
    sys.exit("[!] Install: pip3 install requests phonenumbers tabulate colorama beautifulsoup4 fake-useragent truecallerpy tqdm")

try: from truecallerpy import search_phonenumber; TC_OK = True
except: TC_OK = False

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------
TIMEOUT = 8; MAX_WORKERS = 20
lock = threading.Lock(); req_counter = 0; findings = []
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.I)
PHONE_EXTRACT_RE = re.compile(r"(?:\+?91[\s\-]?)?[6-9]\d{9}|\+\d{7,15}")
PHONE_VALID_RE = re.compile(r"^(?:\+?91[\s\-]?)?[6-9]\d{9}$")
DOMAIN_RE = re.compile(r"^(?!\-)(?:[a-zA-Z0-9\-]{1,63}\.)+[a-zA-Z]{2,}$")
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_\.\-]{3,30}$")
ua = UserAgent()
logging.basicConfig(level=logging.WARNING)
QUIET = False

# Public email domains that we should NOT run heavy domain scans on
COMMON_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
                  "icloud.com", "protonmail.com", "proton.me", "aol.com", "zoho.com"}

def tprint(msg, **kwargs):
    """Print only if not quiet mode. Force stdout flush."""
    if not QUIET:
        tqdm.write(msg, **kwargs)

# ------------------------------------------------------------
# PROXY ROTATOR (only used if --proxy flag is set)
# ------------------------------------------------------------
class ProxyRotator:
    SOURCES = [
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=all",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
        "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt",
    ]
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.proxies = []; self.bad = set(); self.idx = 0
        if enabled: self.refresh()
    def refresh(self):
        tprint(Fore.YELLOW + "[*] Fetching free proxies...")
        found = set()
        for url in self.SOURCES:
            try:
                r = requests.get(url, timeout=8, headers={"User-Agent": ua.random})
                if r.status_code != 200: continue
                for line in r.text.splitlines():
                    m = re.match(r"^(\d{1,3}(?:\.\d{1,3}){3}:\d{2,5})$", line.strip())
                    if m: found.add(m.group(1))
            except: pass
        candidates = list(found); random.shuffle(candidates)
        good = []
        def test(p):
            try:
                px = {"http": f"http://{p}", "https": f"http://{p}"}
                r = requests.get("https://httpbin.org/ip", proxies=px, timeout=5)
                if r.status_code == 200: return p
            except: pass
        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
            for res in ex.map(test, candidates[:120]):
                if res: good.append(res)
                if len(good) >= 25: break
        self.proxies = good if good else candidates[:50]
        tprint(Fore.GREEN + f"[+] {len(self.proxies)} live proxies")
    def next(self):
        if not self.enabled or not self.proxies: return None
        with lock:
            for _ in range(len(self.proxies)):
                p = self.proxies[self.idx % len(self.proxies)]; self.idx += 1
                if p not in self.bad: return {"http": f"http://{p}", "https": f"http://{p}"}
            self.bad.clear(); return {"http": f"http://{p}", "https": f"http://{p}"}
    def mark_bad(self, px):
        if px:
            h = px.get("http", "").replace("http://", "")
            with lock: self.bad.add(h)

PROXY = None

def make_session():
    s = requests.Session()
    retry = Retry(total=2, backoff_factor=0.4, status_forcelist=[429,500,502,503,504])
    s.mount("https://", HTTPAdapter(max_retries=retry)); s.mount("http://", HTTPAdapter(max_retries=retry))
    return s

def safe_request(method, url, session=None, use_proxy=False, tor_ok=False, **kwargs):
    global req_counter
    sess = session or make_session()
    kwargs.setdefault("timeout", TIMEOUT); kwargs.setdefault("allow_redirects", True)
    headers = kwargs.pop("headers", {})
    headers.setdefault("User-Agent", ua.random)
    proxies = None
    if tor_ok and ".onion" in url: proxies = {"http": "socks5h://127.0.0.1:9050", "https": "socks5h://127.0.0.1:9050"}
    elif use_proxy and PROXY is not None and PROXY.enabled: proxies = PROXY.next()
    time.sleep(random.uniform(0.5, 1.5))
    for _ in range(3):
        try:
            with lock: req_counter += 1
            r = sess.request(method, url, headers=headers, proxies=proxies, **kwargs)
            if r.status_code in (403,429,503) and proxies and not tor_ok:
                PROXY.mark_bad(proxies); proxies = PROXY.next()
                time.sleep(random.uniform(1,2))
                continue
            return r
        except Exception as e:
            logging.debug(f"Request failed: {e}")
            if proxies and not tor_ok: PROXY.mark_bad(proxies); proxies = PROXY.next()
            time.sleep(random.uniform(1,2))
    return None

def extract_emails(text):
    if not text: return []
    out = []; skip = ("example.com","domain.com","sentry.io","wixpress")
    for e in EMAIL_RE.findall(text.lower()):
        if not any(s in e for s in skip): out.append(e.strip(".,;\"'<> "))
    return list(set(out))

def add_finding(kind, value, source, confidence="medium", extra=None):
    with lock:
        findings.append({
            "type": kind, "value": value, "source": source,
            "confidence": confidence, "extra": extra or {},
            "ts": datetime.now(timezone.utc).isoformat()
        })

def is_tor_running():
    try:
        r = safe_request("GET", "http://check.torproject.org", tor_ok=True, use_proxy=False)
        return r and "Congratulations" in r.text
    except: return False

# ------------------------------------------------------------
# TARGET TYPE DETECTOR
# ------------------------------------------------------------
def detect_input_type(target):
    """Return: 'email', 'phone', 'domain', 'username'"""
    target = target.strip().lower()
    if EMAIL_RE.search(target):
        return "email"
    normalized = target.replace("+91","").replace(" ","").replace("-","").strip()
    if normalized.startswith("+") and normalized[1:].isdigit():
        normalized = normalized[1:]
    if PHONE_VALID_RE.match(normalized):
        return "phone"
    if DOMAIN_RE.match(target):
        return "domain"
    if USERNAME_RE.match(target):
        return "username"
    return "domain"

# ------------------------------------------------------------
# MODULES (broken endpoints turned into stubs)
# ------------------------------------------------------------
WMM_JSON_URL = "https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/web_accounts_list.json"
WMM_CACHE = "web_accounts_list.json"

def load_whatsmyname():
    if os.path.exists(WMM_CACHE):
        with open(WMM_CACHE, "r") as f: return json.load(f)
    try:
        r = requests.get(WMM_JSON_URL, timeout=15, headers={"User-Agent": ua.random})
        if r.status_code == 200:
            data = r.json()
            with open(WMM_CACHE, "w") as f: json.dump(data, f)
            return data
    except: pass
    return None

def check_username(username, full_scan=False):
    data = load_whatsmyname()
    if not data:
        add_finding("WhatsMyName", "Could not load sites JSON", "WhatsMyName", "low")
        return
    sites = data.get("sites", [])
    if not full_scan: sites = sites[:100]
    tprint(Fore.CYAN + f"[*] Checking username '{username}' on {len(sites)} sites...")
    def test_site(site):
        try:
            url = site["uri_check"].replace("{account}", username)
            r = safe_request("GET", url, use_proxy=False, allow_redirects=True)
            if r and r.status_code == 200 and site.get("e_code", "404") not in r.text:
                add_finding("Profile Found", url, site["name"], "medium", {"username": username})
        except: pass
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
        ex.map(test_site, sites)

# Dead endpoints – return immediately to avoid retries and warnings
def search_psbdmp(query, session=None):
    return  # psbdmp.ws is offline
def darksearch(query, session=None):
    return  # darksearch.io is offline

# Rest of the modules unchanged (except we comment out darksearch/psbdmp from task lists)
def ip_intelligence(ip, session=None):
    for url in [f"http://ip-api.com/json/{ip}", f"https://ipwhois.app/json/{ip}"]:
        r = safe_request("GET", url, use_proxy=False, session=session)
        if r and r.status_code == 200:
            try:
                data = r.json()
                add_finding("IP Info", f"{data.get('city','')} {data.get('country','')}", "ip-api/ipwhois", "high", data)
            except: pass

def dns_lookup(domain, session=None):
    for rtype in ["A", "MX", "TXT"]:
        url = f"https://dns.google/resolve?name={urllib.parse.quote(domain)}&type={rtype}"
        r = safe_request("GET", url, use_proxy=False, session=session)
        if r and r.status_code == 200:
            try:
                data = r.json()
                for ans in data.get("Answer", []):
                    add_finding(f"DNS {rtype}", ans.get("data", ""), "dns.google", "medium")
            except: pass

def firefox_monitor(email, session=None):
    try:
        r = safe_request("GET", f"https://monitor.firefox.com/api/v1/scan/{urllib.parse.quote(email)}", use_proxy=False, session=session)
        if r and r.status_code == 200:
            data = r.json()
            if data.get("breaches"): add_finding("Firefox Monitor", f"{len(data['breaches'])} breaches found", "Firefox Monitor", "high")
            else: add_finding("Firefox Monitor", "No breaches found", "Firefox Monitor", "info")
    except: pass

def breachdirectory_scrape(email, session=None):
    try:
        r = safe_request("POST", "https://breachdirectory.org/check", data={"email": email}, use_proxy=False, session=session)
        if r and "found" in r.text.lower(): add_finding("BreachDirectory", "Data found", "BreachDirectory", "medium")
    except: pass

WAP_JSON = "https://raw.githubusercontent.com/AliasIO/wappalyzer/master/src/technologies.json"
def load_wappalyzer():
    if os.path.exists("technologies.json"):
        with open("technologies.json", "r") as f: return json.load(f)
    try:
        r = requests.get(WAP_JSON, timeout=15, headers={"User-Agent": ua.random})
        if r.status_code == 200:
            data = r.json()
            with open("technologies.json", "w") as f: json.dump(data, f)
            return data
    except: pass
    return {}

def detect_tech(url, session=None):
    r = safe_request("GET", url, session=session)
    if not r: return
    soup = BeautifulSoup(r.text, "html.parser")
    meta_tags = {m.get("name","").lower(): m.get("content","") for m in soup.find_all("meta")}
    techs = load_wappalyzer()
    found = set()
    for name, tech in techs.items():
        for pattern in tech.get("html", []):
            if re.search(pattern, r.text): found.add(name); break
        for pattern in tech.get("headers", {}).values():
            for h, v in r.headers.items():
                if re.search(pattern, v): found.add(name); break
        for meta_name, meta_val in tech.get("meta", {}).items():
            if meta_name.lower() in meta_tags and re.search(meta_val, meta_tags[meta_name.lower()]):
                found.add(name); break
    for t in found: add_finding("Technology", t, "Wappalyzer", "medium", {"url": url})

def robots_sitemap(domain, session=None):
    for path in ["robots.txt", "sitemap.xml"]:
        url = f"https://{domain}/{path}"
        r = safe_request("GET", url, session=session)
        if r and r.status_code == 200: add_finding("Site File", url, path.split(".")[0], "medium")

def duckduckgo_dorks(query, session=None):
    dorks = [
        f'site:linkedin.com "{query}"',
        f'site:facebook.com "{query}"',
        f'site:twitter.com "{query}"',
        f'"{query}" filetype:pdf',
    ]
    for dork in dorks:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(dork)}"
        r = safe_request("GET", url, session=session)
        time.sleep(random.uniform(1.5, 3.0))
        if r:
            for e in extract_emails(r.text): add_finding("Email (Dork)", e, "DuckDuckGo", "low")
            for p in PHONE_EXTRACT_RE.findall(r.text): add_finding("Phone (Dork)", p, "DuckDuckGo", "low")

def phone_libphonenumber(phone):
    try:
        pn = phonenumbers.parse(phone, None)
        add_finding("Phone Info", phone, "libphonenumber", "high", {
            "valid": phonenumbers.is_valid_number(pn),
            "country": geocoder.description_for_number(pn, "en"),
            "carrier": carrier.name_for_number(pn, "en"),
            "timezone": pn_timezone.time_zones_for_number(pn)
        })
    except: pass

def truecaller_lookup(phone):
    if not TC_OK:
        add_finding("Truecaller", "truecallerpy not installed", "Truecaller", "info")
        return
    email = os.environ.get("TC_EMAIL"); pw = os.environ.get("TC_PASS")
    if not email or not pw:
        add_finding("Truecaller", "Set TC_EMAIL / TC_PASS env vars", "Truecaller", "info")
        return
    try:
        result = search_phonenumber(phone.replace("+",""), "IN", login_id=email, password=pw)
        if result:
            add_finding("Truecaller", result.get("name", "Unknown"), "Truecaller", "high", result)
            for key in result:
                if "address" in key.lower() and result[key]:
                    add_finding("Possible Address", str(result[key]), "Truecaller", "medium")
    except Exception as e: add_finding("Truecaller Error", str(e)[:60], "Truecaller", "low")

def email_gravatar(email, session):
    h = hashlib.md5(email.lower().encode()).hexdigest()
    r = safe_request("GET", f"https://www.gravatar.com/{h}.json", session=session)
    if r and r.status_code == 200:
        try:
            j = r.json(); entry = (j.get("entry") or [{}])[0]
            add_finding("Gravatar", entry.get("displayName", "Unknown"), "Gravatar", "high", entry)
            for photo in entry.get("photos", []): add_finding("Avatar URL", photo.get("value"), "Gravatar", "medium")
        except: pass

def email_hibp(email, session):
    sha = hashlib.sha1(email.lower().encode()).hexdigest().upper()
    prefix, suffix = sha[:5], sha[5:]
    r = safe_request("GET", f"https://api.pwnedpasswords.com/range/{prefix}", use_proxy=False, session=session)
    if r and r.status_code == 200:
        for line in r.text.splitlines():
            if line.startswith(suffix):
                count = line.split(":")[1].strip()
                add_finding("Breach (HIBP)", f"Pwned in {count} breaches", "HIBP", "high")
                return
    add_finding("Breach (HIBP)", "No breaches found", "HIBP", "info")

def email_account_checks(email, session):
    checks = {
        "github": ("POST", "https://github.com/signup_check/email", {"value": email}, lambda r: r.status_code == 422),
        "twitter": ("GET", f"https://api.twitter.com/i/users/email_available.json?email={urllib.parse.quote(email)}", None, lambda r: r.json().get("taken")),
        "microsoft": ("POST", "https://login.live.com/GetCredentialType.srf", urllib.parse.urlencode({"username": email}), lambda r: "password" in r.text.lower()),
        "spotify": ("POST", "https://spclient.wg.spotify.com/signup/public/v1/account", {"validate":"1","email":email}, lambda r: "exists" in r.text),
        "wordpress": ("GET", f"https://public-api.wordpress.com/rest/v1.1/users/{urllib.parse.quote(email)}/auth-options", None, lambda r: r.status_code==200 and "password" in r.text.lower()),
    }
    for name, (method, url, data, cond) in checks.items():
        if method == "GET": r = safe_request("GET", url, session=session)
        else: r = safe_request("POST", url, session=session, data=data)
        if r and cond(r): add_finding("Account Found", name.title(), name, "high")

def ahmia(query, session):
    r = safe_request("GET", f"https://ahmia.fi/search/?q={urllib.parse.quote(query)}", session=session)
    if r:
        onions = re.findall(r"https?://[a-zA-Z0-9]{16,}\.onion(?:[/?#]\S*)?", r.text, re.I)
        clean = list(set(o.split('"')[0].split('<')[0] for o in onions))
        for o in clean[:5]: add_finding("Onion Link", o, "Ahmia", "medium")

def onionland(query, session):
    r = safe_request("GET", f"https://onionland.io/search?q={urllib.parse.quote(query)}", session=session)
    if r:
        onions = re.findall(r"https?://[a-zA-Z0-9]{16,}\.onion(?:[/?#]\S*)?", r.text, re.I)
        clean = list(set(o.split('"')[0].split('<')[0] for o in onions))
        for o in clean[:5]: add_finding("Onion Link", o, "OnionLand", "medium")

def scylla(query, session):
    try:
        r = safe_request("GET", f"https://scylla.so/search?q={urllib.parse.quote(query)}", session=session, use_proxy=False)
        if r and r.status_code == 200 and "results" in r.text.lower(): add_finding("Scylla Hit", "Data found", "Scylla", "medium")
    except: pass

def intelx(query, session):
    key = os.environ.get("INTELX_KEY")
    if not key:
        add_finding("IntelX", "Set INTELX_KEY for deep web", "IntelX", "info")
        return
    headers = {"x-key": key, "User-Agent": ua.random}
    r = safe_request("POST", "https://2.intelx.io/intelligent/search", json={"term": query, "maxresults": 5}, headers=headers, session=session, use_proxy=False)
    if r and r.status_code == 200:
        try:
            for rec in r.json().get("records", []): add_finding("IntelX Result", rec.get("name","unknown"), "IntelX", "high", rec)
        except: pass

def leakcheck_api(query, session):
    key = os.environ.get("LEAKCHECK_KEY")
    if not key:
        add_finding("LeakCheck", "Set LEAKCHECK_KEY for leaks", "LeakCheck", "info")
        return
    headers = {"X-API-Key": key}
    r = safe_request("GET", f"https://leakcheck.io/api/public?check={urllib.parse.quote(query)}", headers=headers, session=session)
    if r and r.status_code == 200 and r.json().get("found"): add_finding("LeakCheck", r.json().get("sources", "found"), "LeakCheck", "high")

def github_code_search(query, session):
    r = safe_request("GET", f"https://api.github.com/search/code?q=%22{urllib.parse.quote(query)}%22", session=session)
    if r and r.status_code == 200:
        for item in r.json().get("items", [])[:5]: add_finding("GitHub Leak", item.get("html_url"), "GitHub", "high", {"repo": item.get("repository",{}).get("full_name")})

def telegram_channel_search(query, session):
    r = safe_request("GET", f"https://html.duckduckgo.com/html/?q=site:t.me {query}", session=session)
    if r:
        for link in re.findall(r"https://t\.me/\S+", r.text): add_finding("Telegram Link", link, "DuckDuckGo", "low")

def urlscan_search(query, session):
    r = safe_request("GET", f"https://urlscan.io/api/v1/search/?q={urllib.parse.quote(query)}", session=session, use_proxy=False)
    if r and r.status_code == 200:
        for res in r.json().get("results", [])[:5]: add_finding("URLScan", res.get("page",{}).get("url"), "URLScan", "medium")

def tor_crawler(onion_url, session):
    r = safe_request("GET", onion_url, tor_ok=True, session=session)
    if r:
        for e in extract_emails(r.text): add_finding("Email (Onion)", e, "TorCrawler", "high", {"onion": onion_url})
        for p in PHONE_EXTRACT_RE.findall(r.text): add_finding("Phone (Onion)", p, "TorCrawler", "medium", {"onion": onion_url})

def check_subdomain_alive(subdomains):
    live = []
    for sub in subdomains[:10]:
        for port in [80, 443]:
            try:
                with socket.create_connection((sub, port), timeout=2):
                    live.append(sub)
                    break
            except: pass
    for s in live:
        add_finding("Live Subdomain", s, "Socket Check", "high")

def check_crt_sh(domain, session=None):
    url = f"https://crt.sh/?q=%.{urllib.parse.quote(domain)}&output=json"
    r = safe_request("GET", url, session=session, use_proxy=False, timeout=5)
    if r and r.status_code == 200:
        try:
            subdomains = set()
            for entry in r.json():
                name = entry.get("name_value", "")
                for sub in name.split("\n"):
                    sub = sub.strip().lower()
                    if sub.endswith(domain) and not sub.startswith("*"):
                        subdomains.add(sub)
            sub_list = list(subdomains)[:15]
            for s in sub_list: add_finding("Subdomain", s, "crt.sh", "high")
            check_subdomain_alive(sub_list)
        except: pass

def rdap_lookup(domain, session=None):
    url = f"https://rdap.org/domain/{urllib.parse.quote(domain)}"
    r = safe_request("GET", url, session=session, use_proxy=False, timeout=5)
    if r and r.status_code == 200:
        try:
            data = r.json()
            handle = data.get("handle", "N/A")
            events = {e.get("eventAction"): e.get("eventDate") for e in data.get("events", [])}
            add_finding("RDAP Domain", f"Handle: {handle} | Created: {events.get('registration', 'N/A')}", "rdap.org", "high")
        except: pass

def wayback_cdx(domain, session=None):
    url = f"http://web.archive.org/cdx/search/cdx?url=*.{urllib.parse.quote(domain)}/*&output=json&fl=original&collapse=urlkey&limit=10"
    r = safe_request("GET", url, session=session, use_proxy=False, timeout=5)
    if r and r.status_code == 200:
        try:
            results = r.json()
            if len(results) > 1:
                for row in results[1:]: add_finding("Archived URL", row[0], "Wayback Machine", "low")
        except: pass

def check_email_security(domain, session=None):
    targets = [(domain, "TXT"), (f"_dmarc.{domain}", "TXT")]
    for name, rtype in targets:
        url = f"https://dns.google/resolve?name={urllib.parse.quote(name)}&type={rtype}"
        r = safe_request("GET", url, session=session, use_proxy=False, timeout=5)
        if r and r.status_code == 200:
            try:
                for ans in r.json().get("Answer", []):
                    data = ans.get("data", "")
                    if "v=spf1" in data: add_finding("SPF Record", data[:60], "dns.google", "high")
                    elif "v=DMARC1" in data: add_finding("DMARC Record", data[:60], "dns.google", "high")
            except: pass

def check_urlhaus(domain, session=None):
    url = "https://urlhaus-api.abuse.ch/v1/host/"
    r = safe_request("POST", url, data={"host": domain}, session=session, use_proxy=False, timeout=5)
    if r and r.status_code == 200:
        try:
            data = r.json()
            if data.get("query_status") == "ok":
                add_finding("URLHaus Threat", f"Flagged: {data.get('url_count', 0)} URLs", "URLHaus", "high")
            else:
                add_finding("URLHaus Threat", "Clean (not flagged)", "URLHaus", "info")
        except: pass

# ------------------------------------------------------------
# REPORT EXPORT
# ------------------------------------------------------------
def save_html_report(deduped, target):
    safe = re.sub(r'[^a-zA-Z0-9]+', '_', target)
    html = f"""<html><head><meta charset='utf-8'><title>OSINT Report - {target}</title>
    <style>body{{font-family:sans-serif;background:#0d1117;color:#c9d1d9}}h1{{color:#58a6ff}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #30363d;padding:8px;text-align:left}}th{{background:#161b22}}</style>
    </head><body><h1>NexusOSINT Report for {target}</h1>
    <table><tr><th>Type</th><th>Value</th><th>Source</th><th>Confidence</th></tr>"""
    for f in deduped:
        html += f"<tr><td>{f['type']}</td><td>{f['value']}</td><td>{f['source']}</td><td>{f['confidence']}</td></tr>"
    html += "</table></body></html>"
    with open(f"report_{safe}.html", "w") as file:
        file.write(html)
    tprint(Fore.GREEN + f"[+] HTML report saved: report_{safe}.html")

def save_csv_report(deduped, target):
    safe = re.sub(r'[^a-zA-Z0-9]+', '_', target)
    with open(f"report_{safe}.csv", "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Type", "Value", "Source", "Confidence"])
        for f in deduped:
            writer.writerow([f["type"], f["value"], f["source"], f["confidence"]])
    tprint(Fore.GREEN + f"[+] CSV report saved: report_{safe}.csv")

# ------------------------------------------------------------
# MAIN DISPATCH & PIPELINE
# ------------------------------------------------------------
def run_target(target, full_scan=False):
    global findings
    findings = []
    session = make_session()
    target_type = detect_input_type(target)
    tprint(Fore.CYAN + f"[*] Target type: {target_type.upper()} | Target: {target}")

    task_list = []

    if target_type == "email":
        email = target
        domain = email.split("@")[1]
        # Core email tasks (always run)
        task_list = [
            ("Gravatar", email_gravatar, email, session),
            ("HIBP", email_hibp, email, session),
            ("Account Checks", email_account_checks, email, session),
            ("Firefox Monitor", firefox_monitor, email, session),
            ("BreachDirectory", breachdirectory_scrape, email, session),
            ("DuckDuckGo Dorks", duckduckgo_dorks, email, session),
            ("GitHub Code", github_code_search, email, session),
            ("Ahmia", ahmia, email, session),
            ("OnionLand", onionland, email, session),
            ("Scylla", scylla, email, session),
            ("IntelX", intelx, email, session),
            ("LeakCheck", leakcheck_api, email, session),
            ("Telegram", telegram_channel_search, email, session),
            ("URLScan", urlscan_search, email, session),
            ("WhatsMyName", check_username, email.split("@")[0], full_scan),
        ]
        # Domain-heavy tasks only for custom domains
        if domain.lower() not in COMMON_DOMAINS:
            task_list.extend([
                ("DNS Lookup", dns_lookup, domain, session),
                ("Robots/Sitemap", robots_sitemap, domain, session),
                ("Tech Detection", detect_tech, f"https://{domain}", session),
                ("crt.sh + Alive", check_crt_sh, domain, session),
                ("RDAP", rdap_lookup, domain, session),
                ("Wayback CDX", wayback_cdx, domain, session),
                ("SPF/DMARC", check_email_security, domain, session),
                ("URLHaus Threat", check_urlhaus, domain, session),
            ])
        # Removed psbdmp and darksearch from task list (they are dead)

    elif target_type == "phone":
        phone = target
        task_list = [
            ("Phone Info", phone_libphonenumber, phone),
            ("Truecaller", truecaller_lookup, phone),
            ("DuckDuckGo Dorks", duckduckgo_dorks, phone, session),
            ("GitHub Code", github_code_search, phone, session),
            ("Ahmia", ahmia, phone, session),
            ("OnionLand", onionland, phone, session),
            ("Scylla", scylla, phone, session),
            ("IntelX", intelx, phone, session),
            ("LeakCheck", leakcheck_api, phone, session),
            ("Telegram", telegram_channel_search, phone, session),
            ("URLScan", urlscan_search, phone, session),
        ]

    elif target_type == "domain":
        domain = target
        task_list = [
            ("DNS Lookup", dns_lookup, domain, session),
            ("Robots/Sitemap", robots_sitemap, domain, session),
            ("Tech Detection", detect_tech, f"https://{domain}", session),
            ("crt.sh + Alive", check_crt_sh, domain, session),
            ("RDAP", rdap_lookup, domain, session),
            ("Wayback CDX", wayback_cdx, domain, session),
            ("SPF/DMARC", check_email_security, domain, session),
            ("URLHaus Threat", check_urlhaus, domain, session),
            ("DuckDuckGo Dorks", duckduckgo_dorks, domain, session),
            ("GitHub Code", github_code_search, domain, session),
            ("Ahmia", ahmia, domain, session),
            ("OnionLand", onionland, domain, session),
        ]

    else:  # username
        username = target
        task_list = [
            ("WhatsMyName", check_username, username, full_scan),
            ("GitHub Code", github_code_search, username, session),
            ("DuckDuckGo Dorks", duckduckgo_dorks, username, session),
            ("Ahmia", ahmia, username, session),
            ("OnionLand", onionland, username, session),
            ("Telegram", telegram_channel_search, username, session),
        ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {}
        for name, func, *args in task_list:
            future = ex.submit(func, *args) if args else ex.submit(func)
            futures[future] = name
        with tqdm(total=len(futures), desc="OSINT Progress", bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]", disable=QUIET) as pbar:
            for future in concurrent.futures.as_completed(futures):
                name = futures[future]
                try:
                    future.result()
                except Exception as e:
                    logging.debug(f"Module {name} failed: {e}")
                pbar.update(1)
                if not QUIET:
                    pbar.set_postfix_str(f"Done: {name}")

    if is_tor_running():
        onion_links = [f["value"] for f in findings if f["type"] == "Onion Link" and ".onion" in f["value"]]
        for o in onion_links[:2]: tor_crawler(o, session)

    deduped = []
    seen = set()
    for f in findings:
        key = (f["type"], str(f["value"]).lower(), f["source"])
        if key not in seen: seen.add(key); deduped.append(f)
    return deduped

def print_table(deduped, target, export_format="json"):
    if not deduped:
        tprint(Fore.RED + "\n[!] No findings.")
        return
    table = [[f["type"], str(f["value"])[:70], f["source"], f["confidence"]] for f in deduped]
    print("\n" + Fore.MAGENTA + "="*90)
    print(Fore.GREEN + f" NEXUS OSINT REPORT — {target}")
    print(Fore.MAGENTA + "="*90)
    print(tabulate(table, headers=["TYPE", "VALUE", "SOURCE", "CONFIDENCE"], tablefmt="grid"))

    safe = re.sub(r'[^a-zA-Z0-9]+', '_', target)
    with open(f"report_{safe}.json", "w") as f:
        json.dump({"target": target, "findings": deduped}, f, indent=2)
    tprint(Fore.YELLOW + f"[+] JSON report saved: report_{safe}.json")

    if export_format == "html":
        save_html_report(deduped, target)
    elif export_format == "csv":
        save_csv_report(deduped, target)

    # Colored Summary Banner
    total = len(deduped)
    high_conf = sum(1 for f in deduped if f["confidence"] == "high")
    live_subs = sum(1 for f in deduped if f["type"] == "Live Subdomain")
    print(Fore.CYAN + f"\n{'='*40}")
    print(Fore.YELLOW + Style.BRIGHT + f" SUMMARY: {target}")
    print(Fore.CYAN + f"{'='*40}")
    print(Fore.GREEN + f" Total Findings     : {total}")
    print(Fore.GREEN + f" High Confidence    : {high_conf}")
    print(Fore.GREEN + f" Live Subdomains    : {live_subs}")
    print(Fore.CYAN + f"{'='*40}\n")

def main():
    parser = argparse.ArgumentParser(description="NexusOSINT v12 - Professional OSINT by Nikhil")
    parser.add_argument("target", help="Phone (+91...), email, domain, or username")
    parser.add_argument("--proxy", action="store_true", help="Enable free proxies (may be slow)")
    parser.add_argument("--full-scan", action="store_true", help="Scan all 500+ sites in WhatsMyName")
    parser.add_argument("--format", choices=["json", "html", "csv"], default="json", help="Export report format")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--quiet", action="store_true", help="Suppress extra output, show only progress bar and report")
    args = parser.parse_args()

    if args.debug: logging.getLogger().setLevel(logging.DEBUG)
    global QUIET, PROXY
    QUIET = args.quiet
    PROXY = ProxyRotator(enabled=args.proxy) if args.proxy else None

    print(Fore.RED + Style.BRIGHT + r"""
    ███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗ ██████╗ ███████╗██╗███╗   ██╗████████╗
    ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝██╔═══██╗██╔════╝██║████╗  ██║╚══██╔══╝
    ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗██║   ██║███████╗██║██╔██╗ ██║   ██║
    ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║██║   ██║╚════██║██║██║╚██╗██║   ██║
    ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║╚██████╔╝███████║██║██║ ╚████║   ██║
    ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝ ╚═════╝ ╚══════╝╚═╝╚═╝  ╚═══╝   ╚═╝
    """)
    print(Fore.CYAN + Style.BRIGHT + "NexusOSINT v12.2 – Clean & Fast | Smart Domain Skip")
    print(Fore.MAGENTA + "Made by Nikhil\n")

    deduped = run_target(args.target.strip(), full_scan=args.full_scan)
    print_table(deduped, args.target.strip(), export_format=args.format)

if __name__ == "__main__":
    main()
