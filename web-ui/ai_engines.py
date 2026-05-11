"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  ai_engines.py  —  DataGrid Intelligence · AI Engine Callers               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Priority Order:                                                            ║
║    1. Claude (Anthropic) — PRIMARY AI                                      ║
║    2. Gemini (Google)    — FALLBACK AI                                     ║
║    3. Rule-Based NL→SQL  — OFFLINE FALLBACK (query_runner.py mein hai)    ║
║                                                                             ║
║  ⚠️  Ollama HATA DIYA GAYA — sirf cloud AI supported hai                   ║
║                                                                             ║
║  Har engine same dict format return karta hai:                             ║
║    {"answer": str, "sql": str|None, "chart_type": str,                    ║
║     "insights": str, "follow_ups": list, "_engine": str}                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import json                  # JSON parsing ke liye (AI response parse karna)
import os                    # API keys environment se padhne ke liye
import re                    # Regular expressions — JSON cleaning ke liye
from concurrent.futures import ThreadPoolExecutor  # Background threads ke liye
from typing import Optional  # Type hints ke liye

from config import (
    ANTHROPIC_MODEL,   # Claude ka model naam (e.g., "claude-sonnet-4-6")
    ENGINE_BADGES,     # UI mein engine labels
    GEMINI_MODEL,      # Gemini ka model naam
    QUOTA_ERRORS,      # Error keywords jo quota/auth issues indicate karte hain
)
from db_engine import db, normalize_sql_table_names  # Database engine aur SQL normalizer
from nl_sql import MASTER_JOIN_SQL_STRIPPED           # Master JOIN SQL template


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: THREAD POOL
# AI API calls blocking hoti hain, isliye background thread mein run karte hain
# taaki FastAPI ka async event loop block na ho
# ══════════════════════════════════════════════════════════════════════════════

EXECUTOR = ThreadPoolExecutor(max_workers=4)
# ^ max_workers=4 = ek saath maximum 4 AI API calls parallel chal sakti hain
# Zyada karo agar heavy traffic hai, kam karo agar server resources kam hain


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: SYSTEM PROMPT TEMPLATE
# AI ko context dene ke liye prompt template
# {variables} ko build karte waqt replace kiya jaata hai
# ══════════════════════════════════════════════════════════════════════════════

# Note: Triple-quoted f-string use nahi kar rahe kyunki {variables} confuse ho sakti hain
# Isliye .format() use karte hain manually
SYSTEM_PROMPT_TEMPLATE = """You are DataGrid Intelligence — expert AI data analyst for
electricity distribution, smart metering, and energy analytics.

DATABASE SCHEMA (DuckDB — unquoted table names; double-quote column names):
┌─────────────────────────────────────────────────────────────────────────────┐
│ Equipment          : ID, Utility_ID, Manufacturer_ID, Status, Meter_ID,    │
│                      Device_Type, Model_ID, StartDate, EndDate,             │
│                      Material_ID, HES_ID                                    │
│ Consumer           : ID, Utility_ID, Alt_Utility_ID, Cons_SEG, VIP,        │
│                      Essential_Service, SALUTATION, FIRST_NAME,             │
│                      Address1, Address2, Pin, DISTRICT, REGION,             │
│                      Utility_Office_Id, Status                              │
│ Device_Location    : ID, Utility_ID, Alt_Utility_ID, Description,          │
│                      Premise, GPS_LAT, GPS_LONG, Utility_Office_ID          │
│ DevLoc_Device_Link : ID, EquipmentId, DeviceLocationId,                    │
│                      ValidFromDate, ValidToDate                             │
│ ConsumerDevLocLink : ID, ConsumerID, DeviceLocationId,                     │
│                      ValidFromDate, ValidToDate                             │
│ Material_Master    : ID, Utility_ID, Description, Device_Type,             │
│                      Meter_Type, Functional_Class, No_of_Channels,         │
│                      IsActive, DIP                                          │
│ HES_MASTER         : ID, HES_CD, COMP_ID, HES_DESCRIPTION,                │
│                      IsActive, Data_Source, IsSmart                        │
└─────────────────────────────────────────────────────────────────────────────┘

MASTER JOIN (use for ANY meter/consumer details query):
{master_join}

MULTI-FILE UNION VIEWS (automatically created for same-schema Parquet files):
{union_views}
RULE: Jab user "all data" / "sab data" bole aur multiple files loaded hain,
      use "_all_data" view so ALL uploaded parquet files are queried together.

LOADED DATA:
{data_context}

SQL RULES:
1. Unquoted CamelCase table names: Equipment, Consumer, etc. (NOT "Equipment")
2. Double-quote column names: "Meter_ID", "Status", "GPS_LAT"
3. For meter/consumer details → ALWAYS use MASTER JOIN
4. For generic all-data queries with union views → use _all_data view
5. No trailing semicolons in SQL
6. No LIMIT when user asks for "all" data
7. For documents → synthesize from text, no SQL needed

RESPOND ONLY WITH VALID JSON — no markdown fences, no extra text:
{{"answer": "Clear answer with newlines for formatting.",
  "sql": "SELECT ... (no semicolon) or null if no SQL needed",
  "chart_type": "bar|line|pie|scatter|histogram|area|table",
  "insights": "1-2 domain insight sentences.",
  "follow_ups": ["Relevant question 1", "Question 2", "Question 3"]}}
"""


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: SYSTEM PROMPT BUILDER
# Runtime pe system prompt mein actual data context inject karta hai
# ══════════════════════════════════════════════════════════════════════════════

def _build_system_prompt() -> str:
    """
    AI ke liye complete system prompt banata hai.
    Union views aur current loaded data ki information inject karta hai.
    """
    # Union views ki information banao
    union_views = db.get_all_union_views()   # current union views ki list
    if union_views:
        # Har union view ke liye ek line banao
        uv_lines = "\n".join(
            f'  "{uv["view"]}" = UNION of {uv["count"]} parquet files: '
            f'{", ".join(uv["tables"])}'
            for uv in union_views
        )
        uv_lines += '\n  "_all_data" = sabse bade group ka alias'
    else:
        uv_lines = "  None loaded yet — single files only."
        # Koi union views nahi hain abhi

    # Template mein values inject karo
    return SYSTEM_PROMPT_TEMPLATE.format(
        master_join  = MASTER_JOIN_SQL_STRIPPED,  # standard 7-table JOIN SQL
        union_views  = uv_lines,                  # union views ki info
        data_context = db.build_data_context(include_doc_text=True),
        # ^ Loaded tables, columns, stats, sample rows, documents — sab kuch
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: RESPONSE PARSER
# AI ka raw text response parse karke Python dict mein convert karta hai
# ══════════════════════════════════════════════════════════════════════════════

def _parse_ai_response(raw: str) -> dict:
    """
    AI ke raw string response ko Python dict mein parse karta hai.

    Handle karta hai:
      - Clean JSON (normal case)
      - JSON with markdown code fences (```json ... ```)
      - JSON embedded in extra text (regex se dhundhta hai)
      - Complete parse failure (text as answer return karta hai)

    Returns: dict with keys: answer, sql, chart_type, insights, follow_ups
    """
    # Markdown code fences remove karo agar hain
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    # ^``` = line ki shuruat mein ``` (MULTILINE flag ke saath)
    # (?:json)? = optional "json" word after backticks
    # \s* = optional whitespace

    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE).strip()
    # Closing ``` remove karo, .strip() se edges clean karo

    # Direct JSON parse try karo
    try:
        return json.loads(raw)                # Standard JSON parsing
    except json.JSONDecodeError:
        pass  # JSON invalid hai, alternative try karo

    # JSON block dhundho text mein (agar extra text hai aaspaas)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    # \{.*\} = curly brace mein enclosed koi bhi text
    # re.DOTALL = . newlines ko bhi match kare (multiline JSON ke liye)
    if m:
        try:
            return json.loads(m.group())      # Found JSON parse karo
        except Exception:
            pass  # Ye bhi fail hua

    # Sab kuch fail hua — raw text ko answer ke roop mein return karo
    return {
        "answer":     raw,      # raw text as answer
        "sql":        None,     # koi SQL nahi
        "chart_type": "table",  # default chart type
        "insights":   "",       # koi insights nahi
        "follow_ups": [],       # koi follow-up nahi
    }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: CLAUDE ENGINE
# Anthropic Claude API caller
# ══════════════════════════════════════════════════════════════════════════════

def _call_claude(user_text: str, history: list, system_prompt: str) -> dict:
    """
    Anthropic Claude API ko call karta hai.

    Args:
        user_text:     user ka current question
        history:       conversation history (last 12 messages)
        system_prompt: AI ko context dene wala prompt

    Returns: parsed response dict

    Raises RuntimeError: agar API key nahi hai
    Raises anthropic.APIError: agar API call fail ho
    """
    import anthropic  # Anthropic SDK — sirf tab import karo jab zaroorat ho (lazy import)

    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY set nahi hai .env file mein")

    client = anthropic.Anthropic(api_key=key)
    # ^ Anthropic client create karo with API key

    # Conversation history format karo (Claude ke format mein)
    messages = [
        {
            "role":    "user" if m["role"] == "user" else "assistant",
            # Claude "user" aur "assistant" roles use karta hai
            "content": m["content"]  # message content as-is
        }
        for m in history[-12:]  # last 12 messages (context window ke liye)
    ]
    messages.append({"role": "user", "content": user_text})
    # Current user question add karo messages ke end mein

    # API call karo
    response = client.messages.create(
        model      = ANTHROPIC_MODEL,   # kaunsa Claude model use karna hai
        max_tokens = 3000,              # maximum response length
        system     = system_prompt,     # system prompt (role/context definition)
        messages   = messages,          # conversation history + current message
    )

    raw_text = response.content[0].text.strip()
    # response.content[0].text = pehla content block ka text
    # .strip() = extra whitespace remove karo

    return _parse_ai_response(raw_text)  # parse karke return karo


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: GEMINI ENGINE
# Google Gemini API caller (Claude ka fallback)
# ══════════════════════════════════════════════════════════════════════════════

def _call_gemini(user_text: str, history: list, system_prompt: str) -> dict:
    """
    Google Gemini API ko call karta hai.
    Claude fail hone pe ya API key nahi hone pe use hota hai.

    Gemini ka alag message format hai — user/model roles (assistant nahi)
    """
    import google.generativeai as genai  # Google AI SDK — lazy import

    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY set nahi hai .env file mein")

    genai.configure(api_key=key)  # SDK ko API key de do

    # Conversation history format karo (Gemini ke format mein)
    chat_history = [
        {
            "role":  "user" if m["role"] == "user" else "model",
            # Gemini "user" aur "model" roles use karta hai ("assistant" nahi)
            "parts": [{"text": m["content"]}]  # Gemini mein "parts" list chahiye
        }
        for m in history[-12:]  # last 12 messages
    ]

    # Gemini model create karo with settings
    model = genai.GenerativeModel(
        model_name         = GEMINI_MODEL,      # kaunsa Gemini version
        system_instruction = system_prompt,     # system prompt
        generation_config  = genai.GenerationConfig(
            temperature       = 0.1,    # Low temperature = deterministic outputs (zyada consistent)
            max_output_tokens = 3000,   # maximum response length
        ),
    )

    # Chat session start karo with history
    chat     = model.start_chat(history=chat_history)
    response = chat.send_message(user_text)  # current question bhejo

    return _parse_ai_response(response.text.strip())


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7: ENGINE DISPATCHER
# Priority order mein engines try karta hai — Claude → Gemini → Error
# ══════════════════════════════════════════════════════════════════════════════

# Current engine track karne ke liye module-level variable
# Ye mutable state hai isliye function ke andar global keyword use hoga
_current_engine: str = "nlsql"
# ^ Default: rule-based (jab tak koi AI key nahi)


def current_engine() -> str:
    """Currently active AI engine ka naam return karta hai.

    If no AI call has happened yet, this returns the preferred
    available engine based on configured API keys.
    """
    if _current_engine in {"claude", "gemini", "sql"}:
        return _current_engine

    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return "claude"

    if os.environ.get("GEMINI_API_KEY", "").strip():
        return "gemini"

    return _current_engine


def call_ai_sync(user_text: str, history: list) -> dict:
    """
    AI engine call karta hai — Claude pehle, phir Gemini fallback.
    SYNCHRONOUS function hai — background thread mein run hota hai.

    Flow:
      1. Claude try karo (agar ANTHROPIC_API_KEY hai)
      2. Fail hone pe Gemini try karo (agar GEMINI_API_KEY hai)
      3. Dono fail → RuntimeError raise karo
         → Caller (query_runner.py) offline mode use karega

    Returns: parsed response dict with "_engine" key
    Raises RuntimeError: agar dono engines fail ho
    """
    global _current_engine      # module-level variable modify karna hai

    system_prompt = _build_system_prompt()  # current data ka system prompt banao
    failures: list[str] = []                # failure reasons track karo

    def _try_engine(name: str, fn, key_env: str) -> Optional[dict]:
        """
        Ek engine try karo. Success pe result return karo, failure pe None.

        Args:
            name:    engine naam ("claude" ya "gemini")
            fn:      engine ka caller function
            key_env: environment variable naam jisme API key hai
        """
        global _current_engine

        # API key check karo pehle (unnecessary API call avoid karne ke liye)
        if key_env and not os.environ.get(key_env, "").strip():
            failures.append(f"{name}: {key_env} environment variable set nahi hai")
            return None  # Key nahi hai, skip karo

        try:
            result          = fn(user_text, history, system_prompt)  # engine call karo
            _current_engine = name  # successful engine track karo

            result["_engine"] = name  # response mein engine naam add karo

            # AI-generated SQL ko normalize karo (quoted table names fix karo)
            if result.get("sql"):
                result["sql"] = normalize_sql_table_names(result["sql"])

            print(f"  [AI] {name} engine successful ✓")  # success log karo
            return result  # result return karo

        except Exception as e:
            err   = str(e).lower()  # error message lowercase mein

            # Error type determine karo
            label = "quota/auth error" if any(kw in err for kw in QUOTA_ERRORS) else "error"
            print(f"  [AI] {name} {label} — next engine try kar raha hai: {str(e)[:80]}")
            # Partial error message print karo ([:80] = max 80 chars)

            failures.append(f"{name}: {label} — {str(e)[:120]}")
            return None  # Fail hua, None return karo

    # Priority order mein engines try karo
    result = (
        _try_engine("claude", _call_claude, "ANTHROPIC_API_KEY") or
        # ^ Claude pehle try karo
        # or ke saath: agar pehla None return kare toh doosra try hota hai
        _try_engine("gemini", _call_gemini, "GEMINI_API_KEY")
        # ^ Claude fail hone pe Gemini try karo
    )
    # NOTE: Ollama yahan SE HATAYA GAYA — pehle teen engines the, ab do hain

    if result:
        return result  # Koi ek engine success hua

    # Dono engines fail ho gaye — detailed error message banao
    failure_text = "\n".join(f"• {item}" for item in failures) or "• koi response nahi aaya"
    raise RuntimeError(
        f"Saare AI engines fail ho gaye:\n{failure_text}\n"
        "Rule-based offline engine use hoga."
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8: ASYNC WRAPPER
# FastAPI async context mein blocking AI calls run karne ke liye
# ══════════════════════════════════════════════════════════════════════════════

async def call_ai_async(user_text: str, history: list) -> dict:
    """
    call_ai_sync() ka async wrapper.

    Kyo zaroorat hai:
      - FastAPI async hai (non-blocking event loop use karta hai)
      - AI API calls blocking hain (response aane tak wait karta hai)
      - Blocking call ko async context mein directly call karo toh
        event loop block ho jaata hai — koi aur request handle nahi hogi
      - Solution: run_in_executor() background thread mein run karta hai
        event loop block nahi hota

    Args:
        user_text: user ka question
        history:   conversation history

    Returns: AI response dict
    """
    import asyncio  # Python async library

    loop = asyncio.get_event_loop()
    # ^ Current event loop lo

    return await loop.run_in_executor(
        EXECUTOR,       # Thread pool executor (upar define kiya gaya)
        call_ai_sync,   # Function jo background thread mein run hoga
        user_text,      # Argument 1
        history,        # Argument 2
    )
    # run_in_executor: call_ai_sync ko background thread mein run karo
    # await: background thread complete hone tak wait karo (event loop block nahi hota)