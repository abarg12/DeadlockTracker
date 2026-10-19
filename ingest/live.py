"""Keeps the app's optimized schema filled with a rolling week of sampled matches from the data lake.

    python -m ingest.live [--once]   # the app runs this automatically; use it to ingest without the app
"""

import argparse
import logging
import threading
import time
import tomllib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values

from ingest import lake
from ingest.load import ROOT, connect, read_secrets, run_sql_file

log = logging.getLogger("deadlock.ingest")
STOP = threading.Event()  # set on app shutdown; checked between units of work
LOCK_ID = 501  # advisory lock so two app instances never ingest at once
SCHEMA_VERSION = "deadlock-tracker v2"  # must match the COMMENT ON SCHEMA in sql/optimized.sql
DEFAULTS = {"sample_percent": 3.0, "keep_days": 7, "interval_minutes": 15}


def settings() -> dict:
    """DEFAULTS overridden by an optional [ingest] table in .streamlit/secrets.toml."""
    secrets = tomllib.loads((ROOT / ".streamlit" / "secrets.toml").read_text())
    return DEFAULTS | secrets.get("ingest", {})


def open_database():
    """Connects to the app's database, creating it first if it doesn't exist."""
    try:
        return connect()
    except psycopg2.OperationalError as err:
        if "does not exist" not in str(err):
            raise
    name = read_secrets()["database"]
    with connect("postgres").cursor() as cur:
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    log.info("created database %s", name)
    return connect()


def ensure_schema(conn) -> None:
    """Builds the optimized schema with indexes and views if it's missing or from an older version.
    The data is a sample of the data lake, so a rebuild just triggers a fresh backfill."""
    with conn.cursor() as cur:
        cur.execute("SELECT obj_description(to_regnamespace('optimized'), 'pg_namespace'), "
                    "to_regclass('optimized.hero_daily_stats')")
        version, has_views = cur.fetchone()
    if version != SCHEMA_VERSION:
        run_sql_file(conn, ROOT / "sql" / "optimized.sql")
        log.info("built the optimized schema (%s, was %s)", SCHEMA_VERSION, version or "missing")
        has_views = None
    run_sql_file(conn, ROOT / "sql" / "indexes.sql", "optimized")
    if not has_views:
        run_sql_file(conn, ROOT / "sql" / "views.sql", "optimized")


def refresh_references(cur) -> tuple[set[int], set[int]]:
    """Upserts heroes and items once a day; returns the known hero and item IDs."""
    cur.execute("SELECT references_refreshed_at IS NULL OR references_refreshed_at < now() - INTERVAL '1 day' "
                "FROM optimized.ingest_state")
    if cur.fetchone()[0]:
        heroes, tiers, items = lake.reference_data()
        execute_values(cur, """INSERT INTO optimized.hero VALUES %s ON CONFLICT (hero_id) DO UPDATE SET
            name = EXCLUDED.name, hero_type = EXCLUDED.hero_type, complexity = EXCLUDED.complexity""", heroes)
        execute_values(cur, """INSERT INTO optimized.item_tier VALUES %s ON CONFLICT (item_tier) DO UPDATE SET
            cost = EXCLUDED.cost""", tiers)
        execute_values(cur, """INSERT INTO optimized.item VALUES %s ON CONFLICT (item_id) DO UPDATE SET
            name = EXCLUDED.name, item_slot_type = EXCLUDED.item_slot_type, item_tier = EXCLUDED.item_tier""", items)
        cur.execute("UPDATE optimized.ingest_state SET references_refreshed_at = now()")
    cur.execute("SELECT hero_id FROM optimized.hero")
    hero_ids = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT item_id FROM optimized.item")
    return hero_ids, {r[0] for r in cur.fetchall()}


def insert_records(cur, records: list) -> int:
    """Inserts validated matches, skipping ones already loaded; returns how many were new."""
    if not records:
        return 0
    ids = [m[0] for m, _, _ in records]
    cur.execute("SELECT optimized.ensure_partitions(%s, %s)", (min(ids), max(ids)))
    new = {r[0] for r in execute_values(
        cur, "INSERT INTO optimized.match VALUES %s ON CONFLICT (match_id) DO NOTHING RETURNING match_id",
        [m for m, _, _ in records], fetch=True)}
    players = [p for m, ps, _ in records if m[0] in new for p in ps]
    items = [i for m, _, its in records if m[0] in new for i in its]
    execute_values(cur, "INSERT INTO optimized.player (account_id) VALUES %s ON CONFLICT DO NOTHING",
                   sorted({(p[1],) for p in players}))
    execute_values(cur, "INSERT INTO optimized.match_player VALUES %s", players, page_size=2000)
    execute_values(cur, "INSERT INTO optimized.match_player_item VALUES %s", items, page_size=5000)
    return len(new)


def backfill(conn, con, lake_manifest: dict, since: int, cfg: dict, known: tuple) -> tuple[int, int]:
    """Loads a sample of every match since `since` from the base files, committing chunk by chunk.
    Returns (matches added, oldest build time of the files read)."""
    chunks = lake.base_chunks(con, lake_manifest, since)
    built = {lake.file_url(lake_manifest, f): f["hi"] for f in lake_manifest["tables"]["match_player"]["files"]}
    log.info("backfilling the last %s days from %d data lake chunks", cfg["keep_days"], len(chunks))
    with conn.cursor() as cur:
        cur.execute("UPDATE optimized.ingest_state SET backfill_done = 0, backfill_total = %s", (len(chunks),))
    conn.commit()
    dropped, added, refreshed_at = Counter(), 0, time.monotonic()

    def read(chunk):
        url, first_row, rows, _ = chunk
        return lake.read_rows(con.cursor(), url, since, first_row, rows, cfg["sample_percent"])

    with ThreadPoolExecutor(max_workers=4) as pool:
        # newest first, so the default "last day" views fill in soonest
        futures = [pool.submit(read, c) for c in reversed(chunks)]
        for done, future in enumerate(as_completed(futures), start=1):
            if STOP.is_set():
                for f in futures:
                    f.cancel()
                break
            with conn.cursor() as cur:
                added += insert_records(cur, list(lake.match_records(future.result(), *known, dropped)))
                # refresh the views every 30 s so the hero and item pages fill in too
                if time.monotonic() - refreshed_at > 30 or done == len(chunks):
                    cur.execute("SELECT optimized.refresh_stats()")
                    refreshed_at = time.monotonic()
                cur.execute("UPDATE optimized.ingest_state SET backfill_done = %s, data_version = data_version + 1",
                            (done,))
            conn.commit()
            if done % 10 == 0 or done == len(chunks):
                log.info("backfill: %d/%d chunks, %d matches added", done, len(chunks), added)
    return added, min((built[c[0]] for c in chunks), default=int(time.time()))


def run_once() -> None:
    """Brings the database up to date with the data lake, then expires data older than keep_days."""
    cfg = settings()
    conn = open_database()
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,))
        if not cur.fetchone()[0]:
            log.info("another process is ingesting; skipping this run")
            return
    ensure_schema(conn)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            known = refresh_references(cur)
            cur.execute("SELECT last_delta_hi FROM optimized.ingest_state")
            last_hi = cur.fetchone()[0]
        conn.commit()

        con = lake.connect()
        lake_manifest = lake.manifest()
        files = lake_manifest["tables"]["match_player"]["files"]
        since = int(time.time() - cfg["keep_days"] * 86400)
        deltas = sorted((f for f in files if f["kind"] == "delta"), key=lambda f: f["lo"])
        added = 0

        # hourly delta files hold each hour's new rows; if ours are older than the oldest one kept, backfill
        if last_hi is None or not deltas or last_hi < deltas[0]["lo"]:
            # files contain rows up to their build time; deltas after the oldest build fill the rest
            backfilled, last_hi = backfill(conn, con, lake_manifest, since, cfg, known)
            added += backfilled
            if STOP.is_set():
                return

        for f in deltas:
            if STOP.is_set():
                return
            if f["hi"] <= last_hi:
                continue
            rows = lake.read_rows(con, lake.file_url(lake_manifest, f), since, sample_percent=cfg["sample_percent"])
            with conn.cursor() as cur:
                added += insert_records(cur, list(lake.match_records(rows, *known, Counter())))
                cur.execute("UPDATE optimized.ingest_state SET last_delta_hi = %s, data_version = data_version + 1",
                            (f["hi"],))
            conn.commit()
            last_hi = f["hi"]

        with conn.cursor() as cur:
            cur.execute("SELECT optimized.drop_old_partitions(make_interval(days => %s))", (int(cfg["keep_days"]),))
            dropped = cur.fetchone()[0]
            cur.execute("UPDATE optimized.ingest_state SET last_delta_hi = %s, last_run_at = now()", (last_hi,))
            if added or dropped:
                cur.execute("SELECT optimized.refresh_stats()")
                cur.execute("UPDATE optimized.ingest_state SET data_version = data_version + 1")
        conn.commit()
        log.info("ingest done: %d matches added, %d old partitions dropped", added, dropped)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true", help="ingest once and exit instead of every interval")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    while True:
        run_once()
        if args.once:
            break
        time.sleep(settings()["interval_minutes"] * 60)


if __name__ == "__main__":
    main()
