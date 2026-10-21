"""Ablation study: times each query under baseline, +indexes, partitioned, +both and full (views).

    python -m bench.run --sizes 5000,10000,25000 --repeats 5   # results go to results/<timestamp>/
"""

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import statistics
import subprocess
import time
from pathlib import Path

from ingest.load import ROOT, connect, load, query_sql, run_sql_file, stage

SQL = ROOT / "sql"
QUERIES = SQL / "queries"

# (name, schema, indexes, views)
CONFIGS = [
    ("baseline", "baseline", False, False),
    ("baseline+indexes", "baseline", True, False),
    ("partitioned", "optimized", False, False),
    ("partitioned+indexes", "optimized", True, False),
    ("full", "optimized", True, True),
]
# materialized view query -> the raw query it must agree with
MV_QUERIES = {"hero_win_rates_mv": "hero_win_rates", "item_win_rates_mv": "item_win_rates"}


def load_queries() -> dict[str, str]:
    """Reads sql/queries/*.sql, converting :name parameters to psycopg2's %(name)s."""
    queries = {}
    for path in sorted(QUERIES.glob("*.sql")):
        sql = query_sql(path.stem).replace("%", "%%")
        # skip :: casts and times like 12:30
        queries[path.stem] = re.sub(r"(?<![:\w]):(\w+)", r"%(\1)s", sql)
    return queries


def pick_params(cur, window_days: float) -> dict:
    """Chooses query parameters from the loaded data, identical for every config."""
    cur.execute("SET search_path TO baseline")
    cur.execute("SELECT max(start_time) FROM match")
    newest = cur.fetchone()[0]
    # UTC midnight, so the raw and materialized view queries cover the same days
    since = (newest - dt.timedelta(days=window_days)).astimezone(dt.timezone.utc)
    since = since.replace(hour=0, minute=0, second=0, microsecond=0)
    # same matches in both schemas, so one bound serves every config
    cur.execute("SELECT first_match_id(%s)", (since,))
    min_match_id = cur.fetchone()[0]
    cur.execute("SELECT match_mode FROM match GROUP BY 1 ORDER BY COUNT(*) DESC, 1 LIMIT 1")
    match_mode = cur.fetchone()[0]
    # most active player: the most rows for the history query
    cur.execute("SELECT account_id FROM match_player GROUP BY 1 ORDER BY COUNT(*) DESC, 1 LIMIT 1")
    account_id = cur.fetchone()[0]
    return {"since": since, "min_match_id": min_match_id, "match_mode": match_mode, "account_id": account_id}


def result_hash(rows) -> str:
    """Order-insensitive fingerprint of a result set."""
    lines = sorted("|".join("" if v is None else str(v) for v in row) for row in rows)
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]


def slowest_node(plan: dict) -> tuple[str, float]:
    """Plan node with the most exclusive time (approximate under parallel workers)."""
    best = ("", -1.0)

    def walk(node):
        nonlocal best
        total = node.get("Actual Total Time", 0) * node.get("Actual Loops", 1)
        children = node.get("Plans", [])
        own = total - sum(c.get("Actual Total Time", 0) * c.get("Actual Loops", 1) for c in children)
        label = node["Node Type"] + (f" on {node['Relation Name']}" if "Relation Name" in node else "")
        if own > best[1]:
            best = (label, own)
        for child in children:
            walk(child)

    walk(plan)
    return best


def schema_size(cur, schema: str) -> int:
    cur.execute("""
        SELECT COALESCE(sum(pg_total_relation_size(c.oid)), 0)
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relkind IN ('r', 'm')
    """, (schema,))
    return cur.fetchone()[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sizes", default="5000,10000,25000", help="comma separated match counts")
    parser.add_argument("--repeats", type=int, default=5, help="measured runs per query")
    parser.add_argument("--window-days", type=float, default=3, help="date window for the windowed queries")
    parser.add_argument("--queries", help="comma separated subset of sql/queries (default: all)")
    parser.add_argument("--work-mem", help="work_mem for every config, e.g. 64MB (default: server setting)")
    parser.add_argument("--partitionwise", action="store_true",
                        help="turn on enable_partitionwise_join and _aggregate for every config")
    parser.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--out", type=Path, default=ROOT / "results")
    parser.add_argument("--database", required=True,
                        help="separate database to benchmark in; its baseline and optimized schemas are rebuilt")
    args = parser.parse_args()

    sizes = sorted(int(s) for s in args.sizes.split(","))
    queries = load_queries()
    if args.queries:
        queries = {name: queries[name] for name in args.queries.split(",")}
    out = args.out / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    (out / "plans").mkdir(parents=True)

    conn = connect(args.database)
    cur = conn.cursor()
    settings = {"jit": "off"}
    if args.work_mem:
        settings["work_mem"] = f"'{args.work_mem}'"
    if args.partitionwise:
        settings |= {"enable_partitionwise_join": "on", "enable_partitionwise_aggregate": "on"}
    for name, value in settings.items():
        cur.execute(f"SET {name} = {value}")

    print("rebuilding schemas and staging the downloaded matches...")
    run_sql_file(conn, SQL / "baseline.sql")
    run_sql_file(conn, SQL / "optimized.sql")
    staged = stage(conn, args.raw)
    if sizes[-1] > staged:
        raise SystemExit(f"largest size {sizes[-1]} exceeds the {staged} downloaded matches")

    metadata = {"sizes": sizes, "repeats": args.repeats, "window_days": args.window_days,
                "settings": settings, "staged_matches": staged, "params": {}}
    cur.execute("SELECT version()")
    metadata["postgres"] = cur.fetchone()[0]
    cur.execute("SELECT name, setting, unit FROM pg_settings WHERE name IN "
                "('work_mem', 'shared_buffers', 'max_parallel_workers_per_gather', 'jit', "
                "'enable_partitionwise_join', 'enable_partitionwise_aggregate')")
    metadata["server_settings"] = {name: f"{value}{unit or ''}" for name, value, unit in cur.fetchall()}
    try:
        git = lambda *cmd: subprocess.run(["git", *cmd], cwd=ROOT, capture_output=True, text=True,
                                          check=True).stdout.strip()
        metadata["git_commit"] = git("rev-parse", "HEAD")
        # uncommitted changes mean the commit alone doesn't reproduce the run
        metadata["git_dirty"] = bool(git("status", "--porcelain", "sql", "bench", "ingest"))
    except (OSError, subprocess.CalledProcessError):
        metadata["git_commit"] = metadata["git_dirty"] = None

    latency_f = open(out / "latency.csv", "w", newline="")
    latency = csv.writer(latency_f)
    latency.writerow(["size", "config", "query", "run", "execution_ms", "planning_ms", "shared_hit_blocks",
                      "shared_read_blocks", "temp_read_blocks", "temp_written_blocks", "rows",
                      "slowest_node", "slowest_node_ms"])
    setup_f = open(out / "setup.csv", "w", newline="")
    setup = csv.writer(setup_f)
    setup.writerow(["size", "config", "step", "seconds", "schema_bytes"])
    hashes: dict[tuple[int, str, str], str] = {}

    for size in sizes:
        print(f"\n=== {size} matches ===")
        for schema in ("baseline", "optimized"):
            run_sql_file(conn, SQL / "drop_indexes.sql", schema)
            cur.execute(f"DROP MATERIALIZED VIEW IF EXISTS {schema}.hero_daily_stats, {schema}.item_daily_stats")
            seconds = load(conn, schema, size)
            cur.execute(f"VACUUM (ANALYZE) {schema}.hero, {schema}.item_tier, {schema}.item, {schema}.player, "
                        f"{schema}.match, {schema}.match_player, {schema}.match_player_item")
            setup.writerow([size, schema, "load", round(seconds, 3), schema_size(cur, schema)])
            print(f"loaded {schema} in {seconds:.1f}s")

        params = pick_params(cur, args.window_days)
        metadata["params"][size] = {k: str(v) for k, v in params.items()}

        for config, schema, indexes, views in CONFIGS:
            started = time.perf_counter()
            if indexes:
                run_sql_file(conn, SQL / "indexes.sql", schema)
                cur.execute(f"ANALYZE {schema}.match, {schema}.match_player, {schema}.match_player_item")
            else:
                run_sql_file(conn, SQL / "drop_indexes.sql", schema)
            if views:
                run_sql_file(conn, SQL / "views.sql", schema)
                cur.execute(f"ANALYZE {schema}.hero_daily_stats, {schema}.item_daily_stats")
            step = "views" if views else "indexes" if indexes else "drop_indexes"
            setup.writerow([size, config, step, round(time.perf_counter() - started, 3), schema_size(cur, schema)])
            cur.execute(f"SET search_path TO {schema}")

            to_run = [q for q in queries if (q in MV_QUERIES) == views]
            for name in to_run:
                sql = queries[name]
                cur.execute(sql, params)  # warm-up, and the result for the correctness check
                hashes[(size, config, name)] = result_hash(cur.fetchall())
                runs = []
                for run in range(1, args.repeats + 1):
                    cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params)
                    plan = cur.fetchone()[0][0]
                    runs.append(plan)
                    root = plan["Plan"]
                    node, node_ms = slowest_node(root)
                    latency.writerow([size, config, name, run, plan["Execution Time"], plan["Planning Time"],
                                      root.get("Shared Hit Blocks"), root.get("Shared Read Blocks"),
                                      root.get("Temp Read Blocks"), root.get("Temp Written Blocks"),
                                      root.get("Actual Rows"), node, round(node_ms, 3)])
                (out / "plans" / f"{size}_{config}_{name}.json").write_text(json.dumps(runs, indent=1))
                median = statistics.median(p["Execution Time"] for p in runs)
                print(f"  {config:<20} {name:<24} {median:10.2f} ms")
            latency_f.flush()
            setup_f.flush()

    # every config must return the same rows, and each view query must match its raw one
    with open(out / "correctness.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["size", "query", "compared_configs", "identical"])
        failures = 0
        for size in sizes:
            for name in queries:
                if name in MV_QUERIES:
                    pair = [hashes.get((size, "full", name)), hashes.get((size, "partitioned+indexes", MV_QUERIES[name]))]
                    label = f"full vs {MV_QUERIES[name]} (partitioned+indexes)"
                else:
                    pair = [h for (s, c, q), h in hashes.items() if s == size and q == name]
                    label = "all non-view configs"
                if None in pair:
                    continue
                same = len(set(pair)) == 1
                failures += not same
                writer.writerow([size, name, label, same])
    print(f"\ncorrectness: {'all configurations agree' if not failures else f'{failures} MISMATCHES, see correctness.csv'}")

    with conn.cursor() as c:
        c.execute("DROP SCHEMA staging CASCADE")
    (out / "metadata.json").write_text(json.dumps(metadata, indent=1))
    latency_f.close()
    setup_f.close()
    print(f"results written to {out}/")


if __name__ == "__main__":
    main()
