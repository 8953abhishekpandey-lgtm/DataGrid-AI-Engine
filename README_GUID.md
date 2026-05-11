# ⚡ DataGrid Intelligence — Complete Documentation
### Smart Meter & Electricity Analytics Platform
> **Ye documentation har kisi ke liye likhi gayi hai — chahe aapko coding aati ho ya bilkul na aati ho.**

---

## 📋 Table of Contents

1. [Ye System Kya Hai? (Bilkul Shuru Se Samjhein)](#1-ye-system-kya-hai)
2. [Bina API Key — Offline Mode Kaise Kaam Karta Hai](#2-offline-mode-api-key-ke-bina)
3. [API Key Ke Saath — AI Mode Kaise Kaam Karta Hai](#3-ai-mode-api-key-ke-saath)
4. [Vector Search — Naya Smart Memory System](#4-vector-search-naya-smart-memory)
5. [System Architecture (Poora Map)](#5-system-architecture)
6. [File-by-File Guide](#6-file-by-file-guide)
7. [Data Kaise Load Hoti Hai](#7-data-kaise-load-hoti-hai)
8. [Query Kaise Process Hoti Hai](#8-query-kaise-process-hoti-hai)
9. [Training System — System Ko Sikhana](#9-training-system)
10. [Chart System](#10-chart-system)
11. [Setup & Installation](#11-setup--installation)
12. [Configuration Reference](#12-configuration-reference)
13. [API Reference (Developers Ke Liye)](#13-api-reference)
14. [Training Guide (Practical Steps)](#14-training-guide)
15. [Troubleshooting — Problems Ka Hal](#15-troubleshooting)
16. [Quick Reference Card](#16-quick-reference-card)

---

## 1. Ye System Kya Hai?

### Ek Line Mein Samjhein
> **Aap apna electricity/meter data upload karo, phir seedha Hindi/English mein sawaal pucho — system khud SQL likhega, data dhundega, aur chart bana dega.**

### Socho Aise
Maan lijiye aapke paas ek Excel file hai jisme 50,000 meters ka data hai. Normally aapko SQL ya Python seekhni padti hai data dhundhne ke liye. Is system ke saath aap bas likh sakte ho:

```
"Kitne meters Active hain district-wise?"
"Top 10 consumers kaun hain?"
"HES type SMS wale saare meters dikhao"
```

System khud samjhega, SQL likhega, data dhundhega, aur chart bana dega.

### Kya Kya Kar Sakta Hai?

| Feature | Kya Matlab Hai |
|---------|----------------|
| **Natural Language Query** | Hindi/English mein sawaal pucho, system SQL khud likhega |
| **Offline Mode** | Internet ya API key NAHI chahiye — fir bhi kaam karta hai |
| **AI Mode** | Claude ya Gemini AI se bahut zyada accurate answers |
| **Memory (Sikhna)** | Jab koi query sahi kaam kare, system use yaad rakh leta hai |
| **Vector Search** | "Active meters" aur "working meters" ko same manta hai (smart matching) |
| **Multi-File** | Ek saath kai files query kar sakte ho |
| **Charts** | Automatically bar, line, pie charts banta hai |
| **HTTPS** | Secure connection, password protected nahi |

### Kya Upload Kar Sakte Hain?

```
✅ DATA FILES (Query ke liye):
   .parquet  — Ye apna main data format hai (Excel se convert karo)

✅ DOCUMENTS (AI se discuss karne ke liye):
   .pdf      — Reports, manuals
   .docx     — Word documents
   .txt      — Plain text
   .md       — Notes

❌ YE NAHI CHALEGA:
   .csv, .xlsx, .xls (pehle .parquet mein convert karo)
```

> **💡 Excel ko Parquet mein kaise convert karein?**
> ```python
> import pandas as pd
> df = pd.read_excel("mera_data.xlsx")
> df.to_parquet("mera_data.parquet", index=False)
> ```
> Bas itna likhne se convert ho jaata hai.

---

## 2. Offline Mode (API Key Ke Bina)

### Ye Mode Kab Use Hota Hai?
Jab `.env` file mein koi API key nahi hoti — ya API key galat hoti hai — system automatically offline mode mein chala jaata hai. **Koi internet bhi nahi chahiye.**

### Offline Mode Mein System Kya Karta Hai?

Think of it as **3 drawers** jisme system answers dhundhta hai, ek ke baad ek:

```
Sawaal aaya: "Show active meters"
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  DRAWER 1 — VECTOR SEARCH (Semantic Memory)             │
│  ChromaDB + sentence-transformers (local, offline)      │
│  "Active meters" ko "Working meters" se match kar leta  │
│  ─────────────────────────────────────────────────────  │
│  → Match mila? → Us pattern ka SQL use karo ✓           │
│  → Nahi mila? → Agla drawer                             │
└─────────────────────────────────────────────────────────┘
         │ (agar nahi mila)
         ▼
┌─────────────────────────────────────────────────────────┐
│  DRAWER 2 — EXACT/FUZZY MEMORY (SequenceMatcher)        │
│  learned_queries.json se pattern dhundho                │
│  "Show active meters" vs "show active meter" 96% match  │
│  ─────────────────────────────────────────────────────  │
│  → Match mila (78%+)? → Us pattern ka SQL use karo ✓    │
│  → Nahi mila? → Agla drawer                             │
└─────────────────────────────────────────────────────────┘
         │ (agar nahi mila)
         ▼
┌─────────────────────────────────────────────────────────┐
│  DRAWER 3 — RULE ENGINE (nl_sql.py)                     │
│  Keywords se SQL generate karo                          │
│  "count" + "by" + "status" → GROUP BY query             │
│  "top 10" → LIMIT 10 ORDER BY ... DESC                  │
│  ─────────────────────────────────────────────────────  │
│  → Kuch na kuch SQL generate hoga ✓                     │
│  → Nahi bana? → "Could not generate SQL" error          │
└─────────────────────────────────────────────────────────┘
```

### Offline Mode Ki Limitations

| Kya Kar Sakta Hai | Kya Nahi Kar Sakta |
|--------------------|--------------------|
| Simple counts, sums, averages | Complex multi-step analysis |
| Filter by column value | Context-aware follow-up questions |
| Top N / Bottom N queries | "Why" type questions |
| Group by columns | Intelligent insights |
| Master JOIN (7 tables) | Document summarization |

### Offline Mode Improve Kaise Karein?

**Jitna zyada train karoge, utna zyada offline kaam karega:**
```bash
# Ek sahi pattern sikhao system ko
python train.py add \
  --text "active meters by district" \
  --sql "SELECT \"DISTRICT\", COUNT(*) FROM Consumer WHERE \"Status\"='Active' GROUP BY \"DISTRICT\""
```
Ab ye sawaal offline mein bhi perfectly kaam karega.

---

## 3. AI Mode (API Key Ke Saath)

### Ye Mode Kab Active Hota Hai?

Jab `.env` file mein ye lines hoti hain:
```bash
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxx   # Claude ke liye
GEMINI_API_KEY=AIzaSyxxxxxxxxxx              # Gemini ke liye (backup)
```

### AI Mode Mein System Kya Karta Hai?

```
Sawaal aaya: "Show me all meters where HES type is SMS and status is Active"
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  STEP 1 — SYSTEM PROMPT BANAO                           │
│  AI ko context do:                                      │
│   • Kaunsi tables hain (Equipment, Consumer, etc.)      │
│   • Kaunsa data loaded hai (rows, columns, samples)     │
│   • SQL rules (DuckDB ka syntax)                        │
│   • Conversation history (agle sawaalon ke liye)        │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  STEP 2 — CLAUDE API CALL                               │
│  Model: claude-sonnet-4-6                               │
│  Claude samjhega sawaal + schema + rules                │
│   → SQL likhega                                         │
│   → Chart type suggest karega                           │
│   → Insights likhega                                    │
│   → Follow-up questions suggest karega                  │
└─────────────────────────────────────────────────────────┘
         │ (agar Claude fail kare — quota/network)
         ▼
┌─────────────────────────────────────────────────────────┐
│  STEP 3 — GEMINI FALLBACK (agar Claude fail kare)       │
│  Bilkul same process, sirf Gemini API use hoti hai      │
└─────────────────────────────────────────────────────────┘
         │ (agar dono fail karein)
         ▼
┌─────────────────────────────────────────────────────────┐
│  STEP 4 — OFFLINE FALLBACK                              │
│  Dono AI fail → Vector Search → Memory → Rule Engine    │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  STEP 5 — SQL EXECUTE + SAVE TO MEMORY                  │
│  AI ka SQL → DuckDB run → DataFrame                     │
│  Agar result aaya → automatically memory mein save      │
│  (Next time same sawaal pe AI nahi chahiye!)            │
└─────────────────────────────────────────────────────────┘
```

### AI Mode Ki Khaasiyatein

```
✅ Kya Karta Hai AI Mode:

1. Complex SQL likhta hai automatically
   "meters jinke GPS coordinates 28-29 latitude ke beech hain" →
   SELECT * FROM ... WHERE "GPS_LAT" BETWEEN 28 AND 29

2. 7-table JOIN automatically karta hai
   "Meter no. CRYT123 ka consumer naam kya hai?" →
   Equipment JOIN Consumer JOIN ... complex query khud likhta hai

3. Context yaad rakhta hai (conversation history)
   Aap: "Show active meters"
   AI:  "Found 1,234 active meters"
   Aap: "Inhe district-wise group karo"  ← AI jaanta hai "inho" = active meters

4. Insights deta hai
   "In 3 districts mein meters highest failure rate hai"

5. Follow-up questions suggest karta hai
   "Kya aap by HES type bhi dekhna chahenge?"
```

### AI Errors Kab Aate Hain aur Kya Hota Hai?

| Error | Matlab | System Kya Karta Hai |
|-------|--------|----------------------|
| 429 Too Many Requests | Quota khatam | Gemini try karta hai |
| 401 Unauthorized | Galat API key | Gemini try karta hai |
| Network timeout | Internet problem | Gemini try karta hai |
| Dono fail | Dono API fail | Offline mode use karta hai |

---

## 4. Vector Search — Naya Smart Memory System

### Ye Kya Hai? (Bilkul Simple Explanation)

**Purana system (SequenceMatcher):**
- "Active meters dikhao" ← stored pattern
- "Show active meters" → 85% match ✓
- "Working meters list karo" → 32% match ✗ (MISS!)

**Naya system (Vector/Semantic Search):**
- "Active meters dikhao" ← stored pattern
- "Show active meters" → 91% similarity ✓
- "Working meters list karo" → 82% similarity ✓ (**MATCH! Same matlab hai!**)

> **Seedha bolo:** Vector search *matlab* samjhta hai, sirf words nahi. Jaise aap Hindi mein pucho aur system English mein stored pattern se match kare.

### Ye Kaise Kaam Karta Hai (Without Coding)?

```
Aapka sawaal: "Working meters list karo"
                      │
                      ▼
           ┌──────────────────────┐
           │  Sentence Transformer │
           │  (AI model, ~80MB)   │
           │  Ye model sirf ek     │
           │  baar download hota  │
           │  hai, fir offline    │
           └──────────┬───────────┘
                      │
                      ▼
           Numbers mein convert:
           [0.23, -0.91, 0.44, ...]
           (384 numbers ka array)
                      │
                      ▼
           ┌──────────────────────┐
           │  ChromaDB            │
           │  (local database)    │
           │  Stored patterns ke  │
           │  numbers se compare  │
           └──────────┬───────────┘
                      │
                      ▼
           "Active meters dikhao" → similarity 82%
           "List equipment"       → similarity 45%
           "Consumer count"       → similarity 12%
                      │
                      ▼
           82% > 72% threshold → MATCH! ✓
           SQL use karo: SELECT * FROM Equipment WHERE "Status"='Active'
```

### Vector Search Ke Liye Setup

```bash
# Ek baar chalao — model download hoga (~80MB)
pip install chromadb sentence-transformers

# Pehli baar app start hone pe automatically:
# 1. Model download hoga (internet chahiye sirf ek baar)
# 2. Saare existing patterns automatically index ho jaayenge
# 3. Aage se fully offline kaam karega
```

### Agar Install Na Karein?

Koi problem nahi. System bilkul pehle ki tarah kaam karta rahega. Sirf ye ek line print hogi:

```
[vector] chromadb / sentence-transformers not installed — using SequenceMatcher only.
To enable semantic search: pip install chromadb sentence-transformers
```

### Documents Bhi Index Hote Hain

Jab aap koi PDF ya DOCX upload karte ho:

```
report.pdf upload kiya
        │
        ▼
Text extract hota hai (pypdf se)
        │
        ▼
400 words ke chunks mein divide hota hai
(overlap 50 words — sentences miss na hon)
        │
        ▼
ChromaDB mein store hota hai
        │
        ▼
Jab AI ko document ke baare mein pucho:
System sirf relevant chunks AI ko deta hai
(poora document nahi — token limit bachata hai)
```

---

## 5. System Architecture

### Poori System Ka Map

```
┌─────────────────────────────────────────────────────────────────┐
│                    AAPKA BROWSER                                │
│              (Chrome / Firefox / Edge)                          │
│    • Question type karo                                         │
│    • Charts dekho                                               │
│    • Tables dekho                                               │
└──────────────────────┬──────────────────────────────────────────┘
                       │  WebSocket (real-time) + HTTP (files)
                       │  HTTPS pe encrypted
┌──────────────────────▼──────────────────────────────────────────┐
│                     app.py (FastAPI Server)                     │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────────┐  │
│  │  HTTP Routes   │  │   WebSocket    │  │  File Upload     │  │
│  │  /status       │  │   Handler      │  │  /upload         │  │
│  │  /tables       │  │   (real-time   │  │  Parquet → DB    │  │
│  │  /patterns     │  │    chat)       │  │  PDF/DOCX → text │  │
│  │  /train        │  │                │  │  + Vector index  │  │
│  └────────────────┘  └────────────────┘  └──────────────────┘  │
└─────┬──────────┬──────────┬──────────┬───────────────────────────┘
      │          │          │          │
      ▼          ▼          ▼          ▼
┌──────────┐ ┌────────┐ ┌────────┐ ┌──────────────────────────────┐
│ai_engines│ │db_engine│ │query_  │ │query_memory.py               │
│          │ │        │ │runner  │ │                               │
│• Claude  │ │• DuckDB│ │• SQL   │ │  Layer 1: Vector Search      │
│• Gemini  │ │• Union │ │  exec  │ │  (ChromaDB — offline)        │
│• Fallback│ │  views │ │• Chart │ │                               │
│          │ │• Parquet│ │  gen  │ │  Layer 2: SequenceMatcher    │
└──────────┘ └────────┘ └────────┘ │  (fuzzy string match)        │
      │          │          │      │                               │
      ▼          ▼          ▼      │  Layer 3: Rule Engine        │
┌──────────────────────────────┐   │  (nl_sql.py)                 │
│  config.py (All Settings)    │   └──────────────────────────────┘
│  chart_utils.py (Charts)     │
│  file_handlers.py (Parsing)  │
└──────────────────────────────┘
```

### Data Flow — Ek Query Ka Safar

```
Step 1: Aap browser mein likhte hain:
        "Show meter count by district"
              ↓
Step 2: WebSocket se app.py ko jaata hai
              ↓
Step 3: API key hai?
        ├── YES (AI Mode):
        │     Claude/Gemini ko system prompt + sawaal bheja
        │     Claude SQL likhta hai:
        │     SELECT "DISTRICT", COUNT(*) FROM Consumer
        │     GROUP BY "DISTRICT" ORDER BY count DESC
        │         ↓
        └── NO (Offline Mode):
              Vector Search → Memory → Rule Engine
              Rule Engine: "count" + "by" + "district" → GROUP BY
                  ↓
Step 4: SQL → DuckDB mein execute hota hai
        Result: pandas DataFrame (table)
              ↓
Step 5: DataFrame → auto_chart() → Plotly bar chart
              ↓
Step 6: memory.learn() → pattern save hota hai
        (Next time ye sawaal bina AI ke kaam karega)
              ↓
Step 7: Browser ko bheja:
        • Answer text
        • Bar chart (interactive)
        • Data table
        • SQL jo use hua
        • Follow-up suggestions
```

---

## 6. File-by-File Guide

### 📁 Project Ki Saari Files

```
datagrid/
│
├── app.py              ← ENTRY POINT — Server yahan se start hota hai
├── ai_engines.py       ← Claude + Gemini ko call karta hai
├── config.py           ← Saari settings yahan hain
├── db_engine.py        ← Database ka kaam (DuckDB)
├── file_handlers.py    ← Upload file ko parse karta hai
├── nl_sql.py           ← Rule-based NL to SQL (offline)
├── query_memory.py     ← Patterns yaad rakhna + Vector search (NEW)
├── query_runner.py     ← SQL chalana + chart banana
├── chart_utils.py      ← Charts banana (Plotly)
├── train.py            ← Command line training tool
│
├── .env                ← API keys (KABHI Git pe mat daalo!)
├── learned_queries.json ← Ye file patterns store karti hai
├── training_log.jsonl  ← Har training ka record
│
├── uploads/            ← Upload ki hui files yahan jaati hain
├── .ssl/               ← SSL certificates (auto-banta hai)
└── .chroma_db/         ← Vector database (auto-banta hai, NEW)
```

---

### 📄 app.py — Main Server (Entry Point)

**Isko koi directly nahi chhuta — ye server chalata hai.**

Ye file manage karti hai:
- Browser se aayi requests handle karna (HTTP)
- Real-time chat connection (WebSocket)
- File upload/download
- Document ko vector index mein daalna (**NEW**)

**Important change (NEW):**
Jab aap koi PDF/DOCX upload karte ho, ab ye bhi hota hai:
```
PDF upload → text extract → 400-word chunks → ChromaDB mein store
                                               (offline document search)
```

Jab delete karte ho:
```
Document delete → ChromaDB se bhi chunks remove hote hain
```

---

### 📄 ai_engines.py — AI Ka Kaam

**Ye file Claude aur Gemini API ko call karti hai.**

```
Priority Order:
1. Claude (claude-sonnet-4-6) ← PRIMARY
2. Gemini (gemini-2.0-flash)  ← FALLBACK
3. Offline Rule Engine        ← FINAL FALLBACK
```

AI ko kya bheja jaata hai (System Prompt):
```
┌────────────────────────────────────────┐
│ "Tu DataGrid Intelligence hai, expert  │
│  electricity data analyst..."          │
│                                        │
│ Ye tables hain:                        │
│ Equipment: ID, Meter_ID, Status...     │
│ Consumer: ID, DISTRICT, REGION...      │
│ ...                                    │
│                                        │
│ Ye data loaded hai:                    │
│ equipment: 50,000 rows, columns: ...   │
│                                        │
│ SQL rules:                             │
│ - Table names unquoted CamelCase       │
│ - Column names double-quoted           │
│ - No semicolons                        │
│                                        │
│ SIRF JSON mein answer do:              │
│ {"answer": "...", "sql": "...", ...}   │
└────────────────────────────────────────┘
```

---

### 📄 config.py — Saari Settings

**Agar kuch change karna ho, sirf ye file kholna hai.**

```python
# AI Models (change karna ho to .env mein likho)
ANTHROPIC_MODEL = "claude-sonnet-4-6"   # Claude version
GEMINI_MODEL    = "gemini-2.0-flash"    # Gemini version

# File Limits
MAX_FILE_SIZE = 500 MB      # Ek file ka max size
MAX_FILES     = 200         # Ek saath kitni files
MAX_ROWS      = 10,000      # Query mein max rows

# Memory/Training
MEMORY_MATCH_THRESHOLD = 0.78   # 78% match chahiye pattern recall ke liye
MEMORY_MAX_PATTERNS    = 1000   # Max 1000 patterns store honge
MANUAL_TRAIN_BOOST     = 20     # Manual training ka starting count
```

---

### 📄 db_engine.py — Database Ka Kaam

**Ye file parquet files ko in-memory database mein manage karti hai.**

Ye DuckDB use karta hai — ek super-fast in-memory SQL database. Koi alag server install nahi karna padta.

**Multi-File Union System:**
```
Scenario: Aapne 3 monthly files upload ki, sabke same columns hain

jan_2024.parquet → columns: [Meter_ID, Status, Reading]
feb_2024.parquet → columns: [Meter_ID, Status, Reading]
mar_2024.parquet → columns: [Meter_ID, Status, Reading]

System automatically banata hai:
  _union_abc123 = jan + feb + mar UNION ALL
  _all_data     = same as above (shortcut naam)

Ab query karo:
  SELECT * FROM "_all_data"  ← Teeno files ka data ek saath!
```

**SQL Rules Jo Samajhna Zaroori Hai:**
```sql
-- ✅ SAHI — Table naam without quotes
SELECT * FROM Equipment
SELECT * FROM Consumer

-- ❌ GALAT — Table naam with quotes
SELECT * FROM "Equipment"   -- Ye fail karega!

-- ✅ SAHI — Column naam with double quotes
SELECT "Meter_ID", "Status" FROM Equipment

-- ❌ GALAT — Column naam without quotes
SELECT Meter_ID FROM Equipment  -- Case-sensitive fail ho sakta hai
```

---

### 📄 query_memory.py — Patterns Ka Database (Updated)

**Ye file system ka "yaaddasht" hai.**

3-Layer Search (Updated):
```
Layer 1: Vector Search (NEW)
  ChromaDB + sentence-transformers
  Semantic similarity — matlab dhundhta hai words nahi
  Offline after first install

Layer 2: SequenceMatcher (Original)
  String similarity score
  78%+ match chahiye
  Fast aur reliable

Layer 3: Rule Engine (nl_sql.py)
  Keywords se SQL banata hai
  Hamesha kuch na kuch deta hai
```

**Pattern Ka Format (learned_queries.json mein):**
```json
{
  "text":        "meter count by district",
  "sql":         "SELECT \"DISTRICT\", COUNT(*) FROM Consumer GROUP BY \"DISTRICT\"",
  "chart_type":  "bar",
  "count":       45,
  "trained":     true,
  "explanation": "District-wise meter count"
}
```

**Trust Levels:**
```
Count  1-9   → Auto-seekha (low trust) — overwrite ho sakta hai
Count 10-19  → Confirm hua (used many times)
Count 20-199 → Manually trained (high trust)
Count 200+   → LOCKED — kabhi nahi hatega, kabhi overwrite nahi hoga
```

---

### 📄 nl_sql.py — Rule Engine (Offline SQL Generator)

**Ye file bina AI ke natural language ko SQL mein convert karti hai.**

Ye keywords aur patterns se kaam karta hai:

```
"count meters by status"
↓ Parsing:
  agg = "count" → COUNT()
  group = "status" → GROUP BY "Status"
  table = "meters" → Equipment
↓ SQL:
  SELECT "Status", COUNT(*) AS count_val
  FROM Equipment
  GROUP BY "Status"
  ORDER BY count_val DESC
```

**Master JOIN (7 Tables Ek Saath):**
Ye magic query hai jo automatically chalti hai jab aap "meter details", "show all meters", ya "consumer info" bolte ho:
```sql
SELECT E.Meter_ID, MM.Meter_Type, HM.HES_CD, C.Utility_ID...
FROM Equipment E
JOIN DevLoc_Device_Link DDL ON E.ID = DDL.EquipmentId
JOIN Device_Location DL ON DL.ID = DDL.DeviceLocationId
JOIN ConsumerDevLocLink CDL ON DDL.DeviceLocationId = CDL.DeviceLocationId
JOIN Consumer C ON C.ID = CDL.ConsumerID
JOIN Material_Master MM ON E.Material_ID = MM.Utility_ID
LEFT JOIN HES_MASTER HM ON E.HES_ID = HM.ID
```

---

### 📄 train.py — Training Tool

**Ye command-line tool hai system ko better banana ke liye.**

Jab system galat answer de, aap isko sahi answer sikha sakte ho:
```bash
python train.py add \
  --text "active meters count" \
  --sql "SELECT COUNT(*) FROM Equipment WHERE \"Status\"='Active'"
```

---

## 7. Data Kaise Load Hoti Hai

### Step-by-Step Upload Process

```
Aap file choose karte ho browser mein
          │
          ▼
app.py /upload endpoint
          │
          ▼
Checks:
  ✓ Extension supported? (.parquet / .pdf / etc.)
  ✓ Size < 500MB?
  ✓ Total files < 200?
          │
          ▼
file_handlers.process_upload()
          │
    ┌─────┴──────┐
    │            │
 Parquet      Document (PDF/DOCX/TXT)
    │            │
    ▼            ▼
pandas.       Text extract karo
read_parquet  (pypdf / python-docx)
    │            │
    ▼            ▼
DuckDB mein    _documents dict mein store
register       +
    │          ChromaDB mein chunks index (NEW)
    ▼            │
Union views     ▼
update         Search available ho jaata hai
```

### Filename Cleanup

```
"Q1-2024 Meter Data.parquet"  →  "q1_2024_meter_data"  (table naam)
"123data.parquet"             →  "t_123data"            (digit se start nahi ho sakta)
"../../etc/passwd.parquet"    →  "passwd"               (path traversal block)
```

---

## 8. Query Kaise Process Hoti Hai

### Complete Flow (AI Mode)

```
Browser: "Kitne meters active hain?"
                    │
                    ▼ WebSocket
app.py websocket_handler()
                    │
         ┌──────────┴──────────┐
         │  API key set hai?   │
         └──────────┬──────────┘
                    │
        ┌───────────┴───────────┐
       YES                      NO
        │                       │
        ▼                       ▼
call_ai_async()           run_offline()
(Claude/Gemini)           (Vector→Memory→Rules)
        │                       │
        ▼                       │
AI Response:                    │
{                               │
  "sql": "SELECT...",           │
  "answer": "1,234 active...",  │
  "chart_type": "bar",          │
  "insights": "...",            │
  "follow_ups": [...]           │
}                               │
        │                       │
        └──────────┬────────────┘
                   │
                   ▼
        run_ai_result() / result dict
                   │
                   ▼
        db.execute(sql) → DataFrame
                   │
                   ▼
        generate_chart() → Plotly JSON
                   │
                   ▼
        memory.learn() → Save to memory + Vector store
                   │
                   ▼
        WebSocket → Browser
        {answer, sql, chart, table_data, follow_ups}
```

### Result Jo Browser Mein Aata Hai

```json
{
  "type":        "result",
  "mode":        "ai",
  "answer":      "Found 1,234 active meters across 5 districts",
  "insights":    "Najafgarh district mein sabse zyada inactive meters hain",
  "follow_ups":  [
    "District-wise breakdown dikhao",
    "Inactive meters ki list kya hai?",
    "HES type wise count?"
  ],
  "sql":         "SELECT COUNT(*) FROM Equipment WHERE \"Status\"='Active'",
  "chart_type":  "bar",
  "chart":       "... Plotly JSON ...",
  "table_data":  [{...}, {...}],
  "engine":      "claude",
  "engine_badge": "🤖 Claude AI · claude-sonnet-4-6"
}
```

---

## 9. Training System

### System Ko Kaise Sikhate Hain?

**Simple words mein:** Jab system galat jawab de, aap usse sahi jawab de sakte ho. Wo yaad rakh leta hai.

### 3 Tarike Training Ke

**Tarika 1: Automatic (System Khud Seekhta Hai)**
```
AI se query karo → Sahi result aaya → System automatically save karta hai
Aapko kuch nahi karna
Count = 1 se start hota hai
```

**Tarika 2: Manual Training (Command Line)**
```bash
# Galat result aaya "meters by district" pe
# Sahi SQL likho
python train.py add \
  --text "meters by district" \
  --sql "SELECT \"DISTRICT\", COUNT(*) AS meter_count FROM Consumer GROUP BY \"DISTRICT\" ORDER BY meter_count DESC"
```

**Tarika 3: Bulk Training (Bahut Saare Ek Saath)**
```bash
# questions.txt banao, ek sawaal har line pe
python train.py ai-batch --file questions.txt
# AI se har sawaal ka SQL generate karwao aur save karo
```

### Pattern Trust Levels Samjhein

```
Naya auto-learned pattern:
   Count = 1 (low trust)
   ↓ Use karo
   Count = 2
   ↓ Use karo
   Count = 5 (getting reliable)
   ↓
   Count = 10 (confirmed, reliable)

Manually train karo:
   Count = 20 (instantly trusted)
   ↓
   Lock karo:
   Count = 200 (PERMANENT — never deleted)
```

### Critical Patterns Ko Lock Karo

```bash
# Ye patterns KABHI delete nahi honge
python train.py lock --text "show all meter details"
python train.py lock --text "count meters by district"
python train.py lock --text "active meters list"
```

### Pattern Ko Test Karo (Check Karo Kaam Kar Raha Hai)

```bash
python train.py test --text "meter count district wise"
# Output:
# ✅ Matched pattern (confidence: 0.92)
#    Original: "count meters by district"
#    SQL: SELECT "DISTRICT", COUNT(*)...
```

### Training Statistics Dekho

```bash
python train.py stats
# Output:
# Total patterns   : 156
# Manually trained : 42
# Auto-learned     : 114
# Locked (≥200)   : 15
# Vector store     : ENABLED (156 patterns, 340 doc chunks)
```

---

## 10. Chart System

### Kaunsa Chart Kab Banta Hai?

| Chart Type | Kab Use Hota Hai | Example |
|-----------|-----------------|---------|
| **Bar** | Categories compare karna | District-wise count |
| **Line** | Time ke saath trend | Monthly readings |
| **Area** | Cumulative values | Running total |
| **Pie** | Percentage breakdown | Device type split |
| **Scatter** | Do numbers ka relation | LAT vs LONG |
| **Histogram** | Distribution dekho | Reading frequency |
| **Heatmap** | 2D matrix | District × Status |
| **Table** | Koi chart fit nahi | Raw data |

### Auto-Chart Logic

```
DataFrame aaya
    ↓
Numeric columns hain? AND Categorical columns hain? AND 1-500 rows?
    ├── YES → Bar chart automatically
    └── NO  → Table dikhao (koi chart nahi)
```

### Chart Colors

```
Primary   : #0f7c90  (Teal)
Secondary : #f5a623  (Orange)
Tertiary  : #248a52  (Green)
Quaternary: #6b5bd3  (Purple)
Quinary   : #c2413d  (Red)
```

---

## 11. Setup & Installation

### Prerequisites (Kya Chahiye)

```
✓ Python 3.9 ya usse zyada
✓ pip (Python package manager)
✓ Internet (sirf install ke time)
✓ 500MB disk space (model download ke liye)
```

### Complete Installation (Step by Step)

```bash
# Step 1: Project folder mein jao
cd datagrid/

# Step 2: Core packages install karo
pip install fastapi "uvicorn[standard]" duckdb pandas pyarrow plotly

# Step 3: AI packages (optional but recommended)
pip install anthropic google-generativeai

# Step 4: Document support
pip install pypdf python-docx

# Step 5: SSL ke liye
pip install cryptography

# Step 6: Vector search (HIGHLY RECOMMENDED — offline semantic search)
pip install chromadb sentence-transformers
# Note: Pehli baar ~80MB model download hoga

# Step 7: .env file banao
# (Notepad mein banao, .env naam se save karo)
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxxxxxxx
GEMINI_API_KEY=AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxxx

# Step 8: Server start karo
python app.py

# Step 9: Browser mein kholna
# https://localhost:8899
# Warning aayegi SSL ke liye — "Advanced" → "Proceed" click karo
```

### Kya Bina API Key Ke Bhi Install Kar Sakte Hain?

**Haan!** Sirf ye kafi hai:
```bash
pip install fastapi "uvicorn[standard]" duckdb pandas pyarrow plotly
pip install chromadb sentence-transformers   # Recommended for better offline
python app.py
```
.env file mein kuch nahi daalte — system offline mode mein chalega.

### Excel Data Ko Parquet Mein Convert Karo

```python
# Python mein chalao (sirf ek baar)
import pandas as pd

# Excel se
df = pd.read_excel("mera_data.xlsx")
df.to_parquet("mera_data.parquet", index=False)

# CSV se
df = pd.read_csv("mera_data.csv")
df.to_parquet("mera_data.parquet", index=False)

print(f"Done! {len(df)} rows converted.")
```

---

## 12. Configuration Reference

### .env File (API Keys)

```bash
# .env file — project ke root folder mein banao
# KABHI GitHub ya kisi ke saath share mat karo!

ANTHROPIC_API_KEY=sk-ant-api03-...     # Claude AI
GEMINI_API_KEY=AIzaSy...               # Gemini AI (backup)

# Optional — model change karna ho to
ANTHROPIC_MODEL=claude-opus-4-6        # More powerful, slower, expensive
GEMINI_MODEL=gemini-2.0-pro            # Better quality
```

### config.py Ki Important Settings

```python
# AI Models
ANTHROPIC_MODEL = "claude-sonnet-4-6"  # Best balance of speed & quality
GEMINI_MODEL    = "gemini-2.0-flash"   # Fast, free tier mein zyada quota

# Limits
MAX_FILES        = 200     # Zyada files = zyada RAM
MAX_FILE_SIZE    = 500 MB  # Server pe space ke hisaab se ghata sakte ho
MAX_ROWS_DISPLAY = 10,000  # Browser slow na ho isliye

# Memory
MEMORY_MATCH_THRESHOLD = 0.78  # 0.90 karo = sirf exact matches
                                # 0.65 karo = loose matches (zyada results)
MEMORY_MAX_PATTERNS    = 1000  # Patterns ki limit
MANUAL_TRAIN_BOOST     = 20    # Manual training ka starting count
```

---

## 13. API Reference (Developers Ke Liye)

### REST Endpoints

#### GET /status — System Ki Current State
```json
{
  "ai_enabled": true,
  "ai_engine": "claude",
  "engine_badge": "🤖 Claude AI · claude-sonnet-4-6",
  "claude_key": true,
  "gemini_key": false,
  "tables": [...],
  "documents": ["report"],
  "pattern_count": 156,
  "vector": {
    "enabled": true,
    "query_patterns": 156,
    "doc_chunks": 340
  }
}
```

#### POST /upload — File Upload
```
Request: multipart/form-data
  file: <binary>

Response (parquet):
{
  "type": "table",
  "name": "jan_data",
  "rows": 15420,
  "columns": [...]
}

Response (document):
{
  "type": "document",
  "name": "report",
  "format": "PDF",
  "char_count": 25430
  // ChromaDB mein automatically index ho jaata hai
}
```

#### POST /train — Pattern Add Karo
```json
// Request
{
  "text": "count meters by status",
  "sql": "SELECT \"Status\", COUNT(*) FROM Equipment GROUP BY \"Status\"",
  "chart_type": "bar",
  "lock": false
}

// Response
{"ok": true, "result": "added", "total": 157}
```

### WebSocket Protocol

```javascript
// Connect karo
const ws = new WebSocket("wss://localhost:8899/ws")

// Query bhejo
ws.send(JSON.stringify({
  action: "query",
  text: "show all active meters",
  target_tables: ["equipment"]   // optional — scope limit karo
}))

// Responses:
// 1. Processing indicator
{type: "thinking"}

// 2. Result
{
  type: "result",
  mode: "ai",          // "ai" | "learned" | "rules" | "vector"
  answer: "...",
  sql: "SELECT ...",
  chart: "...",        // Plotly JSON
  table_data: [...],
  engine_badge: "🤖 Claude AI · claude-sonnet-4-6"
}

// 3. Error
{type: "error", text: "..."}
```

---

## 14. Training Guide (Practical Steps)

### Kab Train Karein?

```
System ne galat answer diya
         ↓
Sahi SQL khud likhein (ya AI se likhwaein)
         ↓
train.py add se save karein
         ↓
test se verify karein
         ↓
Zaroori ho to lock karein
```

### Practical Examples

**Example 1: District-wise Count**
```bash
python train.py add \
  --text "meter count by district" \
  --sql "SELECT \"DISTRICT\", COUNT(*) AS meter_count FROM Consumer GROUP BY \"DISTRICT\" ORDER BY meter_count DESC" \
  --chart "bar" \
  --explanation "District-wise total meter count"
```

**Example 2: Specific Status Filter**
```bash
python train.py add \
  --text "show inactive meters" \
  --sql "SELECT \"Meter_ID\", \"Status\", \"DISTRICT\" FROM Equipment WHERE \"Status\" = 'Inactive' LIMIT 10000" \
  --chart "table"
```

**Example 3: Parameter-based Pattern (ID ke saath)**
```bash
# {meter_id} automatically fill hoga user ke input se
python train.py add \
  --text "details for meter {meter_id}" \
  --sql "SELECT * FROM Equipment WHERE \"Meter_ID\" = '{meter_id}'"

# Test karo:
python train.py test --text "details for meter CRYT3000602"
# → SQL: SELECT * FROM Equipment WHERE "Meter_ID" = 'CRYT3000602'
```

**Example 4: Complex Join Query**
```bash
python train.py add \
  --text "consumer name for meter number" \
  --sql "SELECT E.\"Meter_ID\", C.\"FIRST_NAME\", C.\"Utility_ID\" FROM Equipment E JOIN ConsumerDevLocLink CDL ON CDL.DeviceLocationId = (SELECT DeviceLocationId FROM DevLoc_Device_Link WHERE EquipmentId = E.ID LIMIT 1) JOIN Consumer C ON C.ID = CDL.ConsumerID WHERE E.\"Meter_ID\" = '{meter_id}'"
```

### SQL Validate Karo Pehle Save Karne Se

```bash
# Parquet files directly load karke test karo
python train.py test-sql \
  --sql "SELECT \"DISTRICT\", COUNT(*) FROM Consumer GROUP BY \"DISTRICT\"" \
  --files uploads/consumer.parquet

# Output:
# ✅ Query succeeded: 12 rows
#    DISTRICT  count
# 0  Najafgarh    245
# 1  Dwarka      189
# ...
```

### Regular Maintenance

```bash
# Har hafte:
python train.py stats           # Kitne patterns hain, kitne trained

# Har mahine:
python train.py purge-auto      # Count < 20 wale auto-learned remove karo
python train.py export --file backup_$(date +%Y%m%d).json  # Backup

# Naye server pe migrate karte waqt:
python train.py import --file backup.json
```

---

## 15. Troubleshooting — Problems Ka Hal

### Problem: "No data loaded"

```
Matlab: Koi parquet file load nahi hui
Solutions:
  1. Upload karo: Browser mein "+" button se .parquet file upload karo
  2. Parquet file sahi hai? Check karo:
     python -c "import pandas as pd; df=pd.read_parquet('file.parquet'); print(df.shape)"
  3. CSV hai to convert karo pehle (Section 11 dekho)
```

### Problem: AI Answer Nahi De Raha

```
Possible causes:
  1. API key galat hai
     → .env file check karo
     → Key copy-paste sahi hai? Extra spaces nahi?

  2. Quota khatam
     → Anthropic/Google dashboard check karo
     → Gemini key add karo as backup

  3. Network issue
     → Internet connection check karo
     → System offline mode mein switch ho jaayega automatically
```

### Problem: SQL Error Aa Raha Hai

```
Error: "relation does not exist"
Solution:
  → Table naam check karo (Equipment, Consumer — CamelCase)
  → Quotes remove karo table naam se

Error: "column does not exist"
Solution:
  → Column naam double-quote mein hona chahiye: "Meter_ID"
  → Case-sensitive hai — "meter_id" nahi, "Meter_ID" hoga

Debug tool:
  python train.py test-sql --sql "YOUR SQL HERE" --files uploads/data.parquet
```

### Problem: Vector Search Kaam Nahi Kar Raha

```
Check 1: Install hai?
  pip install chromadb sentence-transformers

Check 2: Model download hua?
  First time pe ~80MB download hota hai — internet chahiye
  ~/.cache/huggingface/ mein check karo

Check 3: .chroma_db folder exist karta hai?
  ls -la .chroma_db/

Check 4: Patterns rebuild karo
  python -c "from query_memory import memory; print(memory.stats())"
```

### Problem: Pattern Recall Nahi Ho Raha

```
Step 1: Test karo
  python train.py test --text "your query"

Step 2: Closest patterns dekho (output mein dikhega)

Step 3: Threshold check karo
  config.py mein MEMORY_MATCH_THRESHOLD = 0.78
  Thoda kam karo: 0.70

Step 4: Manually train karo
  python train.py add --text "..." --sql "..."
```

### Problem: Port Already In Use (8899)

```bash
# Linux/Mac:
lsof -i :8899
kill -9 <PID>

# Windows:
netstat -ano | findstr 8899
taskkill /PID <PID_NUMBER> /F
```

### Problem: SSL Certificate Warning Browser Mein

```
Ye normal hai! Self-signed certificate hai.
Fix karo:
  1. Browser mein "Advanced" button click karo
  2. "Proceed to localhost (unsafe)" click karo
  3. Ek baar karne ke baad browser yaad rakh leta hai

Production mein: Let's Encrypt se free SSL certificate lo
```

### Performance Tips

```
Slow queries:
  → SQL mein LIMIT lagao: "top 500 meters" poocho
  → Large files: Sirf necessary columns select karo

High memory usage:
  → MAX_FILES config.py mein kam karo
  → Large parquet files ko filter karke chhoti banaao

Too many patterns (slow search):
  → python train.py purge-auto
  → MEMORY_MAX_PATTERNS = 500 karo config.py mein
```

---

## 16. Quick Reference Card

```
╔═══════════════════════════════════════════════════════════════╗
║          DATAGRID INTELLIGENCE — QUICK REFERENCE             ║
╠═══════════════════════════════════════════════════════════════╣
║  Start:  python app.py                                       ║
║  Open:   https://localhost:8899                              ║
╠═══════════════════════════════════════════════════════════════╣
║  FILES:                                                      ║
║    ✅ .parquet (data)    ✅ .pdf/.docx/.txt (documents)      ║
║    ❌ .csv / .xlsx (pehle .parquet mein convert karo)        ║
╠═══════════════════════════════════════════════════════════════╣
║  QUERY FLOW:                                                 ║
║    API Key Set? → Claude → Gemini → Offline                  ║
║    No API Key?  → Vector Search → Memory → Rules             ║
╠═══════════════════════════════════════════════════════════════╣
║  TRAINING COMMANDS:                                          ║
║    Add:    python train.py add --text "..." --sql "..."      ║
║    Test:   python train.py test --text "..."                 ║
║    Lock:   python train.py lock --text "..."                 ║
║    Stats:  python train.py stats                             ║
║    Backup: python train.py export --file backup.json         ║
╠═══════════════════════════════════════════════════════════════╣
║  SQL RULES (DuckDB):                                         ║
║    Tables:  Equipment  Consumer  (unquoted CamelCase)        ║
║    Columns: "Meter_ID"  "Status"  (double-quoted)            ║
║    No semicolons at end of SQL                               ║
╠═══════════════════════════════════════════════════════════════╣
║  PATTERN TRUST:                                              ║
║    Count  1-9  = Auto-learned (low trust)                    ║
║    Count 20+   = Manually trained (trusted)                  ║
║    Count 200+  = LOCKED (permanent, never deleted)           ║
╠═══════════════════════════════════════════════════════════════╣
║  VECTOR SEARCH SETUP (recommended):                          ║
║    pip install chromadb sentence-transformers                ║
║    (80MB download once, then fully offline)                  ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## 📊 Summary: Offline vs AI Mode

| Feature | Offline Mode (No API Key) | AI Mode (API Key Set) |
|---------|--------------------------|----------------------|
| **Kaam Karta Hai?** | ✅ Haan | ✅ Haan |
| **Internet Chahiye?** | ❌ Nahi | ✅ Haan (API calls ke liye) |
| **Simple Queries** | ✅ Perfectly | ✅ Perfectly |
| **Complex Joins** | ⚡ Sirf Master JOIN | ✅ Koi bhi |
| **Context Memory** | ❌ Nahi (har sawaal alag) | ✅ Haan (conversation) |
| **Insights** | ❌ Nahi | ✅ Haan |
| **Follow-up Qs** | ❌ Nahi | ✅ Haan |
| **Accuracy** | ⚡ Good (after training) | ✅ Excellent |
| **Speed** | ✅ Instant | ⚡ 2-5 seconds |
| **Cost** | ✅ Free | 💰 Per-query cost |
| **Vector Search** | ✅ With chromadb | ✅ With chromadb |
| **Document Q&A** | ⚡ Basic chunks | ✅ Full AI analysis |

> **Best Practice:** API key daalo, zyada queries karo → system sikhta jaayega → dhire dhire API ki zaroorat kam hoti jaayegi!

---

*Documentation last updated: 2025*
*Version: 2.0 — Vector Search Integration*
*Language: Hinglish (Hindi + English) for team clarity*