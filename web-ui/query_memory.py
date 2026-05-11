"""
query_memory.py — DataGrid Intelligence · Learned Query Memory
==============================================================
Single source of truth: learned_queries.json

Key capabilities
----------------
  • find_similar()    — recall the best matching pattern for a query
  • learn()           — auto-save patterns after successful AI queries
  • add_training()    — manually add/update a pattern (CLI / API training)
  • remove_pattern()  — delete a pattern by text
  • import_patterns() — bulk import from a JSON / CSV file
  • export_patterns() — dump all patterns to a file
  • stats()           — training statistics

Training count semantics
------------------------
  count=1…9   — auto-learned from AI results (low weight)
  count=10…19 — auto-learned, confirmed by re-use
  count≥20    — manually trained (MANUAL_TRAIN_BOOST added at training time)
  count≥100   — "locked" pattern, never pruned

Pattern params
--------------
  Some patterns contain {placeholder} tokens in the SQL, e.g.
    WHERE E."Meter_ID" = '{meter_id}'
  When recalled, _apply_params() fills these from the user's question text.

  NEW — Parameterization on save:
    When learn() saves a query like "show consumer for meter CRYT3000602",
    it automatically strips the concrete ID and saves a generic pattern:
      text: "show consumer for meter"
      sql:  WHERE E."Meter_ID" = '{meter_id}'
      params: ["meter_id"]
    So any future "show consumer for meter CRYT3000999" hits the same pattern.
    Multiple IDs ("meter CRYT001, CRYT002") collapse to IN ('{meter_ids}').

Vector Search (API-Free Semantic Matching)
------------------------------------------
  Uses ChromaDB + sentence-transformers (all-MiniLM-L6-v2, ~80MB).
  Downloads model ONCE on first run, then works fully OFFLINE forever.

  Priority chain inside find_similar():
    1. Exact string match          (instant, zero compute)
    2. Vector / semantic search    (ChromaDB — offline, no API)
    3. SequenceMatcher fallback    (original logic — always present)

  Install to enable:
    pip install chromadb sentence-transformers

  Without those packages the file works exactly as before (graceful degradation).
"""

import json
import re
from difflib import SequenceMatcher, get_close_matches
from pathlib import Path
from typing import Optional

from config import (
    MANUAL_TRAIN_BOOST,
    MEMORY_FILE,
    MEMORY_MATCH_THRESHOLD,
    MEMORY_MAX_PATTERNS,
    TRAINING_LOG,
)
from db_engine import db, normalize_sql_table_names


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 0 — VECTOR MEMORY (ChromaDB + sentence-transformers)
# ══════════════════════════════════════════════════════════════════════════════

_EMBED_MODEL   = "all-MiniLM-L6-v2"
_CHROMA_DIR    = str(Path(__file__).parent / ".chroma_db")
_VECTOR_THRESHOLD = 0.72


class _VectorMemory:
    """
    Thin wrapper around ChromaDB + SentenceTransformer.
    Two collections:
      "learned_queries"  — one doc per training pattern
      "document_chunks"  — chunked text from uploaded PDF / DOCX files
    """

    def __init__(self):
        import chromadb                                         # type: ignore
        from chromadb.utils import embedding_functions          # type: ignore

        self._ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=_EMBED_MODEL
        )
        self._client = chromadb.PersistentClient(path=_CHROMA_DIR)

        self._queries = self._client.get_or_create_collection(
            name="learned_queries",
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )
        self._docs = self._client.get_or_create_collection(
            name="document_chunks",
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )
        print(
            f"  [vector] ChromaDB ready — "
            f"{self._queries.count()} query patterns, "
            f"{self._docs.count()} doc chunks  (model: {_EMBED_MODEL})"
        )

    # ── Query pattern operations ───────────────────────────────────────────────

    def upsert_pattern(self, pattern_id: str, text: str, metadata: dict) -> None:
        safe_meta = {
            k: (v if v is not None else "")
            for k, v in metadata.items()
            if isinstance(v, (str, int, float, bool))
        }
        self._queries.upsert(
            ids=[pattern_id],
            documents=[text],
            metadatas=[safe_meta],
        )

    def delete_pattern(self, pattern_id: str) -> None:
        try:
            self._queries.delete(ids=[pattern_id])
        except Exception:
            pass

    def find_similar_query(self, text: str) -> Optional[dict]:
        if self._queries.count() == 0:
            return None

        results = self._queries.query(
            query_texts=[text],
            n_results=1,
            include=["documents", "metadatas", "distances"],
        )

        if not results["ids"] or not results["ids"][0]:
            return None

        distance   = results["distances"][0][0]
        similarity = 1.0 - (distance / 2.0)

        if similarity < _VECTOR_THRESHOLD:
            return None

        meta         = results["metadatas"][0][0]
        matched_text = results["documents"][0][0]

        return {
            "sql":          meta.get("sql", ""),
            "chart_type":   meta.get("chart_type", "table"),
            "explanation":  meta.get("explanation", ""),
            "confidence":   round(similarity, 4),
            "matched_text": matched_text,
            **{k: v for k, v in meta.items() if k not in ("sql", "chart_type", "explanation")},
        }

    def rebuild_from_patterns(self, patterns: list[dict]) -> None:
        existing_ids = self._queries.get()["ids"]
        if existing_ids:
            self._queries.delete(ids=existing_ids)

        if not patterns:
            return

        ids, docs, metas = [], [], []
        for p in patterns:
            pid = _pattern_id(p.get("text", "") or p.get("normalized", ""))
            ids.append(pid)
            docs.append(p.get("text", "") or p.get("normalized", ""))
            metas.append({
                "sql":         p.get("sql", ""),
                "chart_type":  p.get("chart_type", "table"),
                "explanation": p.get("explanation", ""),
                "count":       p.get("count", 0),
                "trained":     p.get("trained", False),
                "table":       p.get("table", ""),
            })

        batch = 500
        for i in range(0, len(ids), batch):
            self._queries.upsert(
                ids=ids[i:i+batch],
                documents=docs[i:i+batch],
                metadatas=metas[i:i+batch],
            )
        print(f"  [vector] Rebuilt index with {len(patterns)} patterns")

    # ── Document chunk operations ──────────────────────────────────────────────

    def add_document_chunks(
        self,
        doc_name: str,
        text: str,
        chunk_size: int = 400,
        overlap: int = 50,
    ) -> int:
        words  = text.split()
        step   = max(chunk_size - overlap, 1)
        chunks = [
            " ".join(words[i: i + chunk_size])
            for i in range(0, len(words), step)
            if words[i: i + chunk_size]
        ]

        if not chunks:
            return 0

        old_ids = [
            item
            for item in self._docs.get()["ids"]
            if item.startswith(f"{doc_name}__chunk__")
        ]
        if old_ids:
            self._docs.delete(ids=old_ids)

        ids   = [f"{doc_name}__chunk__{i}" for i in range(len(chunks))]
        metas = [{"doc_name": doc_name, "chunk_idx": i} for i in range(len(chunks))]

        batch = 500
        for i in range(0, len(ids), batch):
            self._docs.upsert(
                ids=ids[i:i+batch],
                documents=chunks[i:i+batch],
                metadatas=metas[i:i+batch],
            )

        print(f"  [vector] Indexed {len(chunks)} chunks for document '{doc_name}'")
        return len(chunks)

    def remove_document_chunks(self, doc_name: str) -> None:
        try:
            all_ids = self._docs.get()["ids"]
            target  = [i for i in all_ids if i.startswith(f"{doc_name}__chunk__")]
            if target:
                self._docs.delete(ids=target)
        except Exception:
            pass

    def search_documents(self, query: str, n_results: int = 4) -> list[str]:
        total = self._docs.count()
        if total == 0:
            return []

        n = min(n_results, total)
        results = self._docs.query(
            query_texts=[query],
            n_results=n,
            include=["documents", "distances"],
        )

        passages = []
        for doc, dist in zip(
            results["documents"][0],
            results["distances"][0],
        ):
            if (1.0 - dist / 2.0) >= _VECTOR_THRESHOLD:
                passages.append(doc)

        return passages


def _pattern_id(text: str) -> str:
    """Stable deterministic ID for a pattern based on its normalised text."""
    import hashlib
    return hashlib.md5(text.lower().strip().encode()).hexdigest()


# ── Module-level singleton (lazy) ─────────────────────────────────────────────

_vector_memory_instance: Optional[_VectorMemory] = None
_vector_memory_available: Optional[bool] = None


def _get_vector_memory() -> Optional[_VectorMemory]:
    global _vector_memory_instance, _vector_memory_available

    if _vector_memory_available is False:
        return None

    if _vector_memory_instance is not None:
        return _vector_memory_instance

    try:
        _vector_memory_instance  = _VectorMemory()
        _vector_memory_available = True
        return _vector_memory_instance
    except ImportError:
        _vector_memory_available = False
        print(
            "  [vector] chromadb / sentence-transformers not installed — "
            "using SequenceMatcher only.\n"
            "  To enable semantic search: pip install chromadb sentence-transformers"
        )
        return None
    except Exception as e:
        _vector_memory_available = False
        print(f"  [vector] Could not initialise ChromaDB ({e}) — falling back to SequenceMatcher.")
        return None


def get_vector_memory() -> Optional[_VectorMemory]:
    """External accessor — used by app.py when a document is uploaded/deleted."""
    return _get_vector_memory()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — GENERIC VALUES & PARAM HELPERS
# ══════════════════════════════════════════════════════════════════════════════

GENERIC_VALUES = {
    "all", "data", "detail", "details", "info", "information", "meter",
    "meters", "complete", "full", "list", "show", "get", "fetch",
    "consumer", "consumers", "location", "locations", "equipment",
}


def _sql_literal(value: str) -> str:
    return value.replace("'", "''")


def _looks_like_identifier(value: str) -> bool:
    v = value.strip().strip("'\"")
    if v.lower() in GENERIC_VALUES:
        return False
    return len(v) >= 3 and bool(re.search(r"\d", v))


# ── Param extraction patterns ──────────────────────────────────────────────────
# Used by extract_param_values() to pull concrete values out of a user query
# and fill {placeholder} tokens in recalled SQL.

_PARAM_PATTERNS: dict[str, list[str]] = {
    "meter_id": [
        r"\b(?:meter\s*(?:number|no\.?|id)|meter_id)\s*(?:is|=|==|equals?|:)?\s*['\"]?([A-Za-z0-9_-]{3,})['\"]?",
    ],
    "utility_id": [
        r"\b(?:consumer\s*(?:number|no\.?|id)|account\s*(?:number|no\.?|id)|utility_id)\s*"
        r"(?:is|=|==|equals?|:)?\s*['\"]?([A-Za-z0-9_-]{3,})['\"]?",
    ],
    "consumer_id": [
        r"\b(?:consumer\s*(?:number|no\.?|id)|consumer_id)\s*"
        r"(?:is|=|==|equals?|:)?\s*['\"]?([A-Za-z0-9_-]{3,})['\"]?",
    ],
    "equipment_id": [
        r"\b(?:equipment\s*(?:number|no\.?|id)|equipment_id)\s*"
        r"(?:is|=|==|equals?|:)?\s*['\"]?([A-Za-z0-9_-]{3,})['\"]?",
    ],
    "district": [
        r"\b(?:district)\s*(?:is|=|==|equals?|:)?\s*['\"]?([A-Za-z0-9_ -]{3,})['\"]?",
    ],
    "region": [
        r"\b(?:region)\s*(?:is|=|==|equals?|:)?\s*['\"]?([A-Za-z0-9_ -]{3,})['\"]?",
    ],
    "pin_code": [
        r"\b(?:pin|pincode|postal\s*code)\s*(?:is|=|==|equals?|:)?\s*['\"]?(\d{4,10})['\"]?",
    ],
    # ── Multi-value variants (NEW) ─────────────────────────────────────────────
    # Captures a comma-separated list of IDs after the keyword.
    "meter_ids": [
        r"\b(?:meter\s*(?:number|no\.?|id|#)?s?)\s*(?:is|=|:)?\s*"
        r"((?:['\"]?[A-Za-z][A-Za-z0-9_-]{2,}['\"]?\s*,?\s*)+)",
    ],
    "utility_ids": [
        r"\b(?:consumer|account)\s*(?:number|no\.?|id|#)?s?\s*(?:is|=|:)?\s*"
        r"((?:['\"]?[A-Za-z0-9][A-Za-z0-9_-]{2,}['\"]?\s*,?\s*)+)",
    ],
}


def extract_param_values(text: str, params: list[str]) -> dict[str, str]:
    """
    Extract concrete values from user text for each {param} placeholder.

    For singular params  (meter_id)  → returns single escaped string.
    For plural params    (meter_ids) → returns "'ID1','ID2'" ready for IN().
    """
    values: dict[str, str] = {}
    for param in params:
        key = str(param).strip("{}")
        for pattern in _PARAM_PATTERNS.get(key, []):
            m = re.search(pattern, text, re.IGNORECASE)
            if not m:
                continue
            raw = m.group(1).strip()

            if key.endswith("_ids"):
                # Multi-value: build SQL IN list  →  'ID1','ID2'
                ids = [
                    v.strip().strip("'\"")
                    for v in re.split(r"\s*,\s*", raw)
                    if _looks_like_identifier(v.strip().strip("'\""))
                ]
                if ids:
                    values[key] = "','".join(_sql_literal(i) for i in ids)
                    break
            elif _looks_like_identifier(raw):
                values[key] = _sql_literal(raw)
                break
    return values


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1-B — PARAMETERIZER  (NEW)
# Detects concrete ID values in a query and replaces them with {placeholders}
# so one pattern covers millions of different meter/consumer IDs.
# ══════════════════════════════════════════════════════════════════════════════

# Each entry describes one type of ID field:
#   param_name      — placeholder key, e.g. "meter_id"
#   kw_pattern      — regex matching the field keyword in natural language
#   val_pattern     — regex matching a single ID value token
#   sql_col_pattern — regex matching the SQL fragment that contains the literal
_FIELD_DETECTORS = [
    (
        "meter_id",
        r"meter\s*(?:number|no\.?|id|#)?",
        r"[A-Za-z][A-Za-z0-9_-]{2,}",
        r"""(?:E\.|"E"\.)?"?Meter_ID"?\s*=\s*'[^']*'""",
    ),
    (
        "utility_id",
        r"(?:consumer|account|utility)\s*(?:number|no\.?|id|#)?",
        r"[A-Za-z0-9][A-Za-z0-9_-]{2,}",
        r"""(?:C\.|"C"\.)?"?Utility_ID"?\s*=\s*'[^']*'""",
    ),
    (
        "consumer_id",
        r"consumer\s*(?:id|#)",
        r"\d{3,}",
        r"""(?:CDL\.|"CDL"\.)?"?ConsumerID"?\s*=\s*'[^']*'""",
    ),
    (
        "equipment_id",
        r"equipment\s*(?:number|no\.?|id|#)?",
        r"[A-Za-z0-9][A-Za-z0-9_-]{2,}",
        r"""(?:E\.|"E"\.)?"?ID"?\s*=\s*'[^']*'""",
    ),
]


def _parameterize_query(text: str, sql: str) -> tuple[str, str, list[str]]:
    """
    Detect concrete ID values in the query text and parameterize the SQL.

    Returns:
        clean_text  — text with the concrete IDs stripped out
                      (used as the pattern key for future matching)
        param_sql   — SQL with '{meter_id}' placeholders instead of literals
        params      — list of param names used, e.g. ["meter_id"]

    Single ID example:
        text: "show consumer detail for meter CRYT3000602"
        sql:  "... WHERE E.\"Meter_ID\" = 'CRYT3000602'"
        →
        clean_text: "show consumer detail for meter"
        param_sql:  "... WHERE E.\"Meter_ID\" = '{meter_id}'"
        params:     ["meter_id"]

    Multiple IDs example:
        text: "show consumer detail for meter CRYT3000602, CRYT3000707"
        sql:  "... WHERE E.\"Meter_ID\" IN ('CRYT3000602', 'CRYT3000707')"
        →
        clean_text: "show consumer detail for meter"
        param_sql:  "... WHERE E.\"Meter_ID\" IN ('{meter_ids}')"
        params:     ["meter_ids"]
    """
    if not sql:
        return text, sql, []

    params_found: list[str] = []
    clean_text = text

    for param_name, kw_pattern, val_pattern, sql_col_pattern in _FIELD_DETECTORS:

        # Pattern: keyword + optional operator + one or more comma-separated IDs
        multi_re = (
            rf"(?<!\w)({kw_pattern})\s*"           # keyword (captured for removal)
            rf"(?:is|=|:)?\s*"                      # optional operator
            rf"(['\"]?{val_pattern}['\"]?"          # first ID
            rf"(?:\s*,\s*['\"]?{val_pattern}['\"]?)*)"  # optional further IDs
        )
        m = re.search(multi_re, clean_text, re.IGNORECASE)
        if not m:
            continue

        raw_values_str = m.group(2)
        raw_values = [
            v.strip().strip("'\"")
            for v in re.split(r"\s*,\s*", raw_values_str)
        ]
        raw_values = [v for v in raw_values if _looks_like_identifier(v)]

        if not raw_values:
            continue

        # ── Strip the concrete IDs from text (keep the keyword) ───────────────
        # Replace the full match (keyword + IDs) with just the keyword so
        # "show consumer for meter CRYT3000602" → "show consumer for meter"
        clean_text = (
            clean_text[: m.start()]
            + m.group(1)                    # keep keyword, drop IDs
            + clean_text[m.end():]
        ).strip()

        # ── Parameterize SQL ──────────────────────────────────────────────────
        if len(raw_values) == 1:
            # Single value: = 'X'  →  = '{meter_id}'
            placeholder = "{" + param_name + "}"

            def _replace_single(mo, ph=placeholder):
                # Replace only the quoted value, keep column name + operator
                return re.sub(r"'[^']*'", f"'{ph}'", mo.group())

            new_sql = re.sub(
                sql_col_pattern,
                _replace_single,
                sql,
                flags=re.IGNORECASE,
            )
            if new_sql != sql:          # replacement actually happened
                sql = new_sql
                if param_name not in params_found:
                    params_found.append(param_name)

        else:
            # Multiple values → IN ('{meter_ids}')
            plural_param  = param_name + "s"    # "meter_id" → "meter_ids"
            placeholder   = "{" + plural_param + "}"

            # Match either an existing IN(...) clause or a simple = 'X' clause
            combined_re = (
                rf"(?:IN\s*\([^)]*\)"           # existing IN list
                rf"|{sql_col_pattern})"          # or simple equality
            )

            def _replace_multi(mo, ph=placeholder):
                inner = mo.group()
                # Only touch lines that reference the right column
                if not re.search(
                    r"Meter_ID|Utility_ID|ConsumerID|Equipment",
                    inner, re.IGNORECASE
                ):
                    return inner
                return re.sub(
                    r"(?:IN\s*\([^)]*\)|=\s*'[^']*')",
                    f"IN ('{ph}')",
                    inner,
                    flags=re.IGNORECASE,
                )

            new_sql = re.sub(combined_re, _replace_multi, sql, flags=re.IGNORECASE)
            if new_sql != sql:
                sql = new_sql
                if plural_param not in params_found:
                    params_found.append(plural_param)

    return clean_text.strip(), sql, params_found


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — QueryMemory
# ══════════════════════════════════════════════════════════════════════════════

class QueryMemory:

    def __init__(self):
        self.patterns: list[dict] = self._load_and_seed()
        self._mtime = MEMORY_FILE.stat().st_mtime if MEMORY_FILE.exists() else 0.0

        vm = _get_vector_memory()
        if vm and self.patterns:
            try:
                vm.rebuild_from_patterns(self.patterns)
            except Exception as e:
                print(f"  [vector] Startup sync failed (non-fatal): {e}")

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load_and_seed(self) -> list[dict]:
        if MEMORY_FILE.exists():
            try:
                data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for p in data:
                        if isinstance(p.get("sql"), str):
                            p["sql"] = normalize_sql_table_names(p["sql"])
                    data.sort(key=lambda x: x.get("count", 0), reverse=True)
                    print(f"  [memory] Loaded {len(data)} patterns from {MEMORY_FILE.name}")
                    return data
            except Exception as e:
                print(f"  [memory] Could not load {MEMORY_FILE.name}: {e}")

        print("  [memory] Starting with empty pattern store.")
        return []

    def _save(self, patterns: Optional[list] = None) -> None:
        data = patterns if patterns is not None else self.patterns
        try:
            MEMORY_FILE.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            self._mtime = MEMORY_FILE.stat().st_mtime
        except Exception as e:
            print(f"  [memory] Save failed: {e}")

    def reload_if_changed(self) -> None:
        try:
            mtime = MEMORY_FILE.stat().st_mtime
        except FileNotFoundError:
            return
        if mtime > self._mtime:
            self.patterns = self._load_and_seed()
            self._mtime   = mtime
            vm = _get_vector_memory()
            if vm:
                try:
                    vm.rebuild_from_patterns(self.patterns)
                except Exception:
                    pass

    # ── Normalisation ──────────────────────────────────────────────────────────

    def _normalize(self, text: str) -> str:
        text = text.lower().strip()
        for f in ["show me", "please", "can you", "give me", "find me", "tell me", "display"]:
            text = re.sub(r"\b" + re.escape(f) + r"\b", " ", text)
        text = re.sub(r"\b(?:and|the|a|an)\b", " ", text)
        # Strip embedded ID-like tokens so "meter CRYT001" normalizes same as "meter CRYT999"
        text = re.sub(r"\b[A-Za-z]{1,4}\d[\w-]*\b", " ", text)
        text = re.sub(r"\b\d{3,}\b", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _pattern_norm(self, pat: dict) -> str:
        return self._normalize(pat.get("text") or pat.get("normalized", ""))

    def _similarity(self, a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()

    def _token_overlap(self, a: str, b: str) -> float:
        ta = set(a.split())
        tb = set(b.split())
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / max(len(ta), len(tb))

    # ── Param substitution ─────────────────────────────────────────────────────

    def _apply_params(self, sql: str, text: str, params: list[str]) -> Optional[str]:
        """
        Fill {param} placeholders in SQL using values extracted from user text.

        Handles:
          - Singular:  '{meter_id}'  → 'CRYT3000999'
          - Plural:    '{meter_ids}' (inside IN clause) → 'CRYT001','CRYT002'

        Returns None if a required param value could not be found in the text
        (prevents running a query with a literal placeholder in it).
        """
        if not params:
            return sql

        values = extract_param_values(text, params)

        for param in params:
            key         = str(param).strip("{}")
            placeholder = "{" + key + "}"

            if placeholder not in sql:
                continue

            value = values.get(key)
            if not value:
                # Required param missing — refuse to return broken SQL
                return None

            if key.endswith("_ids"):
                # Value is already  'ID1','ID2'  — sits inside IN ('...')
                sql = sql.replace(f"('{placeholder}')", f"('{value}')")
            else:
                sql = sql.replace(placeholder, value)

        return sql

    # ── Find similar  (Exact → Vector → SequenceMatcher) ──────────────────────

    def find_similar(self, text: str, table: str = "") -> Optional[dict]:
        """
        Return the best matching learned pattern, or None.

        Search priority:
          1. Exact normalised-string match      (zero cost)
          2. Vector / semantic search            (ChromaDB, offline)
          3. SequenceMatcher + token-overlap     (always available)
        """
        self.reload_if_changed()
        norm = self._normalize(text)

        # ── 1. Exact match ─────────────────────────────────────────────────────
        exact = [
            p for p in self.patterns
            if (not table or not p.get("table") or p["table"] == table)
            and norm == self._pattern_norm(p)
        ]
        if exact:
            exact.sort(key=lambda x: x.get("count", 0), reverse=True)
            return self._finalise(exact[0], text, 1.0)

        # ── 2. Vector / semantic search ────────────────────────────────────────
        vm = _get_vector_memory()
        if vm:
            try:
                vec_result = vm.find_similar_query(text)
                if vec_result:
                    raw_sql = vec_result.get("sql", "")
                    if raw_sql:
                        vec_table = vec_result.get("table", "")
                        if not (table and vec_table and vec_table != table):
                            sql = self._apply_params(
                                raw_sql, text,
                                vec_result.get("params", []) or []
                            )
                            if sql:
                                sql = self._substitute_numerics(
                                    sql,
                                    vec_result.get("matched_text", ""),
                                    text,
                                )
                                if db.tables and not db.validate(sql):
                                    print(
                                        f"  [vector] Matched pattern failed SQL validation"
                                        f" — skipping: {sql[:80]}…"
                                    )
                                else:
                                    confidence = vec_result.get("confidence", 0.0)
                                    print(
                                        f"  [vector] Semantic match "
                                        f"(score={confidence:.3f}): "
                                        f"'{vec_result.get('matched_text', '')[:60]}'"
                                    )
                                    return {
                                        **vec_result,
                                        "sql":         sql,
                                        "explanation": f"[Vector] {vec_result.get('explanation', '')}",
                                    }
            except Exception as e:
                print(f"  [vector] Search error (non-fatal): {e}")

        # ── 3. SequenceMatcher fallback ────────────────────────────────────────
        best_score = 0.0
        best       = None
        for p in self.patterns:
            if table and p.get("table") and p["table"] != table:
                continue
            pn    = self._pattern_norm(p)
            score = self._similarity(norm, pn)
            if self._token_overlap(norm, pn) < 0.55:
                continue
            if score > best_score and score >= MEMORY_MATCH_THRESHOLD:
                best_score, best = score, p

        if not best:
            return None

        return self._finalise(best, text, best_score)

    def _finalise(self, best: dict, text: str, score: float) -> Optional[dict]:
        """Shared post-processing: substitute numerics, fill params, validate SQL."""
        sql = best["sql"]
        sql = self._substitute_numerics(sql, best.get("text", ""), text)
        sql = self._apply_params(sql, text, best.get("params", []))
        if not sql:
            return None
        if db.tables and not db.validate(sql):
            print(f"  [memory] Pattern SQL failed validation — skipping: {sql[:80]}…")
            return None
        return {
            **best,
            "sql":         sql,
            "explanation": f"[Recalled] {best.get('explanation', '')}",
            "confidence":  score,
        }

    @staticmethod
    def _substitute_numerics(sql: str, original_text: str, new_text: str) -> str:
        """Replace numeric literals from the original question with those from the new one."""
        new_nums = re.findall(r"\b\d+(?:\.\d+)?\b", new_text)
        old_nums = re.findall(r"\b\d+(?:\.\d+)?\b", original_text)
        for old, new in zip(old_nums, new_nums):
            sql = sql.replace(old, new, 1)
        return sql

    # ── Auto-learn  (called after every successful AI query) ──────────────────

    def learn(
        self,
        text: str,
        sql: str,
        table: str,
        explanation: str,
        chart_type: str,
        row_count: int,
        allow_sql_update: bool = True,
    ) -> None:
        """
        Auto-save a successful AI query result as a learned pattern.

        NEW behaviour:
          Before saving, _parameterize_query() strips concrete ID values
          (meter numbers, consumer IDs, etc.) from both the text and the SQL,
          replacing them with {placeholder} tokens.  This means ONE stored
          pattern covers queries for ANY meter ID, not just the one that
          happened to be asked first.
        """
        self.reload_if_changed()
        if row_count == 0 or not sql:
            return

        sql = normalize_sql_table_names(sql)

        # ── Parameterize: strip IDs before storing ────────────────────────────
        generic_text, param_sql, params = _parameterize_query(text, sql)

        # Only use the parameterized versions if we actually found IDs to strip.
        # If no IDs found, fall back to the original text/sql unchanged.
        store_text = generic_text if params else text
        store_sql  = param_sql    if params else sql
        # ── End parameterize ──────────────────────────────────────────────────

        norm = self._normalize(store_text)

        # Update existing pattern if text normalizes to the same key
        for pat in self.patterns:
            if norm == self._pattern_norm(pat):
                if allow_sql_update:
                    pat.update({
                        "sql":         store_sql,
                        "explanation": explanation,
                        "chart_type":  chart_type,
                        "normalized":  norm,
                    })
                    if params:
                        pat["params"] = params
                pat["count"] = pat.get("count", 1) + 1
                self._save()
                self._vector_upsert(pat)
                return

        # Create new pattern
        new_pat: dict = {
            "text":        store_text,
            "normalized":  norm,
            "sql":         store_sql,
            "table":       table,
            "explanation": explanation,
            "chart_type":  chart_type,
            "count":       1,
            "trained":     False,
        }
        if params:
            new_pat["params"] = params

        self.patterns.append(new_pat)
        self._prune()
        self._save()
        self._vector_upsert(new_pat)
        print(
            f"  [memory] Auto-learned: '{store_text[:60]}'"
            + (f" (params: {params})" if params else "")
            + " → saved ✓"
        )

    # ── Manual training ────────────────────────────────────────────────────────

    def add_training(
        self,
        text: str,
        sql: str,
        explanation: str,
        chart_type: str,
        table: str = "",
        params: Optional[list[str]] = None,
        lock: bool = False,
    ) -> str:
        """
        Manually add or update a training example.
        Also parameterizes automatically unless the caller already provides params.
        """
        self.reload_if_changed()
        sql = normalize_sql_table_names(sql.strip().rstrip(";"))

        # Auto-parameterize manually trained patterns too (unless caller passed params)
        if params is None:
            _, param_sql, auto_params = _parameterize_query(text, sql)
            if auto_params:
                sql    = param_sql
                params = auto_params

        norm = self._normalize(text)

        for pat in self.patterns:
            if norm == self._pattern_norm(pat):
                pat.update({
                    "sql":         sql,
                    "explanation": explanation,
                    "chart_type":  chart_type,
                    "normalized":  norm,
                    "trained":     True,
                })
                if params:
                    pat["params"] = params
                pat["count"] = 200 if lock else max(
                    pat.get("count", 0) + MANUAL_TRAIN_BOOST,
                    MANUAL_TRAIN_BOOST,
                )
                self._save()
                self._vector_upsert(pat)
                self._append_training_log(text, sql, "updated")
                return "updated"

        entry: dict = {
            "text":        text,
            "normalized":  norm,
            "sql":         sql,
            "table":       table,
            "explanation": explanation,
            "chart_type":  chart_type,
            "count":       200 if lock else MANUAL_TRAIN_BOOST,
            "trained":     True,
        }
        if params:
            entry["params"] = params
        self.patterns.append(entry)
        self.patterns.sort(key=lambda x: x.get("count", 0), reverse=True)
        self._save()
        self._vector_upsert(entry)
        self._append_training_log(text, sql, "added")
        print(f"  [memory] Trained: '{text[:60]}' → saved ✓")
        return "added"

    # ── Remove pattern ─────────────────────────────────────────────────────────

    def remove_pattern(self, text: str) -> bool:
        self.reload_if_changed()
        norm   = self._normalize(text)
        before = len(self.patterns)
        self.patterns = [
            p for p in self.patterns if self._pattern_norm(p) != norm
        ]
        removed = len(self.patterns) < before
        if removed:
            self._save()
            vm = _get_vector_memory()
            if vm:
                try:
                    vm.delete_pattern(_pattern_id(norm))
                except Exception:
                    pass
        return removed

    def update_sql(self, text: str, new_sql: str) -> bool:
        self.reload_if_changed()
        norm    = self._normalize(text)
        new_sql = normalize_sql_table_names(new_sql.strip().rstrip(";"))
        for pat in self.patterns:
            if norm == self._pattern_norm(pat):
                pat["sql"]     = new_sql
                pat["trained"] = True
                self._save()
                self._vector_upsert(pat)
                return True
        return False

    # ── Bulk import / export ───────────────────────────────────────────────────

    def import_patterns(self, source_path: Path) -> tuple[int, int]:
        data = json.loads(source_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Import file must be a JSON array.")
        added = updated = 0
        for entry in data:
            if "text" not in entry or "sql" not in entry:
                continue
            result = self.add_training(
                text        = entry["text"],
                sql         = entry["sql"],
                explanation = entry.get("explanation", ""),
                chart_type  = entry.get("chart_type", "table"),
                table       = entry.get("table", ""),
                params      = entry.get("params"),
                lock        = entry.get("lock", False),
            )
            if result == "added":
                added += 1
            else:
                updated += 1
        return added, updated

    def export_patterns(self, dest_path: Path) -> int:
        dest_path.write_text(
            json.dumps(self.patterns, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return len(self.patterns)

    # ── Stats ──────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        total   = len(self.patterns)
        trained = sum(1 for p in self.patterns if p.get("trained"))
        auto    = total - trained
        locked  = sum(1 for p in self.patterns if p.get("count", 0) >= 200)
        top5    = sorted(self.patterns, key=lambda x: x.get("count", 0), reverse=True)[:5]
        charts  = {}
        for p in self.patterns:
            ct = p.get("chart_type", "table")
            charts[ct] = charts.get(ct, 0) + 1

        vm = _get_vector_memory()
        vector_info = {
            "enabled":        vm is not None,
            "query_patterns": vm._queries.count() if vm else 0,
            "doc_chunks":     vm._docs.count()    if vm else 0,
            "model":          _EMBED_MODEL        if vm else "N/A",
        }

        return {
            "total":        total,
            "trained":      trained,
            "auto_learned": auto,
            "locked":       locked,
            "chart_types":  charts,
            "top5":         [{"text": p["text"], "count": p.get("count", 0)} for p in top5],
            "vector":       vector_info,
        }

    # ── Private helpers ────────────────────────────────────────────────────────

    def _vector_upsert(self, pat: dict) -> None:
        vm = _get_vector_memory()
        if not vm:
            return
        try:
            pid  = _pattern_id(pat.get("text", "") or pat.get("normalized", ""))
            text = pat.get("text", "") or pat.get("normalized", "")
            meta = {
                "sql":         pat.get("sql", ""),
                "chart_type":  pat.get("chart_type", "table"),
                "explanation": pat.get("explanation", ""),
                "count":       pat.get("count", 0),
                "trained":     bool(pat.get("trained", False)),
                "table":       pat.get("table", ""),
            }
            vm.upsert_pattern(pid, text, meta)
        except Exception as e:
            print(f"  [vector] Upsert failed (non-fatal): {e}")

    def _prune(self) -> None:
        if len(self.patterns) > MEMORY_MAX_PATTERNS:
            keep_locked = [p for p in self.patterns if p.get("count", 0) >= 200]
            rest        = [p for p in self.patterns if p.get("count", 0) < 200]
            rest.sort(key=lambda x: x.get("count", 0), reverse=True)
            self.patterns = keep_locked + rest[:800 - len(keep_locked)]

    def _append_training_log(self, text: str, sql: str, action: str) -> None:
        try:
            import json as _j, datetime as _dt
            entry = _j.dumps(
                {
                    "ts":     _dt.datetime.utcnow().isoformat(),
                    "action": action,
                    "text":   text,
                    "sql":    sql[:200],
                },
                ensure_ascii=False,
            )
            with open(TRAINING_LOG, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception:
            pass


# ── Module-level singleton ─────────────────────────────────────────────────────
memory = QueryMemory()