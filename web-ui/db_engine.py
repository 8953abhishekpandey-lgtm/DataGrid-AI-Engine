"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  db_engine.py  —  DataGrid Intelligence · DuckDB Engine                    ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Is file mein saara database logic hai:                                     ║
║    • Parquet files ko DuckDB tables mein register karna                     ║
║    • Same-schema files ko automatically UNION ALL view mein combine karna   ║
║    • SQL execute karna                                                      ║
║    • Results serialize karna (JSON-safe format mein)                        ║
║                                                                             ║
║  Multi-File Union Kaise Kaam Karta Hai:                                    ║
║    1. Jab koi parquet upload hoti hai, uske columns ka MD5 hash banate hain ║
║    2. Same hash wale files ek "schema group" mein jaate hain                ║
║    3. Us group ka ek UNION ALL view banta hai DuckDB mein                  ║
║    4. Sab se bade group ka alias "_all_data" hota hai                      ║
║    5. "show all data" jaise queries automatically sab files pe chalti hain  ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import hashlib        # MD5 hash banane ke liye — schema fingerprint ke liye use hota hai
import re             # Regular expressions — SQL cleaning ke liye
from typing import Optional  # Type hints ke liye — Optional matlab value ya None

import duckdb         # In-process SQL database — parquet files pe fast queries
import pandas as pd   # DataFrames ke liye — data manipulation

from config import MAX_ROWS_DISPLAY  # Maximum rows limit config se import


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: COLUMN HELPER FUNCTIONS
# DataFrame ke columns ke baare mein information extract karne ke functions
# ══════════════════════════════════════════════════════════════════════════════

def get_column_info(df: pd.DataFrame) -> list[dict]:
    """
    DataFrame ke har column ka naam aur data type return karta hai.

    Returns: list of dicts, example:
        [{"name": "Meter_ID", "dtype": "text"},
         {"name": "Status",   "dtype": "text"},
         {"name": "GPS_LAT",  "dtype": "numeric"}]
    """
    cols = []  # result list jo return hogi

    for col in df.columns:              # har column ke liye loop
        dtype = str(df[col].dtype)      # pandas dtype string mein convert karo

        # Dtype string se column type determine karo
        if "int" in dtype or "float" in dtype:
            col_type = "numeric"        # integers aur floats = numeric
        elif "datetime" in dtype or "date" in dtype:
            col_type = "date"           # datetime types = date
        elif "bool" in dtype:
            col_type = "boolean"        # boolean type
        else:
            col_type = "text"           # baaki sab = text (object, string, category)

        cols.append({"name": str(col), "dtype": col_type})
        # str(col) ensure karta hai ki column name string hi ho

    return cols  # column info ki list return karo


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    DataFrame ko clean karta hai:
      - Strings se whitespace hatata hai
      - 'nan', 'None', 'NULL', '' ko actual None (null) mein convert karta hai
      - Completely empty rows hatata hai
      - Duplicate rows hatata hai
      - Date-like columns ko datetime format mein convert karne ki koshish karta hai

    Returns: cleaned DataFrame
    """
    # Saare object (string) columns clean karo
    for col in df.select_dtypes(include="object").columns:
        # include="object" = sirf string/object dtype columns select karo

        df[col] = df[col].astype(str).str.strip()
        # .astype(str) = sab kuch string mein convert karo (NaN bhi)
        # .str.strip() = har value se leading/trailing whitespace hatao

        df[col] = df[col].replace({"nan": None, "None": None, "NULL": None, "": None})
        # String "nan", "None", "NULL", empty string ko actual Python None mein convert karo
        # Ye important hai warna "nan" as text query mein problem create karta hai

    df = df.dropna(how="all")
    # Sirf wo rows hatao jahan ALL columns None/NaN hain
    # how="all" matlab: row tab hategi jab sab columns empty hon

    df = df.drop_duplicates()
    # Bilkul same content wali duplicate rows hatao
    # Default sab columns pe check karta hai

    # Date columns automatically detect karo aur convert karo
    date_hints = ["date", "time", "timestamp", "dt", "period", "month", "year"]
    # ^ Agar column name mein ye words hain toh likely datetime column hai

    for col in df.columns:
        # Sirf string columns check karo (already datetime columns skip)
        if any(h in col.lower() for h in date_hints) and df[col].dtype == object:
            try:
                df[col] = pd.to_datetime(df[col], infer_datetime_format=True, errors="coerce")
                # infer_datetime_format=True = multiple formats try karo
                # errors="coerce" = agar convert na ho toh NaT (Not a Time) rakh do, error mat do
            except Exception:
                pass  # Conversion fail ho toh silently skip karo

    return df  # cleaned DataFrame return karo


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: SQL TABLE NAME NORMALISER
# Purane stored queries mein "Equipment" (quoted) tha, ab Equipment (unquoted) chahiye
# DuckDB case-insensitive unquoted identifiers resolve karta hai
# ══════════════════════════════════════════════════════════════════════════════

# Map: purana format (double-quoted) → naya format (unquoted CamelCase)
# Ye saare common variations cover karta hai jo stored queries mein mil sakti hain
_TABLE_QUOTE_MAP: dict[str, str] = {
    '"Equipment"':          "Equipment",          # CamelCase quoted → unquoted
    '"equipment"':          "Equipment",          # lowercase quoted → CamelCase unquoted
    '"Consumer"':           "Consumer",
    '"consumer"':           "Consumer",
    '"Device_Location"':    "Device_Location",
    '"device_location"':    "Device_Location",
    '"DevLoc_Device_Link"': "DevLoc_Device_Link",
    '"devloc_device_link"': "DevLoc_Device_Link",
    '"ConsumerDevLocLink"': "ConsumerDevLocLink",
    '"consumerdevloclink"': "ConsumerDevLocLink",
    '"Material_Master"':    "Material_Master",
    '"material_master"':    "Material_Master",
    '"HES_MASTER"':         "HES_MASTER",
    '"hes_master"':         "HES_MASTER",
}


def normalize_sql_table_names(sql: str) -> str:
    """
    SQL mein double-quoted table names ko unquoted CamelCase mein replace karta hai.

    Kyo zaroorat hai:
      - Old stored queries mein "Equipment" (quoted) tha
      - DuckDB lowercase mein tables register karta hai
      - Quoted names case-sensitive hote hain → mismatch → error
      - Unquoted names case-insensitive hote hain → hamesha kaam karta hai

    Column names ("Meter_ID") ko touch nahi karta — woh case-sensitive hain.
    """
    for quoted, unquoted in _TABLE_QUOTE_MAP.items():
        sql = sql.replace(quoted, unquoted)  # simple string replacement
    return sql  # normalized SQL return karo


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: DBENGINE CLASS
# Main database engine class — singleton pattern use karta hai
# Ek hi instance puri application mein use hota hai (module level 'db' variable)
# ══════════════════════════════════════════════════════════════════════════════

class DBEngine:
    """
    DuckDB wrapper class jo multi-file Parquet queries handle karta hai.

    Attributes:
        conn           — DuckDB connection object
        tables         — {table_name: DataFrame} mapping
        table_columns  — {table_name: [col_info]} mapping
        schema_groups  — {schema_key: [table_names]} — same-schema files groups
        active_table   — currently selected table ka naam
    """

    def __init__(self):
        self.conn: duckdb.DuckDBPyConnection = duckdb.connect()
        # ^ In-memory DuckDB connection create karo (no file, pure RAM)
        # Agar persistent chahiye: duckdb.connect("database.duckdb")

        self.tables:        dict[str, pd.DataFrame] = {}
        # ^ Registered tables ka dict: naam → DataFrame

        self.table_columns: dict[str, list[dict]]   = {}
        # ^ Har table ke column info: naam → [{"name": ..., "dtype": ...}]

        self.schema_groups: dict[str, list[str]]    = {}
        # ^ Schema groups: MD5_hash → [table_names_with_same_columns]
        # Same columns wale tables ek group mein hote hain

        self.active_table:  str = ""
        # ^ Currently active/selected table ka naam (UI mein selected)


    # ── HELPER: Schema Key ─────────────────────────────────────────────────────
    def _schema_key(self, df: pd.DataFrame) -> str:
        """
        DataFrame ke columns ka unique fingerprint (MD5 hash) return karta hai.
        Same columns wale tables ka same key hoga → same schema group mein jayenge.

        Process:
          1. Sab column names lowercase karo
          2. Sort karo (order matter nahi karna chahiye)
          3. Comma se join karo
          4. MD5 hash lo, pehle 10 characters use karo
        """
        cols = sorted(c.lower() for c in df.columns)
        # sorted() ensure karta hai ki column order se key change na ho
        # lower() ensure karta hai ki case-insensitive comparison ho

        return hashlib.md5(",".join(cols).encode()).hexdigest()[:10]
        # hashlib.md5() → MD5 hash object
        # .encode() → string ko bytes mein convert karo (md5 ko bytes chahiye)
        # .hexdigest() → 32-char hex string
        # [:10] → sirf pehle 10 chars use karo (collision risk negligible hai)


    # ── REGISTER TABLE ─────────────────────────────────────────────────────────
    def register_table(self, name: str, df: pd.DataFrame) -> None:
        """
        Ek DataFrame ko DuckDB table ke roop mein register karta hai.

        Steps:
          1. DataFrame clean karo
          2. Memory mein store karo (self.tables)
          3. Column info save karo
          4. DuckDB mein table create karo (ya replace karo)
          5. Schema group mein add karo
          6. Union views rebuild karo
        """
        df = clean_dataframe(df)           # pehle data clean karo

        self.tables[name]        = df      # DataFrame Python memory mein store karo
        self.table_columns[name] = get_column_info(df)  # column info save karo

        # Agar table pehle se exist karti hai toh drop karo
        try:
            self.conn.execute(f'DROP TABLE IF EXISTS "{name}"')
            # f-string se table name insert karo
            # IF EXISTS = agar nahi hai toh error mat do
        except Exception:
            pass  # Error silently ignore karo

        # Naya table create karo DataFrame se
        self.conn.execute(f'CREATE TABLE "{name}" AS SELECT * FROM df')
        # df = local variable hai jahan DataFrame stored hai
        # DuckDB automatically df ko pandas DataFrame ke roop mein recognize karta hai

        # Schema group mein add karo
        key   = self._schema_key(df)                    # is DataFrame ka schema key
        group = self.schema_groups.setdefault(key, [])  # existing group ya empty list
        # setdefault: agar key nahi hai toh empty list set karo aur return karo
        if name not in group:
            group.append(name)  # table naam group mein add karo (agar already nahi hai)

        # Union views rebuild karo (naya table add hua hai)
        self._rebuild_union_view(key)      # is schema group ka union view update karo
        self._rebuild_all_data_alias()     # _all_data alias update karo
        self.active_table = name           # naya table active table ban jata hai


    # ── UNREGISTER TABLE ───────────────────────────────────────────────────────
    def unregister_table(self, name: str) -> None:
        """
        Table ko memory aur DuckDB se remove karta hai.
        Related union views bhi update karta hai.
        """
        self.tables.pop(name, None)        # Python dict se remove karo (error nahi agar nahi hai)
        self.table_columns.pop(name, None) # Column info bhi remove karo

        try:
            self.conn.execute(f'DROP TABLE IF EXISTS "{name}"')  # DuckDB se table drop karo
        except Exception:
            pass  # Silently ignore karo

        # Schema groups update karo — is table ko groups se hata do
        for key, group in list(self.schema_groups.items()):
            # list() use kara iterate while modifying ke liye safe approach

            if name not in group:
                continue  # Ye group isme nahi hai, skip karo

            group.remove(name)  # group se ye table naam hatao

            if not group:       # agar group ab khali ho gayi
                del self.schema_groups[key]           # schema group delete karo
                try:
                    self.conn.execute(f'DROP VIEW IF EXISTS "_union_{key}"')
                    # Empty group ka union view bhi hata do
                except Exception:
                    pass
            else:
                self._rebuild_union_view(key)  # Group mein aur tables hain, union rebuild karo

        self._rebuild_all_data_alias()  # _all_data alias update karo

        # Active table update karo agar ye wahi tha jo delete hua
        if self.active_table == name:
            self.active_table = next(iter(self.tables), "")
            # next(iter(...), "") = pehla table jo dict mein hai, ya empty string
            # iter() dictionary ko iterable banata hai, next() pehla item leta hai


    # ── BUILD UNION VIEW ───────────────────────────────────────────────────────
    def _rebuild_union_view(self, key: str) -> None:
        """
        Ek schema group ke saare tables ka UNION ALL view banata hai DuckDB mein.

        View naam: "_union_<key>"
        Har row mein extra column hota hai: _source_file (kis file se aai)

        Example SQL generated:
            CREATE VIEW "_union_abc123" AS
            SELECT "col1", "col2", 'file1' AS _source_file FROM "file1"
            UNION ALL
            SELECT "col1", "col2", 'file2' AS _source_file FROM "file2"
        """
        group = self.schema_groups.get(key, [])   # is key ke tables ki list
        view  = f"_union_{key}"                   # view ka naam

        # Pehle old view drop karo agar exist karti hai
        try:
            self.conn.execute(f'DROP VIEW IF EXISTS "{view}"')
        except Exception:
            pass

        if not group:
            return  # Group khali hai, koi view nahi banana

        # Sab tables mein common columns find karo
        col_sets = [
            set(c["name"] for c in self.table_columns.get(t, []))
            # Har table ke column names ka set banao
            for t in group
            if t in self.table_columns  # sirf registered tables consider karo
        ]

        if not col_sets:
            return  # Koi column info nahi hai

        # Set intersection: sab tables mein jo columns hain woh common hain
        common = col_sets[0]          # pehle set se start karo
        for s in col_sets[1:]:        # baaki sets se intersect karo
            common &= s               # &= = set intersection (dono mein jo ho)

        # Common columns ki quoted SQL list banao
        col_list = ", ".join(f'"{c}"' for c in sorted(common))
        # sorted() = consistent order ke liye

        # Har table ke liye ek SELECT statement banao
        parts = [
            f"SELECT {col_list}, '{t}' AS _source_file FROM \"{t}\""
            # '{t}' = table naam as string literal (kaunsi file se data)
            # AS _source_file = naya column ka naam
            for t in group
        ]

        # UNION ALL se sab SELECT statements join karo
        union_sql = "\nUNION ALL\n".join(parts)
        # UNION ALL = sab rows raho (duplicates remove mat karo)
        # vs UNION = duplicate rows remove karta hai (slow)

        try:
            self.conn.execute(f'CREATE VIEW "{view}" AS {union_sql}')
            # View create karo — actual data copy nahi hoti, sirf SQL definition store hoti hai
        except Exception as e:
            print(f"  [db] Warning: union view {view} nahi bana: {e}")


    # ── ALL_DATA ALIAS ─────────────────────────────────────────════════════────
    def _rebuild_all_data_alias(self) -> None:
        """
        "_all_data" naam ka ek convenience view banata hai jo largest schema group
        ki union view ko point karta hai.

        Use case: User jab "show all data" bolata hai, system automatically
        "_all_data" view use karta hai jismein sab same-schema files hain.
        """
        try:
            self.conn.execute('DROP VIEW IF EXISTS "_all_data"')  # purana alias hata do
        except Exception:
            pass

        if not self.schema_groups:
            return  # Koi tables nahi hain, alias banana bekaar hai

        # Sabse bade group ko dhundho (jisme sabse zyada files hain)
        best_key = max(self.schema_groups, key=lambda k: len(self.schema_groups[k]))
        # max() ke saath key= argument use karo
        # lambda function har key ke liye group size return karta hai
        # max() wo key choose karta hai jiske liye value sabse badi ho

        best_group = self.schema_groups[best_key]  # us key ki group list
        if not best_group:
            return  # Group khali hai

        try:
            self.conn.execute(
                f'CREATE VIEW "_all_data" AS SELECT * FROM "_union_{best_key}"'
                # _all_data view = largest group ki union view ka alias
            )
        except Exception:
            pass  # Silently ignore (already handled union view mein)


    # ── INTROSPECTION HELPERS ──────────────────────────────────────────────────
    def get_best_union_view(self) -> tuple[Optional[str], list[str]]:
        """
        Sabse bade schema group ki union view ka naam aur files ki list return karta hai.

        Returns: (view_name, file_list) ya (None, []) agar koi group nahi hai
        """
        if not self.schema_groups:
            return None, []  # Koi groups nahi hain

        # Largest group dhundho
        best_key  = max(self.schema_groups, key=lambda k: len(self.schema_groups[k]))
        group     = self.schema_groups[best_key]
        if not group:
            return None, []

        return f"_union_{best_key}", group  # view naam aur files ki list return karo


    def get_all_union_views(self) -> list[dict]:
        """
        Saare schema groups ki information return karta hai.
        UI status display ke liye use hota hai.

        Returns: [{"view": ..., "key": ..., "tables": [...], "count": N}, ...]
        """
        result = []
        for key, group in self.schema_groups.items():
            result.append({
                "view":   f"_union_{key}",  # DuckDB mein view ka naam
                "key":    key,              # schema fingerprint
                "tables": list(group),      # is group mein kaunsi files hain
                "count":  len(group),       # kitni files hain
            })
        return result


    def union_view_columns(self, view_name: str) -> list[dict]:
        """
        Ek union view ke column info return karta hai (group ke pehle table se).
        NL→SQL engine column names jaanne ke liye use karta hai.
        """
        for key, group in self.schema_groups.items():
            if f"_union_{key}" == view_name and group:  # matching view dhundho
                return self.table_columns.get(group[0], [])
                # group[0] = pehla table = representative table for schema
        return []  # View nahi mila


    # ── SQL EXECUTION ──────────────────────────────────────────────────────────
    def execute(self, sql: str) -> pd.DataFrame:
        """
        SQL query execute karke result DataFrame return karta hai.
        Error handling calling code mein hona chahiye.
        """
        return self.conn.execute(sql).fetchdf()
        # .execute() = SQL run karo
        # .fetchdf() = results ko pandas DataFrame mein convert karo


    def validate(self, sql: str) -> bool:
        """
        SQL execute kiye bina check karta hai ki kya SQL valid hai.
        LIMIT 0 use karta hai taki koi actual data fetch na ho — sirf syntax check.

        Returns: True agar SQL valid hai, False agar error hai
        """
        if not sql:
            return False  # Empty SQL invalid hai

        try:
            self.conn.execute(f"SELECT * FROM ({sql}) _chk LIMIT 0")
            # SQL ko subquery mein wrap karo aur LIMIT 0 lagao
            # Ye SQL parse aur validate karta hai bina data fetch kiye
            return True   # Koi error nahi = valid SQL
        except Exception:
            return False  # Exception = invalid SQL


    # ── RESULT SERIALISATION ───────────────────────────────────────────────────
    def serialize_rows(self, df: pd.DataFrame, max_rows: int = MAX_ROWS_DISPLAY) -> list[dict]:
        """
        DataFrame rows ko JSON-safe Python dicts mein convert karta hai.

        JSON problematic values handle karta hai:
          - float NaN/Infinity → None
          - datetime objects → ISO format string
          - bytes → hex string
          - unknown types → str()
          - Normal types (str, int, float, bool, None) → as-is

        Returns: list of dicts (JSON serializable)
        """
        rows = df.head(max_rows).to_dict(orient="records")
        # .head(max_rows) = sirf max_rows tak rows lo
        # .to_dict(orient="records") = har row ek dict banta hai
        # [{"col1": val1, "col2": val2}, ...]

        for row in rows:              # har row ke liye
            for k, v in row.items():  # har column ke liye

                if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
                    row[k] = None
                    # v != v = NaN check (NaN is not equal to itself — IEEE 754 property)
                    # float("inf") = positive infinity
                    # float("-inf") = negative infinity
                    # JSON mein NaN/Infinity invalid hain, isliye None use karo

                elif hasattr(v, "isoformat"):
                    row[k] = v.isoformat()
                    # datetime, date, time objects ka .isoformat() method hota hai
                    # Example: datetime(2024,1,15) → "2024-01-15T00:00:00"

                elif isinstance(v, (bytes, bytearray)):
                    row[k] = v.hex()
                    # bytes ko hex string mein convert karo
                    # Example: b'\x00\xff' → "00ff"

                elif not isinstance(v, (str, int, float, bool, type(None))):
                    row[k] = str(v)
                    # Baaki sab types (numpy types, custom objects, etc.) string mein

        return rows  # JSON-safe rows return karo


    # ── TABLE SUMMARY ──────────────────────────────────────────────────────────
    def table_summary(self) -> list[dict]:
        """
        Saare registered tables ki summary return karta hai.
        /status API endpoint ke liye use hota hai.

        Returns: [{"name": ..., "rows": N, "columns": [...], "sample": [...]}, ...]
        """
        result = []
        for name, df in self.tables.items():  # har table ke liye
            result.append({
                "name":    name,                                # table ka naam
                "rows":    len(df),                            # total row count
                "columns": self.table_columns.get(name, []),  # column info list
                "sample":  self.serialize_rows(df.head(3), max_rows=3),
                # .head(3) = sirf pehli 3 rows as preview
            })
        return result


    # ── DATA CONTEXT BUILDER ───────────────────────────────────────────────────
    def build_data_context(
        self, include_doc_text: bool = True, documents: dict = None
    ) -> str:
        """
        AI system prompt ke liye data context string banata hai.
        AI ko batata hai ki kaun kaun si tables aur documents loaded hain.

        Args:
            include_doc_text: documents ka text include karna hai ya nahi
            documents: {name: doc_dict} documents dict (app.py se pass hota hai)

        Returns: formatted string jaise AI ke system prompt mein jaati hai
        """
        parts = []  # string parts ki list (end mein join hogi)

        # ── Tabular tables section ─────────────────────────────────────────────
        if self.tables:
            parts.append("=== TABULAR DATASETS (Parquet Files) ===")

            for name, df in self.tables.items():
                cols     = self.table_columns.get(name, [])
                col_desc = ", ".join(f'{c["name"]}({c["dtype"]})' for c in cols)
                # Example: "Meter_ID(text), Status(text), GPS_LAT(numeric)"

                parts.append(f'\nTable "{name}": {len(df):,} rows × {len(df.columns)} cols')
                # :, = thousands separator, × = multiplication symbol
                parts.append(f"  Columns: {col_desc}")

                # Numeric columns ke statistics add karo (AI ko context dene ke liye)
                num_cols = [c["name"] for c in cols if c["dtype"] == "numeric"]
                if num_cols and len(df) > 0:
                    stats = []
                    for nc in num_cols[:3]:   # max 3 numeric columns ke stats
                        try:
                            stats.append(
                                f"{nc}: min={df[nc].min():.2f}, "
                                f"max={df[nc].max():.2f}, "
                                f"avg={df[nc].mean():.2f}"
                            )
                            # :.2f = 2 decimal places
                        except Exception:
                            pass  # Calculation fail ho toh skip
                    if stats:
                        parts.append(f"  Stats: {'; '.join(stats)}")

                # Sample row (AI ko data format samajhne mein help karta hai)
                if len(df) > 0:
                    sample = df.head(1).to_dict(orient="records")[0]  # pehli row
                    s_str  = ", ".join(
                        f"{k}={repr(v)}"  # repr() quotes strings properly
                        for k, v in list(sample.items())[:6]  # max 6 columns
                    )
                    parts.append(f"  Sample: {s_str}")

        # ── Union views section ────────────────────────────────────────────────
        union_views = self.get_all_union_views()
        if union_views:
            parts.append("\n=== MULTI-FILE UNION VIEWS ===")
            for uv in union_views:
                parts.append(
                    f'  "{uv["view"]}" = {uv["count"]} files ka UNION: '
                    f'{", ".join(uv["tables"])}'
                )
            parts.append('  "_all_data" = sabse bade group ka alias (easy access)')

        # ── Documents section ──────────────────────────────────────────────────
        if documents:
            parts.append("\n=== DOCUMENTS ===")
            for name, doc in documents.items():
                parts.append(f'\nDocument "{name}" [{doc["format"]}]: {doc["filename"]}')
                parts.append(f'  Size: {doc["size"]:,} characters')
                if include_doc_text:
                    parts.append(f'  Content:\n{doc["text"][:4000]}')
                    # Sirf pehle 4000 characters include karo (token limit bachao)

        # Kuch bhi load nahi hua
        if not self.tables and not documents:
            return "Koi data load nahi hua. Pehle Parquet files upload karo."

        return "\n".join(parts)  # sab parts ko newline se join karke return karo


# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL SINGLETON
# Puri application mein ek hi DBEngine instance hoga
# Import karo: from db_engine import db
# ══════════════════════════════════════════════════════════════════════════════

db = DBEngine()
# ^ Ye line module import hone pe ek baar execute hoti hai
# Sab jagah se "from db_engine import db" karke same instance milti hai