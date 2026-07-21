#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NexusOSINT v9.8 FINAL – One Command, All Free OSINT                        ║
║  Dark Web | Phone Ownership | Breach DB | Tabular Report                    ║
║  Made by Nikhil                                                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
import argparse, concurrent.futures, hashlib, json, os, random, re, socket, subprocess, sys, threading, time, urllib.parse
from datetime import datetime, timezone
from collections import defaultdict

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    import phonenumbers
    from phonenumbers import carrier, geocoder, timezone as pn_timezone
    from tabulate import tabulate
    from colorama import init, Fore, Back, Style
    init(autoreset=True)
except ImportError:
    sys.exit("[!] Install: pip3 install requests phonenumbers tabulate colorama")

# Optional
try: from truecallerpy import search_phonenumber; TC_OK = True
except: TC_OK = False

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------
TIMEOUT = 10; MAX_WORKERS = 25
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
]
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+?91[\s\-]?)?[6-9]\d{9}|\+\d{7,15}")
lock = threading.Lock(); req_counter = 0; findings = []

# ------------------------------------------------------------
# FREE PROXY ROTATOR
# ------------------------------------------------------------
class ProxyRotator:
    SOURCES = [
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=all",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
        "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt",
        "https://www.proxy-list.download/api/v1/get?type=http",
    ]
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.proxies = []
        self.bad = set()
        self.idx = 0
        if enabled: self.refresh()
    def refresh(self):
        print(Fore.YELLOW + "[*] Fetching free proxies...")
        found = set()
        for url in self.SOURCES:
            try:
                r = requests.get(url, timeout=8, headers={"User-Agent": random.choice(USER_AGENTS)})
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
                if len(good) >= 30: break
        self.proxies = good if good else candidates[:50]
        print(Fore.GREEN + f"[+] {len(self.proxies)} live proxies")
    def next(self):
        if not self.enabled or not self.proxies: return None
        with lock:
            for _ in range(len(self.proxies)):
                p = self.proxies[self.idx % len(self.proxies)]; self.idx += 1
                if p not in self.bad:
                    return {"http": f"http://{p}", "https": f"http://{p}"}
            self.bad.clear()
            return {"http": f"http://{p}", "https": f"http://{p}"}
    def mark_bad(self, px):
        if px:
            h = px.get("http", "").replace("http://", "")
            with lock: self.bad.add(h)

PROXY = ProxyRotator(enabled=True)

def make_session():
    s = requests.Session()
    retry = Retry(total=2, backoff_factor=0.4, status_forcelist=[429,500,502,503,504])
    s.mount("https://", HTTPAdapter(max_retries=retry)); s.mount("http://", HTTPAdapter(max_retries=retry))
    return s

def safe_request(method, url, session=None, use_proxy=True, tor_ok=False, **kwargs):
    global req_counter
    sess = session or make_session()
    kwargs.setdefault("timeout", TIMEOUT); kwargs.setdefault("allow_redirects", True)
    headers = kwargs.pop("headers", {})
    headers.setdefault("User-Agent", random.choice(USER_AGENTS))
    proxies = None
    if tor_ok and ".onion" in url: proxies = {"http": "socks5h://127.0.0.1:9050", "https": "socks5h://127.0.0.1:9050"}
    elif use_proxy and PROXY.enabled: proxies = PROXY.next()
    for _ in range(3):
        try:
            with lock: req_counter += 1
            r = sess.request(method, url, headers=headers, proxies=proxies, **kwargs)
            if r.status_code in (403,429,503) and proxies and not tor_ok:
                PROXY.mark_bad(proxies); proxies = PROXY.next(); time.sleep(random.uniform(0.5,1.5))
                continue
            return r
        except:
            if proxies and not tor_ok: PROXY.mark_bad(proxies); proxies = PROXY.next()
            time.sleep(random.uniform(0.3,0.7))
    return None

def is_email(t): return bool(EMAIL_RE.fullmatch(t.strip()))
def normalize_phone(p):
    try: return phonenumbers.format_number(phonenumbers.parse(p, None), phonenumbers.PhoneNumberFormat.E164)
    except:
        digits = re.sub(r"[^\d+]", "", p)
        if len(digits) == 10 and digits[0] in "6789": digits = "+91" + digits
        if not digits.startswith("+"): digits = "+" + digits
        return digits

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
# PHONE MODULES (ownership included)
# ------------------------------------------------------------
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
    if not TC_OK: return
    email = os.environ.get("TC_EMAIL"); pw = os.environ.get("TC_PASS")
    if not email or not pw: return
    try:
        result = search_phonenumber(phone.replace("+",""), "IN", login_id=email, password=pw)
        if result:
            add_finding("Truecaller", result.get("name", "Unknown"), "Truecaller", "high", result)
            # Try to extract possible address
            for key in result:
                if "address" in key.lower() and result[key]:
                    add_finding("Possible Address", str(result[key]), "Truecaller", "medium")
    except Exception as e: add_finding("Truecaller Error", str(e), "Truecaller", "low")

def phone_carrier_lookup(phone, session):
    clean = phone.replace("+", "")
    r = safe_request("GET", f"https://www.numlookup.com/search?q={clean}", session=session)
    if r and "carrier" in r.text.lower(): add_finding("Carrier Hint", "numlookup page found", "numlookup", "low")

def phone_google_signals(phone, session):
    r = safe_request("GET", "https://accounts.google.com/signin/recovery", session=session)
    if r: add_finding("Google Signal", "Recovery reachable", "Google", "low")
    try:
        payload = {"f.req": json.dumps([None, json.dumps([None, None, None, None, None, None, None, None, None, [phone,2], None, None, None, [1]])])}
        r2 = safe_request("POST", "https://accounts.google.com/_/accountrecovery/identifyaccount", session=session, data=payload)
        if r2:
            for e in extract_emails(r2.text): add_finding("Email (from Google)", e, "Google", "medium")
            if "sms" in r2.text.lower(): add_finding("Google Account", "Possible", "Google", "medium")
    except: pass

def phone_duckduckgo(phone, session):
    for q in [f'"{phone}" name', f'"{phone}" address', f'"{phone}" street']:
        r = safe_request("GET", f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(q)}", session=session)
        if r:
            for name in re.findall(r"(?:name|Name)[\s:]*([A-Z][a-z]+ [A-Z][a-z]+)", r.text): add_finding("Possible Name", name, "DuckDuckGo", "low")
            for addr in re.findall(r"(\d{1,5}\s\w+\s\w+,\s\w+)", r.text): add_finding("Possible Address", addr, "DuckDuckGo", "low")

def phone_pastes(phone, session):
    clean = phone.replace("+", "")
    r = safe_request("GET", f"https://psbdmp.ws/api/v3/search/{urllib.parse.quote(clean)}", session=session)
    if r and r.status_code == 200:
        try:
            data = r.json(); items = data if isinstance(data, list) else data.get("data", [])
            for item in items[:10]:
                blob = json.dumps(item)
                for e in extract_emails(blob): add_finding("Email (Paste)", e, "psbdmp", "high")
                for p in PHONE_RE.findall(blob): add_finding("Phone (Paste)", p, "psbdmp", "high")
        except: pass

# ------------------------------------------------------------
# EMAIL MODULES
# ------------------------------------------------------------
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
        "instagram": ("POST", "https://www.instagram.com/api/v1/web/accounts/web_create_ajax/attempt/", {"email": email}, lambda r: "taken" in r.text.lower()),
        "microsoft": ("POST", "https://login.live.com/GetCredentialType.srf", urllib.parse.urlencode({"username": email}), lambda r: "password" in r.text.lower()),
        "spotify": ("POST", "https://spclient.wg.spotify.com/signup/public/v1/account", {"validate":"1","email":email}, lambda r: "exists" in r.text),
        "wordpress": ("GET", f"https://public-api.wordpress.com/rest/v1.1/users/{urllib.parse.quote(email)}/auth-options", None, lambda r: r.status_code==200 and "password" in r.text.lower()),
    }
    for name, (method, url, data, cond) in checks.items():
        if method == "GET": r = safe_request("GET", url, session=session)
        else: r = safe_request("POST", url, session=session, data=data)
        if r and cond(r): add_finding("Account Found", name.title(), name, "high")

def email_duckduckgo(email, session):
    r = safe_request("GET", f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(email)}", session=session)
    if r:
        for e in extract_emails(r.text): add_finding("Email (DuckDuckGo)", e, "DuckDuckGo", "low")
        for p in PHONE_RE.findall(r.text): add_finding("Phone (DuckDuckGo)", p, "DuckDuckGo", "low")

def email_pastes(email, session):
    r = safe_request("GET", f"https://psbdmp.ws/api/v3/search/{urllib.parse.quote(email)}", session=session)
    if r and r.status_code == 200:
        try:
            data = r.json(); items = data if isinstance(data, list) else data.get("data", [])
            for item in items[:10]:
                blob = json.dumps(item)
                for p in PHONE_RE.findall(blob): add_finding("Phone (Paste)", p, "psbdmp", "high")
                for e in extract_emails(blob): add_finding("Email (Paste)", e, "psbdmp", "high")
        except: pass

# ------------------------------------------------------------
# DARK WEB & ADVANCED
# ------------------------------------------------------------
def darksearch(query, session):
    r = safe_request("GET", f"https://darksearch.io/api/search?q={urllib.parse.quote(query)}", session=session, use_proxy=False)
    if r and r.status_code == 200:
        try:
            for item in r.json().get("data", [])[:5]: add_finding("Dark Link", item.get("url"), "DarkSearch", "medium", {"title": item.get("title")})
        except: pass

def ahmia(query, session):
    r = safe_request("GET", f"https://ahmia.fi/search/?q={urllib.parse.quote(query)}", session=session)
    if r:
        onions = re.findall(r"https?://[a-zA-Z0-9]{16,}\.onion(?:[/?#]\S*)?", r.text, re.I)
        for o in onions[:5]: add_finding("Onion Link", o, "Ahmia", "medium")

def onionland(query, session):
    r = safe_request("GET", f"https://onionland.io/search?q={urllib.parse.quote(query)}", session=session)
    if r:
        onions = re.findall(r"https?://[a-zA-Z0-9]{16,}\.onion(?:[/?#]\S*)?", r.text, re.I)
        for o in onions[:5]: add_finding("Onion Link", o, "OnionLand", "medium")

def torch_search(query, session):
    """Torch dark web engine via Tor."""
    if not is_tor_running(): return
    onion = "http://xmh57jrzrnw6insl.onion/search"
    r = safe_request("GET", onion, params={"q": query}, tor_ok=True, session=session)
    if r:
        for e in extract_emails(r.text): add_finding("Email (Torch)", e, "Torch", "low")
        for p in PHONE_RE.findall(r.text): add_finding("Phone (Torch)", p, "Torch", "low")

def cryptbb(query, session):
    """CryptBB dark web forum search via Tor."""
    if not is_tor_running(): return
    onion = "http://cryptbbtg65gibadeeo2awe3j7s6evg7eklserehqr4w4e2bis5tebid.onion/search.php"
    r = safe_request("GET", onion, params={"search": query}, tor_ok=True, session=session)
    if r:
        for e in extract_emails(r.text): add_finding("Email (CryptBB)", e, "CryptBB", "medium")
        for p in PHONE_RE.findall(r.text): add_finding("Phone (CryptBB)", p, "CryptBB", "medium")

def scylla(query, session):
    try:
        r = safe_request("GET", f"https://scylla.so/search?q={urllib.parse.quote(query)}", session=session, use_proxy=False)
        if r and r.status_code == 200 and "results" in r.text.lower(): add_finding("Scylla Hit", "Data found", "Scylla", "medium")
    except: pass

def intelx(query, session):
    key = os.environ.get("INTELX_KEY")
    if not key: return
    headers = {"x-key": key, "User-Agent": random.choice(USER_AGENTS)}
    r = safe_request("POST", "https://2.intelx.io/intelligent/search", json={"term": query, "maxresults": 5}, headers=headers, session=session, use_proxy=False)
    if r and r.status_code == 200:
        try:
            for rec in r.json().get("records", []): add_finding("IntelX Result", rec.get("name","unknown"), "IntelX", "high", rec)
        except: pass

def leakcheck_api(query, session):
    key = os.environ.get("LEAKCHECK_KEY")
    if not key: return
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

def theharvester_invoke(target):
    try:
        # Use the installed command 'theHarvester'
        result = subprocess.run(["theHarvester", "-d", target, "-b", "all"], capture_output=True, text=True, timeout=90)
        for e in EMAIL_RE.findall(result.stdout): add_finding("Email (theHarvester)", e, "theHarvester", "medium")
        for p in PHONE_RE.findall(result.stdout): add_finding("Phone (theHarvester)", p, "theHarvester", "medium")
    except Exception as e: add_finding("Error", f"theHarvester: {str(e)[:50]}", "theHarvester", "low")

def tor_crawler(onion_url, session):
    r = safe_request("GET", onion_url, tor_ok=True, session=session)
    if r:
        for e in extract_emails(r.text): add_finding("Email (Onion)", e, "TorCrawler", "high", {"onion": onion_url})
        for p in PHONE_RE.findall(r.text): add_finding("Phone (Onion)", p, "TorCrawler", "medium", {"onion": onion_url})

# ------------------------------------------------------------
# MAIN PIPELINE
# ------------------------------------------------------------
def run_target(target):
    global findings
    findings = []
    session = make_session()

    if is_email(target):
        email = target.lower()
        print(Fore.CYAN + f"[*] Email OSINT: {email}")
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            ex.submit(email_gravatar, email, session)
            ex.submit(email_hibp, email, session)
            ex.submit(email_account_checks, email, session)
            ex.submit(email_duckduckgo, email, session)
            ex.submit(email_pastes, email, session)
            ex.submit(github_code_search, email, session)
            ex.submit(darksearch, email, session)
            ex.submit(ahmia, email, session)
            ex.submit(onionland, email, session)
            ex.submit(torch_search, email, session)
            ex.submit(cryptbb, email, session)
            ex.submit(scylla, email, session)
            ex.submit(intelx, email, session)
            ex.submit(leakcheck_api, email, session)
            ex.submit(telegram_channel_search, email, session)
            ex.submit(theharvester_invoke, email)
        if is_tor_running():
            onion_links = [f["value"] for f in findings if f["type"] == "Onion Link" and ".onion" in f["value"]]
            for o in onion_links[:2]: tor_crawler(o, session)
    else:
        phone = normalize_phone(target)
        print(Fore.CYAN + f"[*] Phone OSINT: {phone}")
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            ex.submit(phone_libphonenumber, phone)
            ex.submit(truecaller_lookup, phone)
            ex.submit(phone_carrier_lookup, phone, session)
            ex.submit(phone_google_signals, phone, session)
            ex.submit(phone_duckduckgo, phone, session)
            ex.submit(phone_pastes, phone, session)
            ex.submit(github_code_search, phone, session)
            ex.submit(darksearch, phone, session)
            ex.submit(ahmia, phone, session)
            ex.submit(onionland, phone, session)
            ex.submit(torch_search, phone, session)
            ex.submit(cryptbb, phone, session)
            ex.submit(scylla, phone, session)
            ex.submit(intelx, phone, session)
            ex.submit(leakcheck_api, phone, session)
            ex.submit(telegram_channel_search, phone, session)
            ex.submit(theharvester_invoke, phone)
        if is_tor_running():
            onion_links = [f["value"] for f in findings if f["type"] == "Onion Link" and ".onion" in f["value"]]
            for o in onion_links[:2]: tor_crawler(o, session)

    # Deduplicate
    deduped = []
    seen = set()
    for f in findings:
        key = (f["type"], str(f["value"]).lower(), f["source"])
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    return deduped

def print_table(deduped, target):
    if not deduped:
        print(Fore.RED + "\n[!] No findings.")
        return
    table = []
    for f in deduped:
        table.append([f["type"], str(f["value"])[:70], f["source"], f["confidence"]])
    print("\n" + Fore.MAGENTA + "="*90)
    print(Fore.GREEN + f" NEXUS OSINT REPORT — {target}")
    print(Fore.MAGENTA + "="*90)
    print(tabulate(table, headers=["TYPE", "VALUE", "SOURCE", "CONFIDENCE"], tablefmt="grid"))
    safe = re.sub(r'[^a-zA-Z0-9]+', '_', target)
    with open(f"report_{safe}.json", "w") as f: json.dump({"target": target, "findings": deduped}, f, indent=2)
    print(Fore.YELLOW + f"\n[+] JSON report saved: report_{safe}.json")

def main():
    parser = argparse.ArgumentParser(description="NexusOSINT - One Command Free OSINT by Nikhil")
    parser.add_argument("target", help="Phone number (+91...) or email")
    parser.add_argument("--no-proxy", action="store_true", help="Disable free proxies")
    args = parser.parse_args()
    if args.no_proxy: PROXY.enabled = False
    global target
    target = args.target.strip()

    # Colorful Banner
    print(Fore.RED + Style.BRIGHT + r"""
    ███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗ ██████╗ ███████╗██╗███╗   ██╗████████╗
    ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝██╔═══██╗██╔════╝██║████╗  ██║╚══██╔══╝
    ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗██║   ██║███████╗██║██╔██╗ ██║   ██║
    ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║██║   ██║╚════██║██║██║╚██╗██║   ██║
    ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║╚██████╔╝███████║██║██║ ╚████║   ██║
    ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝ ╚═════╝ ╚══════╝╚═╝╚═╝  ╚═══╝   ╚═╝
    """)
    print(Fore.CYAN + Style.BRIGHT + "NexusOSINT v9.8 FINAL – One Command, All Free OSINT")
    print(Fore.YELLOW + "Dark Web | Phone Ownership | Breach DB | Tabular Report")
    print(Fore.MAGENTA + "Made by Nikhil\n")

    deduped = run_target(target)
    print_table(deduped, target)

if __name__ == "__main__":
    main()
