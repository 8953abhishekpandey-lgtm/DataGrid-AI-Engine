"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  config.py  —  DataGrid Intelligence · Central Configuration               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Yahan pe saare constants, paths aur environment variables rakhe gaye hain. ║
║  Koi bhi setting change karni ho toh SIRF IS FILE ko edit karo.            ║
║                                                                             ║
║  AI Engine Priority (order mein):                                           ║
║    1. Claude  (Anthropic)  — PRIMARY AI                                     ║
║    2. Gemini  (Google)     — FALLBACK AI                                    ║
║    3. Rule-Based NL→SQL    — FINAL FALLBACK (koi API key nahi chahiye)     ║
║                                                                             ║
║  ⚠️  IMPORTANT CHANGES:                                                     ║
║    • Ollama support HATA DIYA GAYA — sirf cloud AI + offline rules         ║
║    • Sirf .parquet files upload hoti hain — Excel/CSV support NAHI         ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os            # OS environment variables padhne ke liye standard library
from pathlib import Path  # File paths handle karne ke liye (Windows/Linux dono pe kaam kare)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: ENV FILE LOADER
# .env file se API keys aur settings load karne ka function
# python-dotenv install ho ya na ho — dono case handle karta hai
# ══════════════════════════════════════════════════════════════════════════════

def _load_env_file(env_path: Path) -> int:
    """
    .env file ko manually parse karke os.environ mein set karta hai.
    Ye function tab bhi kaam karta hai jab python-dotenv install na ho.

    Supported .env format:
        KEY=value            # simple value
        KEY="value"          # double quotes
        KEY='value'          # single quotes
        # ye ek comment hai  # comment lines ignore hoti hain
        KEY=value # comment  # inline comment bhi handle hota hai

    Returns: int — kitni variables successfully load hui
    """
    if not env_path.exists():          # agar .env file hi disk pe nahi hai
        return 0                       # kuch nahi karna, 0 return karo

    # File bytes mein padho, phir UTF-8 mein decode karo
    # utf-8-sig use karo taki BOM (Byte Order Mark) automatically remove ho
    text = env_path.read_bytes().decode("utf-8-sig", errors="replace")

    loaded = 0  # successfully load hui variables ka counter
    for raw_line in text.splitlines():         # file ki har ek line ke liye iterate karo
        line = raw_line.strip()                # line ke shuru aur end se whitespace hatao

        # In teeno conditions mein line skip karo:
        if not line:                           # blank line hai
            continue
        if line.startswith("#"):               # comment line hai (# se shuru hoti hai)
            continue
        if "=" not in line:                    # KEY=VALUE format nahi hai
            continue

        key, _, value = line.partition("=")    # pehla = sign pe split karo
        # partition() safe hai — agar multiple = hain toh bhi pehle pe split karta hai
        key   = key.strip()                    # key ke aaspaas se whitespace hatao
        value = value.strip()                  # value ke aaspaas se whitespace hatao

        # Inline comments handle karo — lekin sirf unquoted values ke liye
        # Example: KEY=abc123 # ye comment hai → value = "abc123"
        if not (value.startswith('"') or value.startswith("'")):
            value = value.split("#")[0].strip()    # # ke baad sab hata do

        # Surrounding quotes hatao agar value quotes mein wrapped hai
        # Example: KEY="hello" → KEY=hello, KEY='world' → KEY=world
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]                # pehla aur aakhri character hatao

        if key:                                # key khali nahi honi chahiye
            os.environ[key] = value            # environment variable set karo
            loaded += 1                        # counter increment karo

    return loaded  # total loaded count return karo


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: BASE PATH & .ENV LOADING
# Project root path define karo aur .env file load karo
# ══════════════════════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).parent
# ^ __file__ = is config.py file ka path
# .parent = us file ki parent directory = project root folder
# Example: /home/user/datagrid/config.py → BASE_DIR = /home/user/datagrid/

# Pehle python-dotenv se try karo (agar installed hai)
try:
    from dotenv import load_dotenv                          # dotenv library import karo
    load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)
    # override=True matlab: .env ki values existing env vars ko overwrite kar sakti hain
except ImportError:
    pass  # dotenv nahi hai toh silently skip karo — manual loader handle karega

# Chahe dotenv ho ya na ho, manually bhi load karo (double safety ke liye)
_load_env_file(BASE_DIR / ".env")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: API KEYS
# KABHI BHI yahan hardcode mat karo! Hamesha .env file mein rakho.
#
# .env file example:
#   ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxxxxxxx
#   GEMINI_API_KEY=AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxxx
# ══════════════════════════════════════════════════════════════════════════════

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
# ^ os.environ.get(key, default) — key nahi mili toh empty string default hai
# .strip() se accidentally copy-paste hue spaces remove hote hain

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
# ^ Gemini ka API key — Google AI Studio se milta hai

# Startup pe console pe API key status print karo
# Security ke liye sirf last 4 characters dikhate hain (masking)
if ANTHROPIC_API_KEY:
    print(f"  [env] ANTHROPIC_API_KEY loaded  (...{ANTHROPIC_API_KEY[-4:]})")
    # [-4:] matlab string ke last 4 characters
else:
    print("  [env] No ANTHROPIC_API_KEY — Claude engine disabled")

if GEMINI_API_KEY:
    print(f"  [env] GEMINI_API_KEY loaded      (...{GEMINI_API_KEY[-4:]})")
else:
    print("  [env] No GEMINI_API_KEY — Gemini engine disabled")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: AI MODEL NAMES
# Kaunsa exact model version use karna hai
# .env file se override kar sakte ho specific versions ke liye
# ══════════════════════════════════════════════════════════════════════════════

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6").strip()
# ^ Claude ka default model — claude-sonnet-4-6 best balance hai speed aur quality ka
# Override karna ho toh .env mein: ANTHROPIC_MODEL=claude-opus-4-6

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash").strip()
# ^ Gemini ka default model — flash version fast hai aur free tier mein zyada quota hai

# ══════════════════════════════════════════════════════════════════════════════
# OLLAMA — HATA DIYA GAYA HAI
# Pehle local Ollama AI support tha, ab remove kar diya gaya hai.
# Reason: Maintenance complexity + users ke paas GPU nahi hoti.
# Agar future mein chahiye: ai_engines.py mein _call_ollama() wapas add karo
# aur yahan OLLAMA_HOST = "http://localhost:11434" add karo.
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: FILE & STORAGE PATHS
# Saari important directories kahan hain
# ══════════════════════════════════════════════════════════════════════════════

UPLOAD_DIR   = BASE_DIR / "uploads"
# ^ Uploaded parquet files yahan save hoti hain
# / operator Path objects ke saath path join karta hai

MEMORY_FILE  = BASE_DIR / "learned_queries.json"
# ^ Learned query patterns ka main storage file
# Ye file train.py se manually aur app se automatically update hoti hai

TRAINING_LOG = BASE_DIR / "training_log.jsonl"
# ^ Har training action ka append-only log
# .jsonl = JSON Lines format, ek line = ek JSON object
# Ye file kabhi overwrite nahi hoti, sirf append hoti hai

SSL_DIR = BASE_DIR / ".ssl"
# ^ SSL certificates yahan store hote hain (HTTPS ke liye)
# .ssl folder hidden hai (dot se shuru hota hai)

UPLOAD_DIR.mkdir(exist_ok=True)
# ^ uploads/ folder create karo agar exist nahi karta
# exist_ok=True matlab: agar folder already hai toh error mat do


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: LIMITS & CONSTRAINTS
# System performance aur stability ke liye limits
# ══════════════════════════════════════════════════════════════════════════════

MAX_FILES = 200
# ^ Ek saath maximum kitne files (tables) loaded ho sakte hain
# Zyada files = zyada RAM usage — apne server ke hisaab se adjust karo

MAX_FILE_SIZE = 500 * 1024 * 1024
# ^ Maximum single file size = 500 MB
# 500 * 1024 * 1024 = 524,288,000 bytes = ~500 MB

MAX_ROWS_DISPLAY = 10_000
# ^ Ek query ke result mein maximum kitne rows UI ko bhejna hai
# _ (underscore) Python mein number separator hai (readability ke liye)
# Zyada rows = browser slow ho jaata hai — 10,000 usually enough hai


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7: SUPPORTED FILE FORMATS
# ⚠️  IMPORTANT: SIRF PARQUET FILES ACCEPT HOTI HAIN!
#
# Agar koi format add karna ho:
#   1. Yahan uncomment karo
#   2. file_handlers.py mein load function add karo
#   3. index.html mein accept attribute update karo
# ══════════════════════════════════════════════════════════════════════════════

SUPPORTED_FORMATS: dict[str, str] = {
    # File Extension → Handler Type
    # "tabular" = SQL queries chalti hain (DuckDB mein load hoti hai)
    # "document" = AI se discuss kar sakte hain (SQL nahi chalta)

    ".parquet": "tabular",      # ✅ PARQUET — only accepted tabular format
                                # Binary columnar format, bahut fast hai large datasets ke liye
                                # pandas.read_parquet() se load hota hai

    # ── DISABLED FORMATS (uncomment to enable, but also update file_handlers.py) ──
    # ".csv"    : "tabular",    # ❌ DISABLED — CSV files accept nahi hoti
    # ".tsv"    : "tabular",    # ❌ DISABLED — Tab-separated values
    # ".xlsx"   : "tabular",    # ❌ DISABLED — Excel 2007+ format
    # ".xls"    : "tabular",    # ❌ DISABLED — Old Excel format
    # ".json"   : "detect",     # ❌ DISABLED — JSON (auto-detect table/document)

    # ── DOCUMENT FORMATS (still supported for AI reference) ──
    ".pdf":  "document",        # ✅ PDF documents (text extraction hoti hai)
    ".docx": "document",        # ✅ Word documents (paragraphs extract hote hain)
    ".txt":  "document",        # ✅ Plain text files
    ".md":   "document",        # ✅ Markdown files
}

# User-friendly message ke liye accepted formats ki list
ACCEPTED_TABULAR_EXTENSIONS = [
    ext for ext, fmt in SUPPORTED_FORMATS.items() if fmt == "tabular"
]
# ^ = [".parquet"] — abhi sirf parquet hai
# Agar future mein CSV add karoge toh automatically yahan bhi aa jaayega


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8: UI ENGINE BADGES
# Frontend pe kaunsa engine use ho raha hai uska display text
# ══════════════════════════════════════════════════════════════════════════════

ENGINE_BADGES: dict[str, str] = {
    "claude": f"🤖 Claude AI · {ANTHROPIC_MODEL}",    # Claude engine
    "gemini": f"✨ Gemini · {GEMINI_MODEL}",           # Gemini engine
    # "ollama" key HATA DIYA — Ollama support nahi raha
    "nlsql":  "⚙️ Rule-Based SQL Engine",              # Offline fallback engine
    "sql":    "💾 Direct SQL",                         # User ka direct SQL
}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9: ERROR DETECTION KEYWORDS
# Jab AI engine fail kare toh error type detect karne ke liye keywords
# In keywords mein se koi bhi error message mein mila → quota/auth error
# → automatically next available engine pe switch hoga
# ══════════════════════════════════════════════════════════════════════════════

QUOTA_ERRORS = (
    "429",                  # HTTP Status: Too Many Requests (rate limit)
    "quota",                # "quota exceeded" type messages
    "billing",              # Billing/payment issue
    "resource_exhausted",   # Google API ka quota message
    "rate limit",           # Rate limiting
    "exceeded",             # Koi bhi limit exceed hui
    "403",                  # HTTP Status: Forbidden (permission issue)
    "401",                  # HTTP Status: Unauthorized (invalid key)
    "overloaded",           # Server overloaded hai (Claude ka message)
    "credit",               # Credit/balance issue
    "insufficient_quota",   # Gemini ka quota message
)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10: QUERY MEMORY SETTINGS
# Learned patterns ka behaviour aur quality control
# ══════════════════════════════════════════════════════════════════════════════

MEMORY_MATCH_THRESHOLD = 0.78
# ^ Minimum similarity score (0 to 1) pattern recall ke liye
# 0.78 = 78% similarity chahiye
# Zyada karo (e.g. 0.90) = sirf exact matches → kam recall
# Kam karo (e.g. 0.60) = loose matching → galat patterns match hone ka risk

MEMORY_MAX_PATTERNS = 1000
# ^ Maximum patterns stored karne ki limit
# Jab limit exceed ho, bottom patterns automatically prune hote hain
# Locked patterns (count ≥ 200) kabhi nahi hatenge

MANUAL_TRAIN_BOOST = 20
# ^ Jab manually train karo toh starting count kitna hoga
# count 1-19  = auto-learned (low trust)
# count 20-199 = manually trained (high trust)
# count 200+   = locked (never pruned, never overwritten)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 11: MULTI-FILE UNION SETTINGS
# Jab multiple parquet files upload hoti hain toh unhe kaise union karo
# ══════════════════════════════════════════════════════════════════════════════

MIN_FILES_FOR_UNION = 1
# ^ Kitni files pe union view banana shuru karo
# 1 = pehli file se hi union view banta hai
# Ye ensure karta hai ki "show all data" type queries SABI files pe chalein
# Increase karo agar union views performance issue create kar rahe hain


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 12: STARTUP BANNER FUNCTION
# App start hone pe terminal pe information print karta hai
# ══════════════════════════════════════════════════════════════════════════════

def print_banner() -> None:
    """
    App start hone pe console pe informational banner print karta hai.
    Dikhata hai: API keys status, models, limits, accepted formats.
    """
    print("=" * 64)
    print("  ⚡ DataGrid Intelligence — Smart Meter & Electricity AI")
    print("-" * 64)

    # Claude API key ki status
    if ANTHROPIC_API_KEY:
        print(f"  🤖 Primary AI    : Claude ({ANTHROPIC_MODEL})  (...{ANTHROPIC_API_KEY[-4:]})")
    else:
        print("  ❌ Claude         : No ANTHROPIC_API_KEY in .env")

    # Gemini API key ki status
    if GEMINI_API_KEY:
        print(f"  ✨ Fallback AI   : Gemini ({GEMINI_MODEL}) (...{GEMINI_API_KEY[-4:]})")
    else:
        print("  ❌ Gemini         : No GEMINI_API_KEY in .env")

    # Offline engine — hamesha available
    print(f"  ⚙️  Final Fallback : Learned queries + Rule-Based NL→SQL (offline)")
    print("-" * 64)
    print(f"  📁 Upload         : Parquet (.parquet) ONLY — CSV/Excel NAHI")
    print(f"  📊 Max Rows/Query : {MAX_ROWS_DISPLAY:,}")                # :, = thousands separator
    print(f"  📦 Max File Size  : {MAX_FILE_SIZE // (1024 * 1024)} MB") # bytes → MB convert
    print(f"  🗂️  Max Files      : {MAX_FILES}")
    print("=" * 64)