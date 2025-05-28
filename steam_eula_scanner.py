import sys

# ---- Dependency check and helpful error message ----
required_modules = [
    "requests", "beautifulsoup4", "tqdm", "openai",
    "PyPDF2", "python_docx", "striprtf"
]
missing = []
for mod in required_modules:
    try:
        if mod == "beautifulsoup4":
            __import__("bs4")
        elif mod == "python_docx":
            __import__("docx")
        else:
            __import__(mod)
    except ImportError:
        missing.append(mod if mod != "python_docx" else "python-docx")
if missing:
    print("\nERROR: Missing dependencies detected!")
    print("To install them, run:")
    print(f"python -m pip install {' '.join(missing)}")
    sys.exit(1)

# ---- Now safe to import everything ----
import os
import glob
import re
import time
import csv
import requests
from tqdm import tqdm
from bs4 import BeautifulSoup
import PyPDF2
import openai
import docx
from striprtf.striprtf import rtf_to_text

# ---------------- CONFIGURATION ----------------
OPENAI_API_KEY = "" # Optionally paste your key here, or leave blank to use env variable
STEAM_PATH = r"C:\Program Files (x86)\Steam" # Change if your Steam is elsewhere
API_DELAY = 2 # seconds between API calls
OUTPUT_FILE = "steam_eula_privacy_report.csv"
EULA_DUMP_FILE = "steam_eula_dump.txt" # File to save raw EULA texts

# ---------------- OPENAI CLIENT SETUP ----------------
api_key = os.environ.get("OPENAI_API_KEY", OPENAI_API_KEY)
openai_enabled = True
if not api_key or api_key == "YOUR_OPENAI_API_KEY_HERE":
    print("\nWARNING: OpenAI API key not set.")
    print("OpenAI analysis will be skipped. Set the OPENAI_API_KEY environment variable or paste your key into the script to enable AI privacy checking.\n")
    openai_enabled = False
else:
    client = openai.OpenAI(api_key=api_key)

# ---------------- ANTI-CHEAT/PRIVACY KEYWORDS ----------------
ANTI_CHEAT_SYSTEMS = [
    "EasyAntiCheat", "Easy Anti-Cheat", "EAC",
    "BattlEye", "BattleEye",
    "nProtect", "GameGuard", "nProtect GameGuard",
    "Vanguard", "Riot Vanguard",
    "Ricochet", "Call of Duty Ricochet",
    "XIGNCODE", "XIGNCODE3",
    "PunkBuster",
    "FACEIT", "FACEIT Anti-Cheat",
    "FairFight",
    "Valve Anti-Cheat", "VAC",
    "SHiELD", "SHiELD Anti-Cheat",
    "HackShield", "AhnLab HackShield",
    "GameShield",
    "MShield",
    "SGuard",
    "CheatBuster",
    "Warden",
    "Sentry Anti-Cheat",
    "uTRUST", "uTRUST Anti-Cheat",
    "BEACON Anti-Cheat",
    "Kakao Anti-Cheat",
    "nProtect Anti-Cheat",
    "Neowiz Anti-Cheat",
    "Denuvo Anti-Cheat",
    "Denuvo",
    "StarForce",
    "SecuROM",
    "SafeDisc",
    "Arxan",
    "VMProtect",
    "Themida",
    "rootkit",
    "Ring 0",
    "kernel-level", "kernel mode", "kernel driver",
    "HWID", "HWID ban"
]

GENERIC_PRIVACY_TERMS = [
    "kernel", "system privileges", "privileged driver", "driver installation",
    "background service", "persistent service", "process injection", "memory scanning",
    "code injection", "anti-debug", "anti-tamper", "integrity check", "obfuscation",
    "monitoring software", "surveillance", "third-party monitoring", "data collection",
    "hardware ban", "device fingerprint", "telemetry", "monitoring", "driver", "elevated privileges", 
	"admin rights", "administrator", "background process", "persistent", "ring0", "ring-0"
]

def scan_for_anti_cheat_and_privacy(text):
    found_systems = []
    found_generic = []
    for kw in ANTI_CHEAT_SYSTEMS:
        if re.search(r'\b{}\b'.format(re.escape(kw)), text, re.IGNORECASE):
            found_systems.append(kw)
    for kw in GENERIC_PRIVACY_TERMS:
        if re.search(r'\b{}\b'.format(re.escape(kw)), text, re.IGNORECASE):
            found_generic.append(kw)
    if found_systems:
        return "Detected: " + ", ".join(sorted(set(found_systems)))
    elif found_generic:
        return "No specific anti-cheat detected, but technical/privacy terms found: " + ", ".join(sorted(set(found_generic))) + ". Manual review suggested."
    else:
        return "No anti-cheat or concerning technical terms detected."

# ---------------- PCGAMINGWIKI SCRAPER ----------------
def get_pcgamingwiki_anti_cheat(game_name):
    url_name = game_name.replace(" ", "_")
    url = f"https://www.pcgamingwiki.com/wiki/{url_name}"
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return "Not found"
        soup = BeautifulSoup(resp.text, "html.parser")
        ac_section = soup.find("span", {"id": "Anti-cheat"})
        if ac_section:
            parent = ac_section.find_parent("h2")
            if parent:
                content = []
                sib = parent.find_next_sibling()
                while sib and sib.name != "h2":
                    content.append(sib.get_text(separator="\n", strip=True))
                    sib = sib.find_next_sibling()
                return "\n".join(content).strip() or "Section found, but no content."
        # Fallback: look for keywords
        if "anti-cheat" in resp.text.lower():
            return "Anti-cheat mentioned, see page."
        return "No anti-cheat info found."
    except Exception as e:
        return f"Error: {e}"

# ---------------- FORUM/REDDIT SEARCH LINKS ----------------
def make_reddit_search_link(game_name):
    from urllib.parse import quote_plus
    query = quote_plus(f"{game_name} anti-cheat")
    return f"https://www.reddit.com/r/pcgaming/search/?q={query}&restrict_sr=1"

def make_steam_forum_search_link(appid):
    return f"https://steamcommunity.com/app/{appid}/discussions/search/?q=anti-cheat"

# ---------------- WHITESPACE CLEANER ----------------
def clean_eula_text(text):
    text = text.replace('\t', ' ')
    text = re.sub(r'[ ]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = '\n'.join(line.strip() for line in text.splitlines())
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

# ---------------- HELPER FUNCTIONS ----------------
def normalize(text):
    return re.sub(r'[^a-z0-9]', '', text.lower())

def is_close_match(game_name, filename):
    norm_game = normalize(game_name)
    norm_file = normalize(filename)
    return norm_game in norm_file or norm_file in norm_game

def content_matches_game(game_name, content):
    norm_game = normalize(game_name)
    norm_content = normalize(content)
    return norm_game in norm_content

def get_steam_libraries(steam_path):
    library_vdf = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
    libraries = [os.path.join(steam_path, "steamapps")]
    try:
        with open(library_vdf, "r", encoding="utf-8") as f:
            for line in f:
                match = re.search(r'"\d+"\s+"(.+)"', line)
                if match:
                    libraries.append(os.path.join(match.group(1).replace("\\\\", "\\"), "steamapps"))
    except Exception as e:
        print(f"Could not read libraryfolders.vdf: {e}")
    return libraries

def get_installed_games(libraries):
    games = []
    for lib in libraries:
        manifests = glob.glob(os.path.join(lib, "appmanifest_*.acf"))
        for mf in manifests:
            try:
                with open(mf, "r", encoding="utf-8") as f:
                    content = f.read()
                appid_match = re.search(r'"appid"\s+"(\d+)"', content)
                name_match = re.search(r'"name"\s+"([^"]+)"', content)
                installdir_match = re.search(r'"installdir"\s+"([^"]+)"', content)
                if appid_match and name_match and installdir_match:
                    appid = appid_match.group(1)
                    name = name_match.group(1)
                    installdir = installdir_match.group(1)
                    game_path = os.path.join(lib, "common", installdir)
                    games.append({
                        "appid": appid,
                        "name": name,
                        "path": game_path
                    })
            except Exception as e:
                print(f"Error reading {mf}: {e}")
    return games

def get_app_details(appid):
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=us&l=en"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data[str(appid)]['success']:
            return data[str(appid)]['data']
    except Exception as e:
        print(f"Failed to fetch app details for {appid}: {e}")
    return None

def get_eula_url_from_api(app_details):
    if "eula" in app_details:
        return app_details["eula"].get("url")
    if "legal_notice" in app_details and isinstance(app_details["legal_notice"], str) and app_details["legal_notice"].startswith("http"):
        return app_details["legal_notice"]
    if "about_the_game" in app_details:
        match = re.search(r'href="(https?://[^"]+eula[^"]*)"', app_details["about_the_game"], re.I)
        if match:
            return match.group(1)
    return None

def get_eula_url_or_text_from_store_page(appid):
    url = f"https://store.steampowered.com/app/{appid}"
    try:
        resp = requests.get(url, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            if "eula" in a["href"].lower():
                return a["href"]
        legal_sections = soup.find_all(string=re.compile(r"(End User License Agreement|EULA|Legal Notice)", re.I))
        for sec in legal_sections:
            return sec.parent.get_text(separator="\n", strip=True)
    except Exception as e:
        print(f"Failed to scrape store page for {appid}: {e}")
    return None

def extract_text_from_pdf(pdf_path):
    text = ""
    try:
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            for page in pdf_reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        print(f"Error reading PDF {pdf_path}: {e}")
    return text

def extract_text_from_docx(docx_path):
    text = ""
    try:
        doc = docx.Document(docx_path)
        for para in doc.paragraphs:
            text += para.text + "\n"
    except Exception as e:
        print(f"Error reading DOCX {docx_path}: {e}")
    return text

def extract_text_from_rtf(rtf_path):
    text = ""
    try:
        with open(rtf_path, "r", encoding="utf-8", errors="ignore") as f:
            rtf_content = f.read()
            text = rtf_to_text(rtf_content)
    except Exception as e:
        print(f"Error reading RTF {rtf_path}: {e}")
    return text

def extract_text_from_html(html_path):
    text = ""
    try:
        with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
            text = soup.get_text(separator="\n")
    except Exception as e:
        print(f"Error reading HTML {html_path}: {e}")
    return text

def extract_text_by_extension(file):
    ext = os.path.splitext(file)[1].lower()
    if ext == ".txt":
        try:
            with open(file, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception as e:
            print(f"Error reading TXT {file}: {e}")
    elif ext == ".pdf":
        return extract_text_from_pdf(file)
    elif ext == ".rtf":
        return extract_text_from_rtf(file)
    elif ext == ".docx":
        return extract_text_from_docx(file)
    elif ext in [".html", ".htm"]:
        return extract_text_from_html(file)
    return ""

def get_eula_text_from_game_files(game_name, game_path):
    eula_texts = []
    patterns = [
        "**/*eula*.txt", "**/*license*.txt", "**/*legal*.txt",
        "**/*eula*.pdf", "**/*license*.pdf", "**/*legal*.pdf",
        "**/*eula*.rtf", "**/*license*.rtf", "**/*legal*.rtf",
        "**/*eula*.docx", "**/*license*.docx", "**/*legal*.docx",
        "**/*eula*.html", "**/*license*.html", "**/*legal*.html",
        "**/*eula*.htm", "**/*license*.htm", "**/*legal*.htm",
        "**/*readme*.txt", "**/*manual*.txt"
    ]
    candidate_files = set()
    for pattern in patterns:
        for file in glob.glob(os.path.join(game_path, pattern), recursive=True):
            candidate_files.add(file)
    for file in candidate_files:
        filename = os.path.basename(file)
        file_text = extract_text_by_extension(file)
        if is_close_match(game_name, filename):
            eula_texts.append((file, file_text, "filename-match"))
        elif content_matches_game(game_name, file_text):
            eula_texts.append((file, file_text, "content-match"))
    if not eula_texts:
        root_patterns = [
            "eula*.txt", "license*.txt", "legal*.txt",
            "eula*.pdf", "license*.pdf", "legal*.pdf",
            "eula*.rtf", "license*.rtf", "legal*.rtf",
            "eula*.docx", "license*.docx", "legal*.docx",
            "eula*.html", "license*.html", "legal*.html",
            "readme*.txt", "manual*.txt"
        ]
        for pattern in root_patterns:
            for file in glob.glob(os.path.join(game_path, pattern)):
                file_text = extract_text_by_extension(file)
                if file_text.strip():
                    eula_texts.append((file, file_text, "generic-root"))
    return eula_texts

def get_eula_text(eula_url_or_text):
    if not eula_url_or_text:
        return None
    if isinstance(eula_url_or_text, str) and eula_url_or_text.startswith("http"):
        try:
            resp = requests.get(eula_url_or_text, timeout=10)
            if "text/html" in resp.headers.get("Content-Type", ""):
                text = BeautifulSoup(resp.text, "html.parser").get_text(separator="\n")
                return text.strip()
            else:
                return resp.text.strip()
        except Exception as e:
            print(f"Failed to download EULA: {e}")
            return None
    else:
        return eula_url_or_text

def analyze_eula_with_ai(eula_text):
    if not eula_text:
        return "No EULA found", ""
    prompt = (
        "You are a privacy expert. Analyze the following End User License Agreement (EULA) "
        "for privacy-related red flags, such as data collection, third-party sharing, user tracking, or invasive permissions. "
        "Respond with either 'Privacy risk' or 'No issues', then a short explanation. "
        "EULA:\n\n" + eula_text[:4000]
    )
    try:
        response = client.completions.create(
            model="gpt-3.5-turbo-instruct",
            prompt=prompt,
            max_tokens=300,
            temperature=0.0,
        )
        return response.choices[0].text.strip(), ""
    except Exception as e:
        if hasattr(e, "message") and ("insufficient_quota" in str(e) or "quota" in str(e)):
            return "Quota exceeded", str(e)
        if "insufficient_quota" in str(e) or "quota" in str(e):
            return "Quota exceeded", str(e)
        return "AI analysis failed", str(e)

# ---------------- MAIN PROCESS ----------------
def main():
    print("Scanning Steam libraries...")
    libraries = get_steam_libraries(STEAM_PATH)
    games = get_installed_games(libraries)
    print(f"Found {len(games)} installed Steam games.")
    results = []
    quota_exceeded = False # Track quota error

    # Clear the EULA dump file at the start
    with open(EULA_DUMP_FILE, "w", encoding="utf-8") as f:
        f.write("")

    for game in tqdm(games, desc="Processing games"):
        appid = game["appid"]
        name = game["name"]
        path = game["path"]
        app_details = get_app_details(appid)
        eula_url = None
        eula_text = None
        eula_sources = []

        # 1. Try Steam API
        if app_details:
            eula_url = get_eula_url_from_api(app_details)
        # 2. Try scraping the store page
        if not eula_url:
            eula_url = get_eula_url_or_text_from_store_page(appid)
        # 3. Download or use text from above
        if eula_url:
            eula_text = get_eula_text(eula_url)
            if eula_text:
                eula_sources.append(("Steam API/Store", eula_text, "api-or-store"))
        # 4. Try local files with filename/content matching
        local_eulas = get_eula_text_from_game_files(name, path)
        for file_path, text, match_type in local_eulas:
            eula_sources.append((file_path, text, match_type))

        # Choose the "best" EULA for AI analysis (prefer API/Store, else filename/content match, else generic-root)
        eula_for_ai = None
        for src, txt, match_type in eula_sources:
            if match_type in ("api-or-store", "filename-match", "content-match"):
                eula_for_ai = txt
                break
        if not eula_for_ai and eula_sources:
            eula_for_ai = eula_sources[0][1]

        # ---- Anti-cheat/Privacy scan ----
        anti_cheat_scan = "No EULA found"
        if eula_for_ai:
            anti_cheat_scan = scan_for_anti_cheat_and_privacy(eula_for_ai)

        # --- PCGamingWiki anti-cheat info ---
        pcgw_info = get_pcgamingwiki_anti_cheat(name)

        # --- Forum/Reddit search links ---
        reddit_link = make_reddit_search_link(name)
        steam_forum_link = make_steam_forum_search_link(appid)

        status, error = "No EULA found", ""

        if eula_for_ai and not quota_exceeded and openai_enabled:
            status, error = analyze_eula_with_ai(eula_for_ai)
            if "Quota exceeded" in status or "insufficient_quota" in error:
                print("OpenAI quota exceeded. Stopping further AI analysis, but will continue dumping EULAs.")
                quota_exceeded = True # Don't break, just skip AI analysis
        elif not openai_enabled:
            status, error = "Skipped (no API key)", ""

        # ---- ENHANCED DUMP: Add findings summary to EULA dump ----
        with open(EULA_DUMP_FILE, "a", encoding="utf-8") as f:
            f.write(f"-------------------- {name} --------------------\n")
            f.write(f"AppID: {appid}\nInstall Path: {path}\n")
            f.write(f"EULA Found: {'Yes' if eula_sources else 'No'}\n")
            f.write(f"Privacy Assessment: {status}\n")
            f.write(f"Anti-Cheat/Privacy Scan: {anti_cheat_scan}\n")
            f.write(f"PCGamingWiki Info: {pcgw_info}\n")
            f.write(f"Reddit Search: {reddit_link}\n")
            f.write(f"Steam Forum Search: {steam_forum_link}\n")
            if error:
                f.write(f"Error/Notes: {error}\n")
            f.write("\n")
            if eula_sources:
                for src, txt, match_type in eula_sources:
                    f.write(f"[Source: {src} | Match: {match_type}]\n")
                    cleaned_txt = clean_eula_text(txt)
                    f.write(cleaned_txt)
                    f.write("\n\n")
            else:
                f.write("[No EULA found]\n\n")

        results.append([
            appid, name, path, "Yes" if eula_sources else "No", status,
            anti_cheat_scan, pcgw_info, reddit_link, steam_forum_link, error
        ])

        time.sleep(API_DELAY)

    # Write results to CSV
    with open(OUTPUT_FILE, "w", newline='', encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "App ID", "Game Name", "Install Path", "EULA Found", "Privacy Assessment",
            "Anti-Cheat/Privacy Scan", "PCGamingWiki Info", "Reddit Search", "Steam Forum Search", "Error/Notes"
        ])
        writer.writerows(results)

    print(f"\nDone! Results saved to {OUTPUT_FILE}")
    print(f"All EULAs dumped to {EULA_DUMP_FILE}")

if __name__ == "__main__":
    main()
