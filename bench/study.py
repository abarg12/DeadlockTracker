"""Query design study: how much speed comes from how a query is written, and when an index helps.

    python -m bench.study --database deadlock_bench --size 50000 --repeats 5

Three experiments on the baseline schema, written to results/study-<timestamp>/:

  1. rewrites     each query in sql/queries/naive/ against its well-written version, with and
                  without sql/indexes.sql: an index only helps a query written so it can use it
  2. selectivity  study/recent_matches over windows from 1 hour to 7 days, with and without
                  indexes: where an index stops beating a sequential scan
  3. search       name search by substring (the app's) and by prefix, under no name index, a b-tree
                  on lower(name) and a trigram index: the index type has to fit the predicate

Player names come from the Steam name snapshot the app caches in data/lake_cache/; without it
the search experiment is skipped.
"""

import argparse
import csv
import datetime as dt
import io
import json
import statistics
from pathlib import Path

from bench.run import pick_params, prepare, result_hash, slowest_node
from ingest.load import ROOT, connect, load, run_sql_file, stage

SQL = ROOT / "sql"
TABLES = "hero, item_tier, item, player, match, match_player, match_player_item"

# pair name -> (naive query, well-written query), both under sql/queries/
REWRITES = {
    "recent_matches": ("naive/recent_matches", "study/recent_matches"),
    "hero_win_rates": ("naive/hero_win_rates", "hero_win_rates"),
    "player_match_history": ("naive/player_match_history", "player_match_history"),
}
SEARCH_QUERIES = {"contains": "player_search", "prefix": "study/player_search_prefix"}
SEARCH_INDEXES = {
    "no name index": [],
    "b-tree on lower(name)": ["CREATE INDEX player_name_lower_idx ON player (lower(account_name) text_pattern_ops)"],
    "trigram": ["CREATE INDEX player_name_trgm_idx ON player USING gin (account_name public.gin_trgm_ops)"],
}


def indexes_used(plan: dict) -> list[str]:
    """Names of the indexes a plan reads, in plan order."""
    found = []

    def walk(node):
        if "Index Name" in node and node["Index Name"] not in found:
            found.append(node["Index Name"])
        for child in node.get("Plans", []):
            walk(child)

    walk(plan)
    return found


class Timer:
    """Runs queries with EXPLAIN ANALYZE, logging every run to latency.csv and the plans to plans/."""

    def __init__(self, cur, out: Path, repeats: int):
        self.cur, self.out, self.repeats = cur, out, repeats
        self.file = open(out / "latency.csv", "w", newline="")
        self.csv = csv.writer(self.file)
        self.csv.writerow(["experiment", "query", "variant", "config", "param", "run", "execution_ms",
                           "planning_ms", "shared_hit_blocks", "shared_read_blocks", "rows", "indexes_used",
                           "slowest_node", "slowest_node_ms"])

    def time(self, experiment: str, query: str, variant: str, config: str, param, sql: str, params: dict) -> dict:
        """Warm-up run (its rows are fingerprinted), then `repeats` measured runs; returns a summary."""
        self.cur.execute(sql, params)
        fingerprint = result_hash(self.cur.fetchall())
        plans = []
        for run in range(1, self.repeats + 1):
            self.cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params)
            plan = self.cur.fetchone()[0][0]
            plans.append(plan)
            root = plan["Plan"]
            node, node_ms = slowest_node(root)
            self.csv.writerow([experiment, query, variant, config, param, run, plan["Execution Time"],
                               plan["Planning Time"], root.get("Shared Hit Blocks"), root.get("Shared Read Blocks"),
                               root.get("Actual Rows"), " ".join(indexes_used(root)) or "none", node,
                               round(node_ms, 3)])
        self.file.flush()
        slug = "_".join(str(p).replace("/", "-").replace(" ", "-") for p in (experiment, query, variant, config, param))
        (self.out / "plans" / f"{slug}.json").write_text(json.dumps(plans, indent=1))
        ms = statistics.median(p["Execution Time"] for p in plans)
        used = " ".join(indexes_used(plans[0]["Plan"])) or "none"
        print(f"  {query:<22} {variant:<10} {config:<22} {str(param):>6} {ms:10.2f} ms   index: {used}")
        return {"experiment": experiment, "query": query, "variant": variant, "config": config, "param": param,
                "median_ms": round(ms, 3), "indexes_used": used, "hash": fingerprint}


def set_indexes(conn, cur, on: bool) -> None:
    run_sql_file(conn, SQL / ("indexes.sql" if on else "drop_indexes.sql"), "baseline")
    cur.execute("DROP INDEX IF EXISTS baseline.player_name_lower_idx")
    cur.execute(f"ANALYZE {TABLES}")


def load_names(cur) -> int:
    """Fills baseline.player.account_name from the cached Steam name snapshot; returns names set."""
    snapshots = sorted((ROOT / "data" / "lake_cache").glob("steam_names-*.parquet"))
    if not snapshots:
        return 0
    import duckdb
    import pandas as pd

    cur.execute("SELECT account_id FROM player")
    ours = pd.DataFrame({"account_id": [r[0] for r in cur.fetchall()]})
    con = duckdb.connect()
    con.register("ours", ours)
    names = con.execute(f"SELECT n.account_id, n.personaname FROM read_parquet('{snapshots[-1]}') n "
                        "JOIN ours USING (account_id)").fetchall()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for account_id, name in names:
        if name:
            writer.writerow([account_id, name.replace("\x00", "")[:255]])  # Postgres text can't hold NUL
    buffer.seek(0)
    cur.execute("CREATE TEMP TABLE names (account_id BIGINT, name TEXT)")
    cur.copy_expert("COPY names FROM STDIN WITH (FORMAT csv)", buffer)
    cur.execute("UPDATE player p SET account_name = n.name FROM names n WHERE p.account_id = n.account_id")
    count = cur.rowcount
    cur.execute("DROP TABLE names")
    return count


def like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def speedup(slow: float, fast: float) -> str:
    return f"{slow / fast:,.1f}×" if fast > 0 else "–"


def write_summary(out: Path, results: list[dict], meta: dict) -> None:
    """summary.csv with every median, and summary.md with the tables for the write-up."""
    with open(out / "summary.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[k for k in results[0] if k != "hash"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    get = lambda **kw: next(r for r in results if all(r[k] == v for k, v in kw.items()))
    lines = [f"# Query design study ({meta['size']:,} matches, median of {meta['repeats']} runs)", ""]

    lines += ["## 1. Rewrites: naive vs well-written, with and without indexes", "",
              "| query | naive, no index | naive + indexes | rewritten, no index | rewritten + indexes "
              "| total speedup | rows identical |",
              "|---|---|---|---|---|---|---|"]
    for name in REWRITES:
        cells = {(v, c): get(experiment="rewrites", query=name, variant=v, config=c)
                 for v in ("naive", "rewritten") for c in ("no indexes", "indexes")}
        fmt = lambda r: f"{r['median_ms']:.2f} ms ({r['indexes_used']})"
        same = len({r["hash"] for r in cells.values()}) == 1
        lines.append(f"| {name} | {fmt(cells['naive', 'no indexes'])} | {fmt(cells['naive', 'indexes'])} "
                     f"| {fmt(cells['rewritten', 'no indexes'])} | {fmt(cells['rewritten', 'indexes'])} "
                     f"| {speedup(cells['naive', 'no indexes']['median_ms'], cells['rewritten', 'indexes']['median_ms'])} "
                     f"| {'yes' if same else '**NO**'} |")

    lines += ["", "## 2. Selectivity: recent_matches by window length", "",
              "| window | share of matches | rewritten, no index | rewritten + indexes | index speedup "
              "| naive + indexes | index used (rewritten) |",
              "|---|---|---|---|---|---|---|"]
    for hours, share in meta["windows"]:
        no = get(experiment="selectivity", variant="rewritten", config="no indexes", param=hours)
        yes = get(experiment="selectivity", variant="rewritten", config="indexes", param=hours)
        naive = get(experiment="selectivity", variant="naive", config="indexes", param=hours)
        lines.append(f"| {hours} h | {share:.1%} | {no['median_ms']:.2f} ms | {yes['median_ms']:.2f} ms "
                     f"| {speedup(no['median_ms'], yes['median_ms'])} | {naive['median_ms']:.2f} ms "
                     f"| {yes['indexes_used']} |")

    if any(r["experiment"] == "search" for r in results):
        lines += ["", f"## 3. Name search for \"{meta['search_text']}\"", "",
                  "| predicate | " + " | ".join(SEARCH_INDEXES) + " |",
                  "|---|" + "---|" * len(SEARCH_INDEXES)]
        for variant in SEARCH_QUERIES:
            cells = [get(experiment="search", variant=variant, config=c) for c in SEARCH_INDEXES]
            lines.append(f"| {variant} | " + " | ".join(f"{r['median_ms']:.2f} ms ({r['indexes_used']})"
                                                         for r in cells) + " |")
    (out / "summary.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database", required=True, help="separate database; its baseline schema is rebuilt")
    parser.add_argument("--size", type=int, default=50000, help="matches to load")
    parser.add_argument("--repeats", type=int, default=5, help="measured runs per query")
    parser.add_argument("--window-days", type=float, default=3, help="date window for hero_win_rates")
    parser.add_argument("--hours", type=int, default=1, help="window for recent_matches in the rewrites experiment")
    parser.add_argument("--sweep", default="1,8,16,24,48,72,96,120,168", help="windows in hours for the selectivity sweep")
    parser.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--out", type=Path, default=ROOT / "results")
    args = parser.parse_args()

    out = args.out / ("study-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
    (out / "plans").mkdir(parents=True)
    conn = connect(args.database)
    cur = conn.cursor()
    cur.execute("SET jit = off")

    print("rebuilding the baseline schema and loading matches...")
    run_sql_file(conn, SQL / "baseline.sql")
    staged = stage(conn, args.raw)
    if args.size > staged:
        raise SystemExit(f"--size {args.size} exceeds the {staged} downloaded matches")
    load(conn, "baseline", args.size)
    cur.execute("SET search_path TO baseline")
    named = load_names(cur)
    print(f"loaded {args.size} matches, {named} player names")
    cur.execute(f"VACUUM (ANALYZE) {TABLES}")

    params = pick_params(cur, args.window_days)
    cur.execute("SELECT max(start_time) FROM match")
    params |= {"as_of": cur.fetchone()[0], "hours": args.hours}
    meta = {"size": args.size, "repeats": args.repeats, "named_players": named}
    timer = Timer(cur, out, args.repeats)
    results = []

    print("\n1. rewrites")
    for on in (False, True):
        set_indexes(conn, cur, on)
        config = "indexes" if on else "no indexes"
        for name, (naive, rewritten) in REWRITES.items():
            for variant, query in (("naive", naive), ("rewritten", rewritten)):
                param = args.hours if name == "recent_matches" else ""
                results.append(timer.time("rewrites", name, variant, config, param, prepare(query), params))

    print("\n2. selectivity")
    hours_list = [int(h) for h in args.sweep.split(",")]
    meta["windows"] = []
    for hours in hours_list:
        cur.execute("SELECT avg((start_time >= %s - make_interval(hours => %s))::INT) FROM match",
                    (params["as_of"], hours))
        meta["windows"].append((hours, float(cur.fetchone()[0])))
    for on in (False, True):
        set_indexes(conn, cur, on)
        config = "indexes" if on else "no indexes"
        for hours in hours_list:
            for variant, query in zip(("naive", "rewritten"), REWRITES["recent_matches"]):
                results.append(timer.time("selectivity", "recent_matches", variant, config, hours,
                                          prepare(query), params | {"hours": hours}))

    if named:
        # the most active player's full name, as if someone searched for them
        cur.execute("""SELECT p.account_name FROM player p JOIN match_player USING (account_id)
                       WHERE length(p.account_name) >= 5 GROUP BY p.account_id, p.account_name
                       ORDER BY COUNT(*) DESC, p.account_id LIMIT 1""")
        text = cur.fetchone()[0]
        meta["search_text"] = text
        search = params | {"text": text, "pattern": f"%{like_escape(text)}%", "prefix": f"{like_escape(text)}%"}
        print(f"\n3. search for {text!r}")
        set_indexes(conn, cur, True)  # the other indexes stay; only the name index varies
        for config, statements in SEARCH_INDEXES.items():
            cur.execute("DROP INDEX IF EXISTS player_name_trgm_idx, player_name_lower_idx")
            for statement in statements:
                cur.execute(statement)
            cur.execute("ANALYZE player")
            for variant, query in SEARCH_QUERIES.items():
                results.append(timer.time("search", query, variant, config, "", prepare(query), search))
    else:
        print("\n3. search skipped: no Steam name snapshot in data/lake_cache/ (run the app once to fetch it)")

    # same rows from both versions of a query, under every index config
    mismatches = []
    for experiment, key in (("rewrites", "query"), ("selectivity", "param"), ("search", "variant")):
        groups = {}
        for r in results:
            if r["experiment"] == experiment:
                groups.setdefault(r[key], set()).add(r["hash"])
        mismatches += [f"{experiment}: {k}" for k, hashes in groups.items() if len(hashes) > 1]
    meta["mismatches"] = mismatches
    meta["params"] = {k: str(v) for k, v in params.items()}
    print(f"\ncorrectness: {'every version returned identical rows' if not mismatches else mismatches}")

    write_summary(out, results, meta)
    (out / "metadata.json").write_text(json.dumps(meta, indent=1))
    cur.execute("DROP SCHEMA staging CASCADE")
    timer.file.close()
    print(f"results written to {out}/ (start with summary.md)")


if __name__ == "__main__":
    main()
