"""Database helpers, and the benchmark loader for ingest.fetch CSVs (N matches always picks the same N)."""

import gzip
import time
import tomllib
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent.parent
TABLES = ["hero", "item_tier", "item", "match", "match_player", "match_player_item"]

STAGING_DDL = """
DROP SCHEMA IF EXISTS staging CASCADE;
CREATE SCHEMA staging;
CREATE UNLOGGED TABLE staging.hero (hero_id INT, name TEXT, hero_type TEXT, complexity INT);
CREATE UNLOGGED TABLE staging.item_tier (item_tier INT, cost INT);
CREATE UNLOGGED TABLE staging.item (item_id BIGINT, name TEXT, item_slot_type TEXT, item_tier INT);
CREATE UNLOGGED TABLE staging.match (
    match_id BIGINT, start_time TIMESTAMPTZ, duration_s INT, game_mode TEXT, match_mode TEXT,
    winning_team SMALLINT, average_badge INT);
CREATE UNLOGGED TABLE staging.match_player (
    match_id BIGINT, account_id BIGINT, hero_id INT, team SMALLINT, assigned_lane INT, kills INT,
    deaths INT, assists INT, net_worth INT, last_hits INT, denies INT, hero_level INT);
CREATE UNLOGGED TABLE staging.match_player_item (
    match_id BIGINT, account_id BIGINT, item_id BIGINT, game_time_s INT, sold_time_s INT);
"""


def read_secrets() -> dict:
    """The app's [connections.postgresql] settings from .streamlit/secrets.toml."""
    return tomllib.loads((ROOT / ".streamlit" / "secrets.toml").read_text())["connections"]["postgresql"]


def connect(database: str | None = None):
    """Autocommit connection from the app's secrets, optionally to another database."""
    secrets = read_secrets()
    conn = psycopg2.connect(host=secrets["host"], port=secrets["port"], dbname=database or secrets["database"],
                            user=secrets["username"], password=secrets["password"])
    conn.autocommit = True
    return conn


def run_sql_file(conn, path: Path, schema: str | None = None) -> None:
    """Runs a .sql file, optionally with search_path set to schema first."""
    with conn.cursor() as cur:
        if schema:
            cur.execute(f"SET search_path TO {schema}")
        cur.execute(path.read_text())


def query_sql(name: str) -> str:
    """sql/queries/<name>.sql minus comment lines (their :names would otherwise be bound as parameters).
    The app and the benchmark both read queries through this, so they run identical SQL."""
    lines = (ROOT / "sql" / "queries" / f"{name}.sql").read_text().splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("--"))


def stage(conn, raw_dir: Path) -> int:
    """Copies the CSVs in raw_dir into the staging schema; returns the match count."""
    with conn.cursor() as cur:
        cur.execute(STAGING_DDL)
        for table in TABLES:
            with gzip.open(raw_dir / f"{table}.csv.gz", "rt") as f:
                cur.copy_expert(f"COPY staging.{table} FROM STDIN WITH (FORMAT csv, HEADER true)", f)
        # hashed ranks spread every subset over the whole time window
        cur.execute("""
            ALTER TABLE staging.match ADD COLUMN sample_rank BIGINT;
            UPDATE staging.match s SET sample_rank = r.rank
            FROM (SELECT match_id, row_number() OVER (ORDER BY md5(match_id::TEXT), match_id) AS rank
                  FROM staging.match) r
            WHERE s.match_id = r.match_id;
            CREATE INDEX ON staging.match (sample_rank);
            CREATE INDEX ON staging.match_player (match_id);
            CREATE INDEX ON staging.match_player_item (match_id);
            ANALYZE staging.match, staging.match_player, staging.match_player_item;
            SELECT COUNT(*) FROM staging.match;
        """)
        return cur.fetchone()[0]


def load(conn, schema: str, matches: int | None = None) -> float:
    """Replaces schema's data with the first `matches` staged matches (all if None); returns seconds."""
    started = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(f"SET search_path TO {schema}")
        cur.execute("TRUNCATE hero, item_tier, item, player, match, match_player, match_player_item CASCADE")
        cur.execute("DROP TABLE IF EXISTS pg_temp.chosen")
        cur.execute("CREATE TEMP TABLE chosen AS SELECT match_id FROM staging.match WHERE sample_rank <= %s",
                    (matches if matches is not None else 2 ** 62,))
        if schema == "optimized":
            cur.execute("SELECT optimized.ensure_partitions(min(match_id), max(match_id)) FROM chosen")
        cur.execute("""
            INSERT INTO hero SELECT * FROM staging.hero;
            INSERT INTO item_tier SELECT * FROM staging.item_tier;
            INSERT INTO item SELECT * FROM staging.item;
            INSERT INTO player (account_id)
                SELECT DISTINCT account_id FROM staging.match_player JOIN chosen USING (match_id);
            INSERT INTO match
                SELECT match_id, start_time, duration_s, game_mode, match_mode, winning_team, average_badge
                FROM staging.match JOIN chosen USING (match_id);
            INSERT INTO match_player SELECT mp.* FROM staging.match_player mp JOIN chosen USING (match_id);
            INSERT INTO match_player_item SELECT mpi.* FROM staging.match_player_item mpi JOIN chosen USING (match_id);
        """)
    return time.perf_counter() - started
