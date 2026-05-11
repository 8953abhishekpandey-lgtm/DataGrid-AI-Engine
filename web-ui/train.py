#!/usr/bin/env python3
"""
train.py — DataGrid Intelligence · Training CLI
================================================
Use this script to train the system WITHOUT needing an API key.
All training is saved to learned_queries.json.

COMMANDS
--------
  python train.py list                          # List all patterns (sorted by count)
  python train.py stats                         # Training statistics
  python train.py add                           # Interactive wizard
  python train.py add --text "..." --sql "..."  # Direct add
  python train.py remove --text "..."           # Remove a pattern
  python train.py test --text "..."             # Test pattern recall
  python train.py test-sql --sql "..."          # Test SQL against live DuckDB
  python train.py import --file queries.json    # Bulk import from JSON
  python train.py export --file out.json        # Export all patterns
  python train.py lock --text "..."             # Mark pattern as locked (count=200)
  python train.py fix --text "..." --sql "..."  # Fix/update just the SQL
  python train.py ai-generate --text "..."      # Use AI to generate SQL for query
  python train.py ai-batch --file questions.txt # Batch AI training from text file
  python train.py seed                          # Re-load seeded queries from learned_queries_seed.json
  python train.py purge-auto                    # Remove all auto-learned (non-trained) patterns

HOW TO TRAIN WELL (Quick Guide)
---------------------------------
1. Start the app and ask a question that gives the WRONG result.
2. Note the question text exactly.
3. Write the correct DuckDB SQL manually.
4. Run:   python train.py add --text "your question" --sql "SELECT ..."
5. Re-test in the browser — it should now return the correct result.

To train from a CSV of questions: create questions.txt (one per line),
then run: python train.py ai-batch --file questions.txt
(This requires ANTHROPIC_API_KEY or GEMINI_API_KEY in .env)

TRAINING TIPS
-------------
- Use --lock for critical patterns you never want overwritten
- Patterns with count ≥ 20 are treated as manually trusted
- Patterns with count ≥ 200 are locked (never pruned)
- Run `python train.py stats` regularly to audit quality
"""

import argparse
import json
import os
import sys
from pathlib import Path

# ── Setup path ────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from config import MEMORY_FILE, print_banner
from db_engine import db, normalize_sql_table_names
from query_memory import memory


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


def _green(text: str) -> str:
    return f"\033[32m{text}\033[0m"


def _red(text: str) -> str:
    return f"\033[31m{text}\033[0m"


def _yellow(text: str) -> str:
    return f"\033[33m{text}\033[0m"


def _print_pattern(p: dict, idx: int = None) -> None:
    prefix = f"[{idx:3d}] " if idx is not None else "  "
    trained = "🔒 LOCKED" if p.get("count", 0) >= 200 else ("✅ TRAINED" if p.get("trained") else "🤖 AUTO")
    print(f"{prefix}{_bold(p['text'][:80])}")
    print(f"       Count: {p.get('count', 0):3d}  Chart: {p.get('chart_type', 'table')}  {trained}")
    if p.get("sql"):
        print(f"       SQL: {p['sql'][:100]}{'…' if len(p['sql']) > 100 else ''}")
    print()


# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_list(args):
    pats = sorted(memory.patterns, key=lambda x: x.get("count", 0), reverse=True)
    filter_text = (args.filter or "").lower()
    shown = 0
    for i, p in enumerate(pats):
        if filter_text and filter_text not in p.get("text", "").lower():
            continue
        _print_pattern(p, i)
        shown += 1
        if shown >= (args.limit or 50):
            break
    print(f"  Showing {shown}/{len(pats)} patterns (use --limit N for more, --filter TEXT to search)")


def cmd_stats(args):
    s = memory.stats()
    print(_bold("=== Training Statistics ==="))
    print(f"  Total patterns   : {s['total']}")
    print(f"  Manually trained : {_green(str(s['trained']))}")
    print(f"  Auto-learned     : {s['auto_learned']}")
    print(f"  Locked (≥200)    : {_yellow(str(s['locked']))}")
    print(f"\n  Chart type breakdown:")
    for ct, n in sorted(s["chart_types"].items(), key=lambda x: -x[1]):
        print(f"    {ct:12s}: {n}")
    print(f"\n  Top 5 most-used patterns:")
    for i, t in enumerate(s["top5"], 1):
        print(f"    {i}. [{t['count']:3d}] {t['text'][:70]}")


def cmd_add(args):
    if args.text and args.sql:
        text        = args.text.strip()
        sql         = args.sql.strip()
        explanation = args.explanation or ""
        chart_type  = args.chart or "table"
        lock        = args.lock or False
    else:
        # Interactive wizard
        print(_bold("=== Add Training Pattern ==="))
        print("Enter the natural language query (the question users will ask):")
        text = input("  Question: ").strip()
        if not text:
            print(_red("Cancelled."))
            return

        print("\nEnter the DuckDB SQL (press Enter twice when done):")
        lines = []
        while True:
            line = input()
            if line == "" and lines and lines[-1] == "":
                break
            lines.append(line)
        sql = "\n".join(lines).strip().rstrip(";")
        if not sql:
            print(_red("Cancelled — no SQL entered."))
            return

        print("\nChart type (bar/line/pie/scatter/histogram/area/table) [table]:")
        chart_type  = input("  Chart: ").strip() or "table"
        print("Explanation (short description) [optional]:")
        explanation = input("  Explanation: ").strip()
        print("Lock this pattern? Locked patterns are never auto-overwritten. (y/n) [n]:")
        lock        = input("  Lock: ").strip().lower() == "y"

    result = memory.add_training(
        text=text, sql=sql, explanation=explanation,
        chart_type=chart_type, lock=lock,
    )
    print(_green(f"\n✅ Pattern {result}: '{text[:60]}'"))
    print(f"   Total patterns: {len(memory.patterns)}")


def cmd_remove(args):
    if not args.text:
        print(_red("--text is required"))
        return
    removed = memory.remove_pattern(args.text.strip())
    if removed:
        print(_green(f"✅ Removed: '{args.text[:60]}'"))
    else:
        print(_yellow(f"⚠️  Pattern not found: '{args.text[:60]}'"))
        print("   Try: python train.py list --filter 'keywords'")


def cmd_test(args):
    if not args.text:
        print(_red("--text is required"))
        return
    text   = args.text.strip()
    result = memory.find_similar(text)
    if result:
        print(_green(f"✅ Matched pattern (confidence: {result.get('confidence', 0):.2f})"))
        print(f"  Original text : {result.get('text', '')}")
        print(f"  Explanation   : {result.get('explanation', '')}")
        print(f"  Chart type    : {result.get('chart_type', 'table')}")
        print(f"  SQL:\n{result['sql']}")
    else:
        print(_yellow(f"⚠️  No pattern matched for: '{text}'"))
        # Show closest
        from difflib import SequenceMatcher
        def _score(p):
            n1 = memory._normalize(text)
            n2 = memory._pattern_norm(p)
            return SequenceMatcher(None, n1, n2).ratio()
        closest = sorted(memory.patterns, key=_score, reverse=True)[:3]
        if closest:
            print("\n  Closest patterns:")
            for p in closest:
                print(f"    [{_score(p):.2f}] {p.get('text', '')[:70]}")
        print("\n  To add this: python train.py add --text \"...\" --sql \"SELECT ...\"")


def cmd_test_sql(args):
    """Test a SQL query against the live DuckDB (tables must be loaded via the app first,
    but you can also point to parquet files directly here)."""
    if not args.sql:
        print(_red("--sql is required"))
        return
    sql = normalize_sql_table_names(args.sql.strip().rstrip(";"))

    # If parquet files are provided, load them first
    if args.files:
        import pandas as pd
        for fp in args.files:
            p = Path(fp)
            if not p.exists():
                print(_red(f"File not found: {fp}"))
                continue
            name = p.stem.lower()[:64]
            df   = pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p)
            db.register_table(name, df)
            print(f"  Loaded: {fp} → table '{name}' ({len(df):,} rows)")

    if not db.tables:
        print(_yellow("⚠️  No tables loaded. Use --files to specify parquet files."))
        print("   Example: python train.py test-sql --sql \"SELECT ...\" --files data.parquet")
        return

    try:
        result = db.execute(sql)
        print(_green(f"✅ Query succeeded: {len(result):,} rows"))
        print(result.head(5).to_string())
    except Exception as e:
        print(_red(f"❌ SQL error: {e}"))


def cmd_import(args):
    if not args.file:
        print(_red("--file is required"))
        return
    p = Path(args.file)
    if not p.exists():
        print(_red(f"File not found: {args.file}"))
        return
    try:
        added, updated = memory.import_patterns(p)
        print(_green(f"✅ Imported: {added} added, {updated} updated"))
        print(f"   Total patterns: {len(memory.patterns)}")
    except Exception as e:
        print(_red(f"❌ Import failed: {e}"))


def cmd_export(args):
    dest = Path(args.file) if args.file else Path("learned_queries_export.json")
    count = memory.export_patterns(dest)
    print(_green(f"✅ Exported {count} patterns → {dest}"))


def cmd_lock(args):
    if not args.text:
        print(_red("--text is required"))
        return
    result = memory.find_similar(args.text.strip())
    if not result:
        print(_yellow(f"⚠️  Pattern not found: '{args.text}'"))
        return
    memory.add_training(
        text        = result.get("text", args.text),
        sql         = result["sql"],
        explanation = result.get("explanation", ""),
        chart_type  = result.get("chart_type", "table"),
        lock        = True,
    )
    print(_green(f"✅ Locked: '{args.text[:60]}'"))


def cmd_fix(args):
    if not args.text or not args.sql:
        print(_red("--text and --sql are required"))
        return
    updated = memory.update_sql(args.text.strip(), args.sql.strip())
    if updated:
        print(_green(f"✅ SQL updated for: '{args.text[:60]}'"))
    else:
        # Add as new
        memory.add_training(text=args.text.strip(), sql=args.sql.strip(),
                            explanation="", chart_type="table")
        print(_green(f"✅ Pattern added (was not found, created new): '{args.text[:60]}'"))


def cmd_purge_auto(args):
    before = len(memory.patterns)
    memory.patterns = [p for p in memory.patterns if p.get("trained") or p.get("count", 0) >= 20]
    memory._save()
    after  = len(memory.patterns)
    print(_green(f"✅ Purged {before - after} auto-learned patterns (kept {after})"))


def cmd_ai_generate(args):
    """Use the configured AI to generate SQL for a query and save it."""
    if not args.text:
        print(_red("--text is required"))
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print(_red("❌ No API key found. Set ANTHROPIC_API_KEY or GEMINI_API_KEY in .env"))
        return

    print(f"  Asking AI: '{args.text}'")
    try:
        from ai_engines import call_ai_sync
        result = call_ai_sync(args.text, [])
        sql    = (result.get("sql") or "").strip().rstrip(";")
        if not sql:
            print(_yellow("⚠️  AI returned no SQL for this query."))
            print(f"  Answer: {result.get('answer', '')[:200]}")
            return
        chart   = result.get("chart_type", "table")
        explain = result.get("answer", "")[:100]
        print(_green(f"  ✅ SQL generated:"))
        print(f"  {sql[:200]}")
        print(f"  Chart: {chart}")
        confirm = input("\n  Save this pattern? (y/n) [y]: ").strip().lower()
        if confirm in ("", "y", "yes"):
            res = memory.add_training(
                text=args.text, sql=sql, explanation=explain,
                chart_type=chart, lock=args.lock or False,
            )
            print(_green(f"  ✅ Pattern {res}: '{args.text[:60]}'"))
        else:
            print(_yellow("  Skipped."))
    except Exception as e:
        print(_red(f"❌ AI error: {e}"))


def cmd_ai_batch(args):
    """
    Train from a text file of questions (one per line).
    Requires ANTHROPIC_API_KEY or GEMINI_API_KEY.
    """
    if not args.file:
        print(_red("--file is required (text file with one question per line)"))
        return
    p = Path(args.file)
    if not p.exists():
        print(_red(f"File not found: {args.file}"))
        return

    questions = [q.strip() for q in p.read_text().splitlines() if q.strip() and not q.startswith("#")]
    print(f"  Found {len(questions)} questions")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print(_red("❌ No API key. Set ANTHROPIC_API_KEY or GEMINI_API_KEY in .env"))
        return

    from ai_engines import call_ai_sync
    added = updated = skipped = 0
    for i, q in enumerate(questions, 1):
        print(f"  [{i:3d}/{len(questions)}] {q[:60]}…", end=" ", flush=True)
        try:
            result = call_ai_sync(q, [])
            sql    = (result.get("sql") or "").strip().rstrip(";")
            if not sql:
                print(_yellow("(no SQL)"))
                skipped += 1
                continue
            res = memory.add_training(
                text=q, sql=sql,
                explanation=result.get("answer", "")[:100],
                chart_type=result.get("chart_type", "table"),
            )
            if res == "added":
                added   += 1
                print(_green("added"))
            else:
                updated += 1
                print(_yellow("updated"))
        except Exception as e:
            print(_red(f"error: {str(e)[:60]}"))
            skipped += 1

    print(_green(f"\n✅ Batch complete: {added} added, {updated} updated, {skipped} skipped"))
    print(f"   Total patterns: {len(memory.patterns)}")


def cmd_seed(args):
    seed_file = Path(__file__).parent / "learned_queries_seed.json"
    if not seed_file.exists():
        print(_yellow(f"⚠️  Seed file not found: {seed_file}"))
        print("   Create learned_queries_seed.json with your base patterns.")
        return
    try:
        added, updated = memory.import_patterns(seed_file)
        print(_green(f"✅ Seed imported: {added} added, {updated} updated"))
    except Exception as e:
        print(_red(f"❌ Seed import failed: {e}"))


# ─── CLI entry point ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="DataGrid Intelligence — Training CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command")

    # list
    p_list = sub.add_parser("list", help="List all learned patterns")
    p_list.add_argument("--filter", help="Filter by keyword")
    p_list.add_argument("--limit", type=int, default=50)

    # stats
    sub.add_parser("stats", help="Show training statistics")

    # add
    p_add = sub.add_parser("add", help="Add a training pattern")
    p_add.add_argument("--text",        help="Natural language question")
    p_add.add_argument("--sql",         help="DuckDB SQL")
    p_add.add_argument("--chart",       default="table", help="Chart type")
    p_add.add_argument("--explanation", default="", help="Short description")
    p_add.add_argument("--lock",        action="store_true", help="Lock pattern (count=200)")

    # remove
    p_rm = sub.add_parser("remove", help="Remove a pattern by text")
    p_rm.add_argument("--text", required=True)

    # test
    p_test = sub.add_parser("test", help="Test pattern recall for a query")
    p_test.add_argument("--text", required=True)

    # test-sql
    p_tsql = sub.add_parser("test-sql", help="Test SQL directly against DuckDB")
    p_tsql.add_argument("--sql",   required=True)
    p_tsql.add_argument("--files", nargs="*", help="Parquet/CSV files to load first")

    # import
    p_imp = sub.add_parser("import", help="Import patterns from JSON file")
    p_imp.add_argument("--file", required=True)

    # export
    p_exp = sub.add_parser("export", help="Export all patterns to JSON file")
    p_exp.add_argument("--file", default="learned_queries_export.json")

    # lock
    p_lock = sub.add_parser("lock", help="Lock a pattern (never pruned/overwritten)")
    p_lock.add_argument("--text", required=True)

    # fix
    p_fix = sub.add_parser("fix", help="Fix/update SQL for an existing pattern")
    p_fix.add_argument("--text", required=True)
    p_fix.add_argument("--sql",  required=True)

    # purge-auto
    sub.add_parser("purge-auto", help="Remove all auto-learned (non-trained) patterns")

    # ai-generate
    p_aig = sub.add_parser("ai-generate", help="Use AI to generate SQL for a query")
    p_aig.add_argument("--text", required=True)
    p_aig.add_argument("--lock", action="store_true")

    # ai-batch
    p_aib = sub.add_parser("ai-batch", help="Batch AI training from a text file")
    p_aib.add_argument("--file", required=True, help="Text file, one question per line")

    # seed
    sub.add_parser("seed", help="Import from learned_queries_seed.json")

    args = parser.parse_args()

    dispatch = {
        "list":       cmd_list,
        "stats":      cmd_stats,
        "add":        cmd_add,
        "remove":     cmd_remove,
        "test":       cmd_test,
        "test-sql":   cmd_test_sql,
        "import":     cmd_import,
        "export":     cmd_export,
        "lock":       cmd_lock,
        "fix":        cmd_fix,
        "purge-auto": cmd_purge_auto,
        "ai-generate": cmd_ai_generate,
        "ai-batch":   cmd_ai_batch,
        "seed":       cmd_seed,
    }

    if args.command not in dispatch:
        parser.print_help()
        return

    dispatch[args.command](args)


if __name__ == "__main__":
    main()