"""
query_runner.py — DataGrid Intelligence · Query Execution Pipeline
==================================================================
Single entry point for all query execution, whether AI or offline.

Execution priority
------------------
  1. Learned memory   (query_memory.py  → find_similar)
  2. NLToSQL rules    (nl_sql.py        → NLToSQL.convert)
  3. Error response

When an AI key is available, the AI path runs first and its result
is also saved to memory for future offline use.
"""

from typing import Optional

import pandas as pd

from chart_utils import auto_chart, generate_chart
from config import ENGINE_BADGES, MAX_ROWS_DISPLAY
from db_engine import db, normalize_sql_table_names
from nl_sql import NLToSQL
from query_memory import memory


def _make_error(message: str, sql: str = "") -> dict:
    return {
        "type": "error", "mode": "error",
        "answer": message, "insights": "", "follow_ups": [],
        "sql": sql, "chart_type": "table", "chart": "",
        "table_data": [], "columns": [], "row_count": 0,
        "engine": "nlsql", "engine_badge": ENGINE_BADGES["nlsql"],
    }


def _make_result(
    source: str,
    sql: str,
    result_df: pd.DataFrame,
    explanation: str,
    chart_type: str,
    answer_prefix: str = "",
    insights: str = "",
    follow_ups: Optional[list] = None,
    engine: str = "nlsql",
) -> dict:
    row_count  = len(result_df)
    table_data = db.serialize_rows(result_df)
    columns    = result_df.columns.tolist()
    chart_json = ""
    if chart_type and chart_type != "table" and not result_df.empty:
        chart_json = generate_chart(result_df, chart_type, explanation[:80])
    if not chart_json and not result_df.empty:
        chart_json = auto_chart(result_df, explanation[:80])

    return {
        "type":        "result",
        "mode":        source,
        "answer":      f"{answer_prefix}\n{explanation}".strip() if answer_prefix else explanation,
        "insights":    insights,
        "follow_ups":  (follow_ups or [])[:3],
        "sql":         sql,
        "chart_type":  chart_type,
        "chart":       chart_json,
        "table_data":  table_data,
        "columns":     columns,
        "row_count":   row_count,
        "engine":      engine,
        "engine_badge": ENGINE_BADGES.get(engine, engine),
    }


def run_offline(text: str, target_tables: Optional[list] = None) -> dict:
    """
    Execute a query without AI.
    Tries: learned memory → NLToSQL rules.
    Automatically uses union views when multiple same-schema files are loaded.
    """
    if not db.tables:
        return _make_error("No tabular data loaded. Upload files first.")

    converter = NLToSQL()
    learned   = memory.find_similar(text, "")

    if learned:
        sql        = learned["sql"]
        chart_type = learned.get("chart_type", "table")
        explanation = learned.get("explanation", "")
        source     = "learned"
    elif target_tables and len(target_tables) > 1:
        from nl_sql import build_union_sql, ALL_DATA_KEYWORDS
        lim = None if any(w in text.lower() for w in ALL_DATA_KEYWORDS) else MAX_ROWS_DISPLAY
        sql = build_union_sql(target_tables, limit=lim)
        chart_type  = "table"
        explanation = f"Combined: {', '.join(target_tables)}"
        source      = "rules"
    else:
        sql, chart_type, explanation = converter.convert(text)
        source = "rules"

    if not sql:
        return _make_error("Could not generate SQL for this query. Try rephrasing.")

    try:
        result_df = db.execute(sql)
    except Exception as exc:
        return _make_error(
            f"Query failed.\nSQL: {sql}\nError: {exc}\n\n"
            "Tip: Try rephrasing, or check that the data files are uploaded.",
            sql=sql,
        )

    if result_df.empty and source == "learned":
        # Retry with rule engine (data may have changed)
        sql2, chart_type2, explanation2 = converter.convert(text)
        if sql2 and sql2 != sql:
            try:
                result_df  = db.execute(sql2)
                sql        = sql2
                chart_type = chart_type2
                explanation = explanation2
                source     = "rules-fallback"
            except Exception:
                pass  # Keep original empty result

    row_count = len(result_df)
    if row_count > 0 and source in ("rules", "rules-fallback"):
        memory.learn(text, sql, "", explanation, chart_type, row_count, allow_sql_update=False)

    prefix = {
        "learned":        "✅ Recalled from memory",
        "rules":          "⚙️ Rule-based SQL engine",
        "rules-fallback": "⚙️ Rule-based SQL engine (memory miss, re-run)",
    }.get(source, "⚙️")

    return _make_result(
        source=source, sql=sql, result_df=result_df,
        explanation=explanation, chart_type=chart_type,
        answer_prefix=prefix,
    )


def run_ai_result(ai: dict, text: str, active_table: str) -> dict:
    """
    Post-process an AI response dict: execute the SQL, generate chart,
    save to memory, and return a result dict.
    """
    engine     = ai.get("_engine", "nlsql")
    answer     = ai.get("answer", "")
    sql        = (ai.get("sql") or "").strip().rstrip(";")
    chart_type = (ai.get("chart_type") or "table").strip()
    insights   = ai.get("insights", "")
    follow_ups = ai.get("follow_ups", [])

    if sql:
        sql = normalize_sql_table_names(sql)
        try:
            result_df = db.execute(sql)
            row_count = len(result_df)
            if row_count > 0:
                memory.learn(text, sql, active_table, answer[:100], chart_type, row_count)
            return _make_result(
                source="ai", sql=sql, result_df=result_df,
                explanation=answer, chart_type=chart_type,
                insights=insights, follow_ups=follow_ups, engine=engine,
            )
        except Exception as exc:
            answer += f"\n\n⚠️ SQL error: {exc}"

    return {
        "type": "result", "mode": "ai",
        "answer": answer, "insights": insights, "follow_ups": follow_ups[:3],
        "sql": sql, "chart_type": chart_type, "chart": "",
        "table_data": [], "columns": [], "row_count": 0,
        "engine": engine, "engine_badge": ENGINE_BADGES.get(engine, engine),
    }