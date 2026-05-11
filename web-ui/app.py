"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  app.py  —  DataGrid Intelligence · FastAPI Main Server                    ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Ye file poore application ka ENTRY POINT hai.                             ║
║  Sirf slim entry point hai — heavy logic alag modules mein hai.            ║
║                                                                             ║
║  Server start karo: python app.py                                          ║
║  Browser mein kholo: https://localhost:8899                                ║
║                                                                             ║
║  Module structure:                                                          ║
║    config.py        — Saari settings aur constants                         ║
║    ai_engines.py    — Claude + Gemini API callers                          ║
║    db_engine.py     — DuckDB + Parquet management                          ║
║    file_handlers.py — Upload file processors                               ║
║    query_memory.py  — Learned query patterns storage + Vector Search       ║
║    query_runner.py  — SQL execution pipeline                               ║
║    chart_utils.py   — Plotly chart generator                               ║
║                                                                             ║
║  Static files (frontend):                                                  ║
║    index.html  — Main UI (HTML structure only)                             ║
║    static/style.css — All CSS styling                                      ║
║    static/app.js    — All JavaScript logic                                 ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library Imports ───────────────────────────────────────────────────
import os           # Environment variables padhne ke liye (API keys, etc.)
import subprocess   # OpenSSL command run karne ke liye (SSL cert generate)
import tempfile     # Temporary files banane ke liye (CSV export ke liye)
from pathlib import Path  # File paths handle karne ke liye (OS-independent)

# ── FastAPI Imports ────────────────────────────────────────────────────────────
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── Config PEHLE load karo — ye environment variables set karta hai ────────────
from config import (
    ENGINE_BADGES,
    MAX_FILE_SIZE,
    MAX_FILES,
    MAX_ROWS_DISPLAY,
    SUPPORTED_FORMATS,
    UPLOAD_DIR,
    SSL_DIR,
    print_banner,
)

# ── Application-specific Imports ───────────────────────────────────────────────
from ai_engines import call_ai_async, current_engine
from db_engine import db
from file_handlers import process_upload, sanitize_table_name, secure_filename
from query_memory import memory, get_vector_memory
# get_vector_memory() → ChromaDB instance (None agar package install nahi hai)
from query_runner import run_ai_result, run_offline


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: APPLICATION SETUP
# ══════════════════════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).parent

app = FastAPI(title="DataGrid Intelligence")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: GLOBAL STATE
# ══════════════════════════════════════════════════════════════════════════════

_documents: dict[str, dict] = {}
# ^ {doc_name: {filename, text, format, size}}

_clients: list[WebSocket] = []
# ^ Connected WebSocket clients

_conversations: dict[int, list] = {}
# ^ {ws_id: [{role, content}, ...]} — per-client conversation history


def _has_cloud_key() -> bool:
    """Check karo ki koi cloud AI API key configured hai ya nahi."""
    return bool(
        os.environ.get("ANTHROPIC_API_KEY", "").strip() or
        os.environ.get("GEMINI_API_KEY", "").strip()
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: HTTP ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/")
async def index():
    """Root URL pe main HTML page serve karo."""
    return FileResponse(BASE_DIR / "static" / "index.html", media_type="text/html")


@app.get("/favicon.ico")
async def favicon():
    """Browser automatically /favicon.ico request karta hai."""
    return JSONResponse({}, status_code=204)


@app.get("/status")
async def status():
    """
    Application ki current state return karo.
    Frontend har refresh pe ye endpoint call karta hai.
    """
    # Vector store info bhi include karo
    vm = get_vector_memory()
    vector_status = {
        "enabled":        vm is not None,
        "query_patterns": vm._queries.count() if vm else 0,
        "doc_chunks":     vm._docs.count()    if vm else 0,
    } if vm is not None else {
        "enabled": False,
        "query_patterns": 0,
        "doc_chunks": 0,
    }

    # Table summary without large samples (to prevent Content-Length errors)
    tables_info = [
        {
            "name": name,
            "rows": len(df),
            "columns": db.table_columns.get(name, []),
        }
        for name, df in db.tables.items()
    ]

    return JSONResponse({
        "ai_enabled":    True,
        "ai_engine":     current_engine(),
        "engine_badge":  ENGINE_BADGES.get(current_engine(), current_engine()),
        "claude_key":    bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
        "gemini_key":    bool(os.environ.get("GEMINI_API_KEY", "").strip()),
        "tables":        tables_info,
        "documents":     list(_documents.keys()),
        "union_views":   db.get_all_union_views(),
        "pattern_count": len(memory.patterns),
        "max_rows":      MAX_ROWS_DISPLAY,
        "active_table":  db.active_table,
        "vector":        vector_status,
    })


@app.get("/tables")
async def list_tables():
    """Saare loaded tables ki detailed information return karo."""
    return JSONResponse(
        {
            name: {
                "rows":    len(df),
                "columns": db.table_columns.get(name, []),
                "sample":  db.serialize_rows(df.head(3), max_rows=3)
            }
            for name, df in db.tables.items()
        }
    )


@app.get("/patterns")
async def list_patterns():
    """
    Learned query patterns ki list return karo.
    stats() mein ab vector info bhi hoti hai.
    """
    return JSONResponse({
        "count":    len(memory.patterns),
        "stats":    memory.stats(),          # vector info automatically included
        "patterns": [
            {
                "text":       p["text"],
                "count":      p.get("count", 1),
                "chart_type": p.get("chart_type", "table"),
                "trained":    p.get("trained", False)
            }
            for p in memory.patterns[:100]
        ],
    })


@app.post("/train")
async def train_pattern(body: dict):
    """
    Ek naya learned pattern manually add ya update karo.

    Request body:
        text        — Natural language query (required)
        sql         — DuckDB SQL (required)
        explanation — Short description (optional)
        chart_type  — "bar"|"line"|"pie"|... (optional, default "table")
        table       — Associated table naam (optional)
        params      — SQL placeholders list (optional)
        lock        — True = count=200 (never pruned) (optional)
    """
    text  = (body.get("text") or "").strip()
    sql   = (body.get("sql")  or "").strip()

    if not text or not sql:
        return JSONResponse({"error": "text and sql are required"}, status_code=400)

    result = memory.add_training(
        text        = text,
        sql         = sql,
        explanation = body.get("explanation", ""),
        chart_type  = body.get("chart_type", "table"),
        table       = body.get("table", ""),
        params      = body.get("params"),
        lock        = body.get("lock", False),
    )
    # NOTE: add_training() automatically upserts into ChromaDB vector store
    return JSONResponse({
        "ok":     True,
        "result": result,
        "total":  len(memory.patterns)
    })


@app.delete("/train")
async def remove_pattern(body: dict):
    """
    Text ke basis pe ek pattern remove karo.
    Pattern ChromaDB vector store se bhi automatically remove hota hai.
    """
    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "text is required"}, status_code=400)

    removed = memory.remove_pattern(text)
    # remove_pattern() ChromaDB se bhi delete karta hai
    return JSONResponse({"ok": removed, "total": len(memory.patterns)})


@app.post("/train/import")
async def import_patterns(file: UploadFile = File(...)):
    """
    JSON file se bulk patterns import karo.
    Har pattern automatically vector store mein bhi add hota hai.
    """
    content  = await file.read()
    tmp_path = UPLOAD_DIR / f"_import_{file.filename}"
    tmp_path.write_bytes(content)

    try:
        added, updated = memory.import_patterns(tmp_path)
        return JSONResponse({
            "ok":      True,
            "added":   added,
            "updated": updated,
            "total":   len(memory.patterns)
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    finally:
        tmp_path.unlink(missing_ok=True)


@app.get("/train/export")
async def export_patterns():
    """Saare learned patterns ko JSON file ke roop mein download karo."""
    tmp   = UPLOAD_DIR / "_export_patterns.json"
    count = memory.export_patterns(tmp)
    return FileResponse(
        tmp,
        filename   = "learned_queries.json",
        media_type = "application/json"
    )


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    File upload endpoint.

    Accepted formats:
        TABULAR  : .parquet ONLY
        DOCUMENT : .pdf, .docx, .txt, .md

    NEW (Vector Memory):
        Document files upload hone pe automatically ChromaDB mein
        index hoti hain — semantic search ke liye.
    """
    ext = Path(file.filename or "").suffix.lower()

    if ext not in SUPPORTED_FORMATS:
        supported = ", ".join(sorted(SUPPORTED_FORMATS))
        return JSONResponse(
            {"error": f"Unsupported: {ext}. Supported: {supported}"},
            status_code=400
        )

    content = await file.read()

    if len(content) > MAX_FILE_SIZE:
        return JSONResponse(
            {"error": "File too large (max 500 MB)."},
            status_code=400
        )

    if len(db.tables) + len(_documents) >= MAX_FILES:
        return JSONResponse(
            {"error": f"Max {MAX_FILES} files. Remove one first."},
            status_code=400
        )

    safe_name = secure_filename(file.filename or "unnamed")
    file_path = UPLOAD_DIR / safe_name
    file_path.write_bytes(content)

    try:
        result = process_upload(file_path, safe_name)
    except Exception as e:
        file_path.unlink(missing_ok=True)
        return JSONResponse(
            {"error": f"Failed to process: {e}"},
            status_code=400
        )

    if result["type"] == "table":
        # Tabular file — DuckDB mein register karo
        db.register_table(result["name"], result["df"])

        return JSONResponse({
            "type":        "table",
            "name":        result["name"],
            "filename":    safe_name,
            "rows":        len(result["df"]),
            "columns":     db.table_columns.get(result["name"], []),
            "union_views": db.get_all_union_views(),
        })

    else:
        # Document file — _documents dict mein store karo
        doc_entry = {
            "filename": result["filename"],
            "text":     result["text"],
            "format":   result["format"],
            "size":     result["size"],
        }
        _documents[result["name"]] = doc_entry

        # ── NEW: Vector index mein add karo (semantic document search ke liye) ──
        vm = get_vector_memory()
        if vm:
            try:
                chunk_count = vm.add_document_chunks(
                    doc_name   = result["name"],
                    text       = result["text"],
                    chunk_size = 400,    # ~400 words per chunk
                    overlap    = 50,     # 50 words overlap between chunks
                )
                print(
                    f"  [app] Document '{result['name']}' → "
                    f"{chunk_count} chunks indexed in ChromaDB"
                )
            except Exception as e:
                # Vector indexing fail hona critical nahi hai — document still works
                print(f"  [app] Vector indexing failed for '{result['name']}' (non-fatal): {e}")
        else:
            print(
                f"  [app] Document '{result['name']}' uploaded "
                f"(vector indexing not available — install chromadb sentence-transformers)"
            )

        return JSONResponse({
            "type":       "document",
            "name":       result["name"],
            "filename":   safe_name,
            "format":     result["format"],
            "char_count": result["size"],
        })


@app.delete("/table/{name}")
async def delete_table(name: str):
    """Table ko application se remove karo."""
    if name not in db.tables:
        return JSONResponse({"error": "Table not found"}, status_code=404)

    db.unregister_table(name)

    for f in UPLOAD_DIR.iterdir():
        if sanitize_table_name(f.name) == name:
            f.unlink(missing_ok=True)
            break

    return JSONResponse({"ok": True, "union_views": db.get_all_union_views()})


@app.delete("/document/{name}")
async def delete_document(name: str):
    """
    Document ko application se remove karo.

    NEW (Vector Memory):
        Document ke saare vector chunks bhi ChromaDB se delete hote hain.
    """
    if name not in _documents:
        return JSONResponse({"error": "Document not found"}, status_code=404)

    doc = _documents.pop(name)

    # ── NEW: Vector store se document chunks bhi remove karo ──────────────────
    vm = get_vector_memory()
    if vm:
        try:
            vm.remove_document_chunks(name)
            print(f"  [app] Document '{name}' chunks removed from ChromaDB")
        except Exception as e:
            print(f"  [app] Vector chunk removal failed for '{name}' (non-fatal): {e}")

    # Associated file delete karo
    for f in UPLOAD_DIR.iterdir():
        if f.name == doc.get("filename"):
            f.unlink(missing_ok=True)
            break

    return JSONResponse({"ok": True})


@app.get("/export/{table_name}")
async def export_csv(table_name: str):
    """Table ka data CSV file ke roop mein download karo."""
    if table_name not in db.tables:
        return JSONResponse({"error": "Table not found"}, status_code=404)

    with tempfile.NamedTemporaryFile(
        mode    = "w",
        suffix  = ".csv",
        delete  = False,
        dir     = UPLOAD_DIR
    ) as f:
        db.tables[table_name].to_csv(f, index=False)
        tmp_path = Path(f.name)

    return FileResponse(
        tmp_path,
        filename   = f"{table_name}.csv",
        media_type = "text/csv"
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: WEBSOCKET HANDLER
# ══════════════════════════════════════════════════════════════════════════════

@app.websocket("/ws")
async def websocket_handler(ws: WebSocket):
    """
    WebSocket connection handler.

    Supported actions:
        query       — Natural language query execute karo
        set_active  — Active table change karo
        clear_memory — Conversation history clear karo
        execute_sql — Direct SQL execute karo

    Query execution priority:
        1. Cloud AI available (API key set hai)
           → Claude / Gemini → SQL execute → chart → save to memory + vector store
        2. No API key (offline mode)
           → Vector semantic search → Learned patterns → Rule-based NL→SQL
    """
    await ws.accept()
    _clients.append(ws)
    ws_id = id(ws)
    _conversations[ws_id] = []

    try:
        while True:
            data   = await ws.receive_json()
            action = data.get("action", "")

            # ── Action: QUERY ──────────────────────────────────────────────────
            if action == "query":
                text          = data.get("text", "").strip()
                target_tables = data.get("target_tables", [])

                if not text:
                    await ws.send_json({"type": "error", "text": "Please enter a question."})
                    continue

                if not db.tables and not _documents:
                    await ws.send_json({"type": "error", "text": "No data loaded. Upload files first."})
                    continue

                await ws.send_json({"type": "thinking"})

                try:
                    augmented = text
                    if target_tables:
                        augmented = f"[Query these tables: {', '.join(target_tables)}]\n{text}"

                    if not _has_cloud_key():
                        # ── OFFLINE MODE ───────────────────────────────────────
                        # Priority: Vector semantic search → Learned patterns → Rules
                        payload = run_offline(text, target_tables)
                    else:
                        # ── CLOUD AI MODE ──────────────────────────────────────
                        # Priority: Claude → Gemini → run_offline() fallback
                        try:
                            ai      = await call_ai_async(augmented, _conversations[ws_id])
                            payload = run_ai_result(ai, text, db.active_table)
                        except Exception as ai_err:
                            print(f"  [AI] All engines failed: {ai_err}")
                            payload = run_offline(text, target_tables)

                    # Conversation history update
                    _conversations[ws_id].append({"role": "user",      "content": text})
                    _conversations[ws_id].append({"role": "assistant",  "content": payload.get("answer", "")})

                    if len(_conversations[ws_id]) > 20:
                        _conversations[ws_id] = _conversations[ws_id][-20:]

                    await ws.send_json(payload)

                except Exception as e:
                    await ws.send_json({"type": "error", "text": str(e)})

            # ── Action: SET_ACTIVE ─────────────────────────────────────────────
            elif action == "set_active":
                table = data.get("table", "")
                if table in db.tables:
                    db.active_table = table
                    await ws.send_json({"type": "status", "text": f"Active table: {table}"})

            # ── Action: CLEAR_MEMORY ───────────────────────────────────────────
            elif action == "clear_memory":
                _conversations[ws_id] = []
                await ws.send_json({"type": "status", "text": "Conversation cleared."})

            # ── Action: EXECUTE_SQL ────────────────────────────────────────────
            elif action == "execute_sql":
                sql = data.get("sql", "").strip().rstrip(";")

                if not sql:
                    continue

                try:
                    result_df = db.execute(sql)

                    from chart_utils import auto_chart
                    chart_json = auto_chart(result_df, "Query Result")

                    await ws.send_json({
                        "type":        "result",
                        "mode":        "sql",
                        "answer":      f"Query executed: {len(result_df):,} rows",
                        "insights":    "",
                        "follow_ups":  [],
                        "sql":         sql,
                        "chart_type":  "bar" if chart_json else "table",
                        "chart":       chart_json,
                        "table_data":  db.serialize_rows(result_df),
                        "columns":     result_df.columns.tolist(),
                        "row_count":   len(result_df),
                        "engine":      "sql",
                        "engine_badge": "💾 Direct SQL",
                    })
                except Exception as e:
                    await ws.send_json({
                        "type": "error",
                        "text": str(e),
                        "sql":  sql
                    })

    except WebSocketDisconnect:
        pass

    finally:
        if ws in _clients:
            _clients.remove(ws)
        _conversations.pop(ws_id, None)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: SSL CERTIFICATE MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

def ensure_ssl_certs():
    """SSL certificates check karo ya generate karo."""
    cert = SSL_DIR / "cert.pem"
    key  = SSL_DIR / "key.pem"

    if cert.exists() and key.exists():
        return cert, key

    SSL_DIR.mkdir(exist_ok=True)

    # Method 1: OpenSSL command line
    try:
        subprocess.run([
            "openssl", "req", "-x509",
            "-newkey", "rsa:2048",
            "-keyout", str(key),
            "-out", str(cert),
            "-days", "365",
            "-nodes",
            "-subj", "/CN=localhost",
        ], check=True, capture_output=True)

    except Exception:
        # Method 2: Python cryptography library
        try:
            from cryptography import x509
            from cryptography.x509.oid import NameOID
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            import datetime, ipaddress

            k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            s = i = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
            c = (
                x509.CertificateBuilder()
                .subject_name(s)
                .issuer_name(i)
                .public_key(k.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.datetime.utcnow())
                .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
                .add_extension(
                    x509.SubjectAlternativeName([
                        x509.DNSName("localhost"),
                        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                    ]),
                    critical=False
                )
                .sign(k, hashes.SHA256())
            )
            key.write_bytes(k.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ))
            cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))

        except ImportError:
            print("  WARNING: Cannot generate SSL. Install cryptography or openssl.")

    return cert, key


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: APPLICATION ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import logging
    import uvicorn

    cert, key = ensure_ssl_certs()
    use_ssl   = cert.exists() and key.exists()
    proto     = "https" if use_ssl else "http"

    print_banner()

    # Vector memory startup summary
    vm = get_vector_memory()
    if vm:
        print(f"  🔍 Vector Search : ENABLED ({vm._queries.count()} patterns, {vm._docs.count()} doc chunks)")
    else:
        print(f"  🔍 Vector Search : DISABLED (pip install chromadb sentence-transformers)")

    print(f"  Open     : {proto}://localhost:8899")
    print(f"  SSL      : {'Enabled' if use_ssl else 'Disabled'}")
    print(f"  Files    : {UPLOAD_DIR}")
    print(f"  Patterns : {len(memory.patterns)} learned queries")
    print(f"  Static   : {BASE_DIR / 'static'}")
    print("=" * 64)

    logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)

    kwargs = dict(
        host      = "127.0.0.1",
        port      = 8899,
        log_level = "warning",
        ws        = "wsproto",
    )

    if use_ssl:
        kwargs["ssl_certfile"] = str(cert)
        kwargs["ssl_keyfile"]  = str(key)

    uvicorn.run(app, **kwargs)