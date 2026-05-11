"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  nl_sql.py  —  DataGrid Intelligence · Rule-Based NL → SQL Converter       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Ye file tab use hoti hai jab:                                              ║
║    1. Koi API key nahi hai (offline mode)                                  ║
║    2. AI engines fail ho gaye                                               ║
║    3. Learned memory mein pattern nahi mila                                 ║
║                                                                             ║
║  Multi-File Awareness:                                                      ║
║    Jab multiple parquet files same columns share karti hain, converter      ║
║    automatically "_all_data" union view use karta hai — sab files ek saath ║
║                                                                             ║
║  CHANGE (parameterization support):                                         ║
║    _detect_master_join_condition() now handles multiple comma-separated     ║
║    meter/consumer IDs, building an IN ('ID1','ID2') clause instead of      ║
║    silently dropping everything after the first comma.                      ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import re                    # Regular expressions — text patterns match karne ke liye
from difflib import get_close_matches  # Fuzzy string matching — typos handle karne ke liye
from typing import Optional  # Type hints ke liye

from config import MAX_ROWS_DISPLAY  # Maximum rows limit
from db_engine import db             # Database engine singleton


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: MASTER JOIN SQL
# 7 tables ko join karne wala canonical query
# ══════════════════════════════════════════════════════════════════════════════

MASTER_JOIN_SQL = """SELECT
    E.Meter_ID          AS Meter_No,
    MM.Meter_Type,
    MM.DIP,
    HM.HES_CD           AS HES_Name,
    E.ID                AS EQUIPMENT_ID,
    MM.Utility_ID       AS Material_ID,
    C.Cons_SEG,
    CDL.ConsumerID,
    E.Manufacturer_ID,
    C.Utility_ID        AS ConsumerNo,
    E.Status,
    DL.Utility_Office_ID,
    MM.Description      AS Attribute,
    E.Model_ID,
    DL.GPS_LAT,
    DL.GPS_LONG,
    C.Utility_ID        AS Account_No
FROM Equipment E
JOIN DevLoc_Device_Link  DDL ON E.ID                = DDL.EquipmentId
JOIN Device_Location     DL  ON DL.ID               = DDL.DeviceLocationId
JOIN ConsumerDevLocLink  CDL ON DDL.DeviceLocationId = CDL.DeviceLocationId
JOIN Consumer            C   ON C.ID                = CDL.ConsumerID
JOIN Material_Master     MM  ON E.Material_ID        = MM.Utility_ID
LEFT JOIN HES_MASTER     HM  ON E.HES_ID             = HM.ID"""

MASTER_JOIN_SQL_STRIPPED = re.sub(r"\s+", " ", MASTER_JOIN_SQL).strip()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: TRIGGER KEYWORDS
# ══════════════════════════════════════════════════════════════════════════════

MASTER_JOIN_TRIGGERS = [
    "meter detail", "meter info", "meter data", "complete meter",
    "full meter", "meter inventory", "list all meter", "show meter",
    "all meter", "consumer detail", "consumer info", "account detail",
    "show all meter", "get meter", "meter number", "meter no", "meter id",
    "meter_id", "meter no.", "user whose meter", "consumer whose meter",
    "customer whose meter",
]

MASTER_JOIN_TABLES = {
    "equipment", "consumer", "device_location", "devloc_device_link",
    "consumerdevloclink", "material_master", "hes_master",
}

GENERIC_VALUES = {
    "all", "data", "detail", "details", "info", "information", "meter",
    "meters", "complete", "full", "list", "show", "get", "fetch",
    "consumer", "consumers", "location", "locations",
}

ALL_DATA_KEYWORDS = [
    "all data", "show all", "all rows", "everything", "full data",
    "entire data", "complete data", "return all", "fetch all",
    "display all", "get all",
]

ALL_TABLES_KEYWORDS = [
    "all tables", "every table", "all files", "all datasets",
    "combine all", "merge all", "union all tables", "from all",
]


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _sql_literal(v: str) -> str:
    """SQL string literal ke liye single quotes escape karo."""
    return v.replace("'", "''")


def _looks_like_identifier(v: str) -> bool:
    """
    Check karo ki string ek actual ID/value hai ya generic word.
    Meter IDs mein usually digits hote hain (e.g., "CRYT3000602").
    """
    v = v.strip().strip("'\"")
    if v.lower() in GENERIC_VALUES:
        return False
    return len(v) >= 3 and bool(re.search(r"\d", v))


def _has_master_join_tables() -> bool:
    """Check karo ki Equipment aur Consumer tables loaded hain."""
    available = {t.lower() for t in db.tables}
    return {"equipment", "consumer"}.issubset(available)


def _detect_master_join_condition(text: str) -> Optional[tuple[str, str]]:
    """
    Text mein specific meter/consumer ID(s) dhundho aur WHERE clause banao.

    UPDATED: Ab single aur multiple comma-separated IDs dono handle karta hai.

    Single ID  → WHERE E."Meter_ID" = 'CRYT3000602'
    Multi IDs  → WHERE E."Meter_ID" IN ('CRYT3000602', 'CRYT3000707')

    Returns: (WHERE_clause, label) ya None
    """

    # Each entry: (keyword_pattern, value_pattern, column_ref, label)
    # value_pattern matches ONE identifier token (no comma inside)
    field_specs = [
        (
            r"(?:meter\s*(?:number|no\.?|id)|meter_id)",
            r"[A-Za-z0-9_-]{3,}",
            'E."Meter_ID"',
            "meter id",
        ),
        (
            r"(?:consumer\s*(?:number|no\.?|id)|consumer_id)",
            r"[A-Za-z0-9_-]{3,}",
            'C."Utility_ID"',
            "consumer id",
        ),
        (
            r"(?:account\s*(?:number|no\.?|id)|account_id)",
            r"[A-Za-z0-9_-]{3,}",
            'C."Utility_ID"',
            "account id",
        ),
    ]

    for kw_pat, val_pat, column, label in field_specs:

        # Pattern: keyword + optional operator + first ID
        # then greedily capture any further ", ID" tokens
        full_pattern = (
            rf"\b({kw_pat})\s*"             # keyword (group 1)
            rf"(?:is|=|==|equals?|:)?\s*"  # optional operator
            rf"['\"]?({val_pat})['\"]?"     # first ID (group 2)
            rf"((?:\s*,\s*['\"]?{val_pat}['\"]?)*)"  # optional more IDs (group 3)
        )

        m = re.search(full_pattern, text, re.IGNORECASE)
        if not m:
            continue

        first_id   = m.group(2).strip().strip("'\"")
        rest_chunk = m.group(3) or ""       # e.g. ", CRYT3000707, CRYT3000800"

        if not _looks_like_identifier(first_id):
            continue

        # Collect all IDs: first + any extras from the comma-separated tail
        all_ids = [first_id]
        for extra in re.findall(rf"['\"]?({val_pat})['\"]?", rest_chunk):
            extra = extra.strip().strip("'\"")
            if _looks_like_identifier(extra):
                all_ids.append(extra)

        if len(all_ids) == 1:
            # Single ID → equality condition
            safe_val = _sql_literal(all_ids[0])
            return (
                f"{column} = '{safe_val}'",
                f"{label} = {all_ids[0]}",
            )
        else:
            # Multiple IDs → IN condition
            in_list  = ", ".join(f"'{_sql_literal(i)}'" for i in all_ids)
            id_label = ", ".join(all_ids)
            return (
                f"{column} IN ({in_list})",
                f"{label} IN ({id_label})",
            )

    return None  # Koi specific ID nahi mila


def build_union_sql(table_names: list[str], limit: Optional[int] = None) -> str:
    """
    Multiple tables ko UNION ALL mein combine karne ka SQL banata hai.
    _source_file column add karta hai.
    """
    if not table_names:
        return ""

    if len(table_names) == 1:
        sql = f"SELECT *, '{table_names[0]}' AS _source_file FROM \"{table_names[0]}\""
        if limit:
            sql += f" LIMIT {limit}"
        return sql

    col_sets = [
        set(c["name"] for c in db.table_columns.get(n, []))
        for n in table_names
    ]
    common_cols = col_sets[0]
    for s in col_sets[1:]:
        common_cols &= s

    if common_cols:
        col_list = ", ".join(f'"{c}"' for c in sorted(common_cols))
        parts    = [
            f"SELECT {col_list}, '{n}' AS _source_file FROM \"{n}\""
            for n in table_names
        ]
    else:
        parts = [f"SELECT *, '{n}' AS _source_file FROM \"{n}\"" for n in table_names]

    sql = "\nUNION ALL\n".join(parts)
    if limit:
        sql = f"SELECT * FROM ({sql}) _sq LIMIT {limit}"
    return sql


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: NLTOSQL CLASS
# ══════════════════════════════════════════════════════════════════════════════

class NLToSQL:
    """
    Natural language queries ko DuckDB SQL mein convert karta hai.
    Rule-based approach use karta hai — AI ki zaroorat nahi.
    """

    AGG_MAP = {
        "sum": "SUM", "total": "SUM",
        "average": "AVG", "avg": "AVG", "mean": "AVG",
        "count": "COUNT", "how many": "COUNT",
        "minimum": "MIN", "min": "MIN", "lowest": "MIN", "smallest": "MIN",
        "maximum": "MAX", "max": "MAX", "highest": "MAX", "largest": "MAX",
    }

    CHART_MAP = {
        "bar": "bar", "line": "line", "pie": "pie", "scatter": "scatter",
        "histogram": "histogram", "area": "area",
        "trend": "line",
        "distribution": "histogram",
        "table": "table",
    }

    def __init__(self):
        self.tables  = db.table_columns
        self.active  = db.active_table

    def convert(self, text: str) -> tuple[str, str, str]:
        """
        Natural language text ko (sql, chart_type, explanation) tuple mein convert karta hai.
        """
        lower = text.lower().strip()

        # ── Raw SQL passthrough ────────────────────────────────────────────────
        if re.match(r"^(select|with|pragma|explain)\b", lower):
            return text, self._detect_chart(lower) or "table", "SQL passthrough"

        # ── Master JOIN path ───────────────────────────────────────────────────
        if _has_master_join_tables() and (
            any(t in lower for t in MASTER_JOIN_TRIGGERS) or
            any(k in lower for k in ALL_DATA_KEYWORDS)
        ):
            sql   = MASTER_JOIN_SQL_STRIPPED
            chart = self._detect_chart(lower)

            # Detect specific ID(s) — now handles multiple IDs too
            cond = _detect_master_join_condition(text)
            if cond:
                where_sql, label = cond
                sql += f" WHERE {where_sql}"
                return sql, chart or "table", f"Meter/consumer details jahan {label}"

            return sql, chart or "table", "Sab meter details (7-table join)"

        # ── All tables union ───────────────────────────────────────────────────
        if any(kw in lower for kw in ALL_TABLES_KEYWORDS):
            all_t = list(self.tables.keys())
            if not all_t:
                return "", "table", "Koi tables load nahi hain"
            lim = None if any(w in lower for w in ALL_DATA_KEYWORDS) else MAX_ROWS_DISPLAY
            return (
                build_union_sql(all_t, limit=lim),
                self._detect_chart(lower) or "table",
                f"Sab {len(all_t)} tables ka combined data",
            )

        # ── Multi-file union view path ─────────────────────────────────────────
        union_view, union_tables = db.get_best_union_view()
        if union_view and len(union_tables) >= 1:
            mentioned_in_text = self._find_mentioned_tables(lower)
            if not mentioned_in_text and not any(t in lower for t in MASTER_JOIN_TRIGGERS):
                ucols     = db.union_view_columns(union_view)
                col_names = [c["name"] for c in ucols]
                chart     = self._detect_chart(lower)
                agg       = self._detect_agg(lower)
                group     = self._detect_group(lower, col_names)
                lim, od   = self._detect_limit(lower)

                if agg and group:
                    numeric  = [c["name"] for c in ucols if c["dtype"] == "numeric"]
                    val_col  = next(
                        (c for c in col_names if c in numeric and c != group),
                        numeric[0] if numeric else "*"
                    )
                    alias    = f"{agg.lower()}_val"
                    sql      = (
                        f'SELECT "{group}", {agg}("{val_col}") AS {alias} '
                        f'FROM "{union_view}" '
                        f'GROUP BY "{group}" ORDER BY {alias} {od}'
                    )
                    if lim:
                        sql += f" LIMIT {lim}"
                    return sql, chart or "bar", f"{agg} of {val_col} by {group} (sab files)"

                if lim:
                    return (
                        f'SELECT * FROM "{union_view}" LIMIT {lim}',
                        chart or "table",
                        f"Top {lim} rows (sab files)",
                    )

                eq = self._detect_equality_filter(text, col_names)
                if eq:
                    col_f, val_f = eq
                    return (
                        f'SELECT * FROM "{union_view}" WHERE "{col_f}" = \'{val_f}\' '
                        f'LIMIT {MAX_ROWS_DISPLAY}',
                        chart or "table",
                        f"Sab files jahan {col_f} = {val_f}",
                    )

                return (
                    f'SELECT * FROM "{union_view}" LIMIT {MAX_ROWS_DISPLAY}',
                    chart or "table",
                    f"Sab data ({len(union_tables)} parquet files)",
                )

        # ── Single table path ──────────────────────────────────────────────────
        mentioned = self._find_mentioned_tables(lower)
        if len(mentioned) > 1:
            lim = None if any(w in lower for w in ALL_DATA_KEYWORDS) else MAX_ROWS_DISPLAY
            return (
                build_union_sql(mentioned, limit=lim),
                self._detect_chart(lower) or "table",
                f"Combined: {', '.join(mentioned)}",
            )

        table     = mentioned[0] if mentioned else self._detect_table(lower)
        if not table:
            return "", "table", "Koi table select nahi hua"

        cols      = self.tables.get(table, [])
        col_names = [c["name"] for c in cols]
        numeric   = [c["name"] for c in cols if c["dtype"] == "numeric"]

        if any(w in lower for w in ["describe", "schema", "columns", "structure"]):
            return f'DESCRIBE "{table}"', "table", f"{table} ka schema"

        if any(w in lower for w in ["summary", "stats", "statistics", "overview", "summarize"]):
            return f'SUMMARIZE "{table}"', "table", f"{table} ki statistics"

        if any(p in lower for p in ALL_DATA_KEYWORDS):
            eq = self._detect_equality_filter(text, col_names)
            if eq:
                col_f, val_f = eq
                return (
                    f'SELECT * FROM "{table}" WHERE "{col_f}" = \'{val_f}\'',
                    "table",
                    f"Sab {table} jahan {col_f} = {val_f}",
                )
            return f'SELECT * FROM "{table}"', "table", f"{table} ka sab data"

        chart   = self._detect_chart(lower)
        agg     = self._detect_agg(lower)
        eq      = self._detect_equality_filter(text, col_names)
        wh_cond = self._detect_where(lower, col_names)

        if eq and not wh_cond:
            col_f, val_f = eq
            return (
                f'SELECT * FROM "{table}" WHERE "{col_f}" = \'{val_f}\' LIMIT {MAX_ROWS_DISPLAY}',
                chart or "table",
                f"{table} filter: {col_f} = {val_f}",
            )

        mcols   = self._find_columns(lower, col_names)
        lim, od = self._detect_limit(lower)
        group   = self._detect_group(lower, col_names)
        where   = self._build_where(wh_cond)

        if agg and group:
            vc    = next((c for c in mcols if c in numeric and c != group), (numeric[0] if numeric else "*"))
            alias = f"{agg.lower()}_val"
            sql   = f'SELECT "{group}", {agg}("{vc}") AS {alias} FROM "{table}"'
            if where: sql += f" WHERE {where}"
            sql += f' GROUP BY "{group}" ORDER BY {alias} {od}'
            if lim: sql += f" LIMIT {lim}"
            return sql, chart or "bar", f"{agg} of {vc} by {group}"

        if lim:
            sc  = next((c for c in mcols if c in numeric), (numeric[0] if numeric else None))
            sql = f'SELECT * FROM "{table}"'
            if where: sql += f" WHERE {where}"
            if sc:    sql += f' ORDER BY "{sc}" {od}'
            sql += f" LIMIT {lim}"
            return sql, chart or "bar", f"{'Top' if od == 'DESC' else 'Bottom'} {lim} rows"

        if where:
            return (
                f'SELECT * FROM "{table}" WHERE {where} LIMIT {MAX_ROWS_DISPLAY}',
                chart or "table",
                f"{table} filtered",
            )

        if len(mcols) >= 2:
            return (
                f'SELECT "{mcols[0]}", "{mcols[1]}" FROM "{table}" LIMIT {MAX_ROWS_DISPLAY}',
                chart or "scatter",
                f"{mcols[0]} vs {mcols[1]}",
            )

        if len(mcols) == 1:
            col = mcols[0]
            if col in numeric:
                return (
                    f'SELECT "{col}" FROM "{table}" LIMIT {MAX_ROWS_DISPLAY}',
                    chart or "histogram",
                    f"{col} ka distribution",
                )
            return (
                f'SELECT "{col}", COUNT(*) AS count FROM "{table}" '
                f'GROUP BY "{col}" ORDER BY count DESC LIMIT 50',
                chart or "bar",
                f"Count by {col}",
            )

        return f'SELECT * FROM "{table}" LIMIT 50', chart or "table", f"{table} ka sample"

    # ── Detection Helper Methods ───────────────────────────────────────────────

    def _detect_equality_filter(self, text: str, col_names: list[str]) -> Optional[tuple[str, str]]:
        patterns = [
            r"whose\s+(.+?)\s+(?:is|=|==|equals?)\s+['\"]?([^\s'\"]+)['\"]?",
            r"where\s+(.+?)\s+(?:is|=|==|equals?)\s+['\"]?([^\s'\"]+)['\"]?",
            r"\b(.+?)\s+(?:is|=|==|equals?)\s+['\"]?([A-Z0-9][^\s'\"]{2,})['\"]?",
            r"with\s+(.+?)\s+['\"]?([A-Z0-9][^\s'\"]{2,})['\"]?",
            r"filter\s+by\s+(.+?)\s+['\"]?([^\s'\"]+)['\"]?",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if not m:
                continue
            col_hint = m.group(1).strip()
            val      = m.group(2).strip().strip("'\"")
            matched  = self._match_col(col_hint, col_names) or \
                       self._match_col(col_hint.replace(" ", "_"), col_names)
            if matched:
                return matched, val
        return None

    def _find_mentioned_tables(self, lower: str) -> list[str]:
        found = []
        for name in self.tables:
            for v in [name, name.replace("_", " "), name.replace("_", "-")]:
                if re.search(r"(?:^|[\s,'\"])" + re.escape(v) + r"(?:[\s,'\"]|$)", lower):
                    if name not in found:
                        found.append(name)
                    break
        return found

    def _detect_table(self, lower: str) -> str:
        for name in self.tables:
            if name in lower or name.replace("_", " ") in lower:
                return name
        return self.active or next(iter(self.tables), "")

    def _detect_agg(self, lower: str) -> Optional[str]:
        for phrase, func in sorted(self.AGG_MAP.items(), key=lambda x: -len(x[0])):
            if re.search(r"\b" + re.escape(phrase) + r"\b", lower):
                return func
        return None

    def _detect_chart(self, lower: str) -> str:
        for phrase, ct in sorted(self.CHART_MAP.items(), key=lambda x: -len(x[0])):
            if phrase in lower:
                return ct
        return ""

    def _detect_limit(self, lower: str) -> tuple[Optional[int], str]:
        m = re.search(r"\b(top|first)\s+(\d+)\b", lower)
        if m: return int(m.group(2)), "DESC"

        m = re.search(r"\b(bottom|last|worst)\s+(\d+)\b", lower)
        if m: return int(m.group(2)), "ASC"

        m = re.search(r"\blimit\s+(\d+)\b", lower)
        if m: return int(m.group(1)), "DESC"

        return None, "DESC"

    def _detect_group(self, lower: str, col_names: list[str]) -> Optional[str]:
        m = re.search(r"\b(?:group\s*by|per|for\s+each|by)\s+([\w_]+)", lower)
        if m:
            return self._match_col(m.group(1), col_names)
        return None

    def _detect_where(self, lower: str, col_names: list[str]) -> list[tuple]:
        conds = []
        m = re.search(r"\bwhere\s+(.+)", lower)
        if m:
            for part in re.split(r"\band\b", m.group(1)):
                wm = re.search(r"([\w_]+)\s*([><=!]+)\s*(\S+)", part.strip())
                if wm:
                    col = self._match_col(wm.group(1), col_names)
                    if col:
                        conds.append((col, wm.group(2), wm.group(3)))
        return conds

    def _build_where(self, conditions: list[tuple]) -> str:
        if not conditions:
            return ""
        parts = []
        for col, op, val in conditions:
            try:
                float(val)
                parts.append(f'"{col}" {op} {val}')
            except ValueError:
                parts.append(f'"{col}" {op} \'{val}\'')
        return " AND ".join(parts)

    def _find_columns(self, lower: str, col_names: list[str]) -> list[str]:
        found = []
        for col in sorted(col_names, key=len, reverse=True):
            for variant in [col.lower(), col.lower().replace("_", " ")]:
                if re.search(r"(?:^|[\s,])" + re.escape(variant) + r"(?:[\s,]|$)", lower):
                    if col not in found:
                        found.append(col)
                    break
        return found

    def _match_col(self, word: str, col_names: list[str]) -> str:
        if not word or not col_names:
            return ""
        w = word.lower().strip()

        for col in col_names:
            if col.lower() == w:
                return col

        for col in col_names:
            if (col.lower().replace("_", " ") == w or
                col.lower().replace("_", "") == w.replace(" ", "")):
                return col

        matches = get_close_matches(w, [c.lower() for c in col_names], n=1, cutoff=0.6)
        if matches:
            idx = [c.lower() for c in col_names].index(matches[0])
            return col_names[idx]

        return ""


# Module-level singleton
nlsql = NLToSQL()