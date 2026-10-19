"""Shared access to the Deadlock API's public data lake (hourly parquet snapshots of match_player)."""

import datetime as dt
import http.client
import json
import time
import urllib.error
import urllib.request
from collections import Counter

import duckdb

API = "https://api.deadlock-api.com"
LAKE = "https://data.deadlock-api.com"
TEAMS = {"Team0": 0, "Team1": 1}
GAME_MODE, PLAYERS = "Normal", 12

MATCH_COLUMNS = ["match_id", "start_time", "duration_s", "game_mode", "match_mode", "winning_team", "average_badge"]
PLAYER_COLUMNS = ["match_id", "account_id", "hero_id", "team", "assigned_lane", "kills", "deaths", "assists",
                  "net_worth", "last_hits", "denies", "hero_level"]
ITEM_COLUMNS = ["match_id", "account_id", "item_id", "game_time_s", "sold_time_s"]


def get(url: str, retries: int = 5):
    headers = {"User-Agent": "DeadlockTracker (ECE501C course project)"}
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=300) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as err:
            # retry only rate limits (429) and server errors
            if err.code != 429 and err.code < 500:
                raise
            reason = f"HTTP {err.code}"
        except (OSError, http.client.HTTPException, json.JSONDecodeError) as err:
            # dropped or corrupted connections, including SSL errors mid-download
            reason = type(err).__name__
        wait = 15 * (attempt + 1)
        print(f"  request failed ({reason}), retrying in {wait}s", flush=True)
        time.sleep(wait)
    raise RuntimeError(f"giving up on {url}")


def reference_data() -> tuple[list, list, list]:
    """(hero, item_tier, item) rows from the assets API."""
    heroes = [(h["id"], h["name"], h.get("hero_type"), h.get("complexity")) for h in get(f"{API}/v1/assets/heroes")]
    # shop items only; abilities and weapons also appear in item lists
    items = [i for i in get(f"{API}/v1/assets/items") if i.get("type") == "upgrade" and i.get("shopable")]
    tier_costs: dict[int, set[int]] = {}
    for i in items:
        tier_costs.setdefault(i["item_tier"], set()).add(i["cost"])
    # item_tier -> cost must hold for the item_tier table
    mixed = {tier: costs for tier, costs in tier_costs.items() if len(costs) > 1}
    if mixed:
        raise RuntimeError(f"tiers with more than one cost, item_tier table no longer valid: {mixed}")
    tiers = sorted((tier, costs.pop()) for tier, costs in tier_costs.items())
    return heroes, tiers, [(i["id"], i["name"], i.get("item_slot_type"), i["item_tier"]) for i in items]


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; SET http_retries = 8; SET http_retry_wait_ms = 2000")
    return con


def manifest() -> dict:
    return get(f"{LAKE}/v1/manifest.json")


def file_url(lake_manifest: dict, f: dict) -> str:
    return f"{lake_manifest['public_url']}/{f['key']}"


def _row_groups(con, url: str, since: int) -> list[tuple[str, int, int, int]]:
    """Row groups of one file holding start times >= since: (url, first row, rows, earliest start)."""
    groups = con.execute(f"""
        SELECT row_group_id, any_value(row_group_num_rows),
               epoch(min(stats_min_value::TIMESTAMPTZ))::BIGINT, epoch(max(stats_max_value::TIMESTAMPTZ))::BIGINT
        FROM parquet_metadata('{url}') WHERE path_in_schema = 'start_time'
        GROUP BY 1 ORDER BY 1""").fetchall()
    chunks, first_row = [], 0
    for _, rows, earliest, latest in groups:
        if latest >= since:
            chunks.append((url, first_row, rows, earliest))
        first_row += rows
    return chunks


def base_chunks(con, lake_manifest: dict, since: int) -> list[tuple[str, int, int, int]]:
    """Row groups of the base and residual files with start times >= since, sorted by earliest start."""
    files = lake_manifest["tables"]["match_player"]["files"]
    chunks, stale = [], 0
    # base files are split by match ID, so walk from the newest until two in a row predate the window
    for f in sorted((f for f in files if f["kind"] == "base"), key=lambda f: -f["partition"]):
        found = _row_groups(con, file_url(lake_manifest, f), since)
        chunks += found
        stale = 0 if found else stale + 1
        if stale == 2:
            break
    # residual files hold rows not yet merged into a base file
    for f in files:
        if f["kind"] == "residual" and f["hi"] >= since:
            chunks += _row_groups(con, file_url(lake_manifest, f), since)
    return sorted(chunks, key=lambda c: c[3])


def read_rows(con, url: str, since: int, first_row: int | None = None, rows: int | None = None,
              sample_percent: float | None = None) -> list[tuple]:
    """Player rows of complete, scored public matches started at or after since, ordered by match.
    Optionally limited to one row group and to a deterministic sample of matches."""
    where = [f"start_time >= to_timestamp({since})", f"game_mode = '{GAME_MODE}'",
             "match_mode IN ('Ranked', 'Unranked')", "winning_team IN ('Team0', 'Team1')", "not_scored IS NOT TRUE"]
    if first_row is not None:
        where.append(f"file_row_number >= {first_row} AND file_row_number < {first_row + rows}")
    if sample_percent is not None:
        where.append(f"match_id % 10000 < {int(sample_percent * 100)}")
    query = f"""
        SELECT match_id, epoch(start_time)::BIGINT, duration_s, game_mode, match_mode, winning_team, average_badge,
               account_id, hero_id, team, assigned_lane, kills, deaths, assists, net_worth, last_hits, denies,
               player_level, "items.item_id", "items.game_time_s", "items.sold_time_s"
        FROM read_parquet('{url}', file_row_number = true)
        WHERE {' AND '.join(where)}
        QUALIFY count(*) OVER (PARTITION BY match_id) = {PLAYERS}
        ORDER BY match_id"""
    for attempt in range(5):
        try:
            return con.execute(query).fetchall()
        except duckdb.Error as err:
            wait = 15 * (attempt + 1)
            print(f"  lake read failed ({type(err).__name__}), retrying in {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"giving up on {url}")


def match_records(rows: list[tuple], hero_ids: set[int], item_ids: set[int], dropped: Counter):
    """Validates read_rows output; yields (match row, player rows, item rows) in schema column order."""
    by_match: dict[int, list] = {}
    for row in rows:
        by_match.setdefault(row[0], []).append(row)

    for match_id, match_rows in by_match.items():
        if any(r[8] not in hero_ids for r in match_rows):
            dropped["match with unknown hero"] += 1
            continue
        accounts = {}
        for r in match_rows:
            # skip bots/anonymous players and duplicate accounts
            if not r[7] or r[7] in accounts or r[9] not in TEAMS:
                dropped["player without valid account or team"] += 1
                continue
            accounts[r[7]] = r
        if not accounts:
            dropped["match with no valid players"] += 1
            continue

        m = match_rows[0]
        start = dt.datetime.fromtimestamp(m[1], dt.timezone.utc)
        match = (match_id, start, m[2], m[3], m[4], TEAMS[m[5]], m[6] or None)
        players, items = [], []
        for account_id, r in accounts.items():
            players.append((match_id, account_id, r[8], TEAMS[r[9]], r[10], r[11], r[12], r[13], r[14], r[15],
                            r[16], r[17]))
            bought = set()
            for item_id, bought_at, sold in zip(r[18] or [], r[19] or [], r[20] or []):
                sold = sold or None  # 0 means never sold
                if item_id not in item_ids:
                    continue  # not a shop item
                if (item_id, bought_at) in bought or (sold is not None and sold < bought_at):
                    dropped["malformed item purchase"] += 1
                    continue
                bought.add((item_id, bought_at))
                items.append((match_id, account_id, item_id, bought_at, sold))
        yield match, players, items
