-- Deadlock Statistics: OPTIMIZED schema
-- Filled with data from the Deadlock API: https://api.deadlock-api.com/docs
--
-- Same 3NF tables, keys and constraints as baseline.sql, plus:
--   1. range partitions on match_id for match, match_player and
--      match_player_item, so date-bounded queries skip old data and data
--      older than a week is removed by dropping whole partitions
--   2. B-tree indexes for the dashboard's lookup and join columns
--   3. materialized views holding daily hero and item win rate rollups
--
-- Why match_id and not start_time: PostgreSQL requires a partitioned table's
-- primary key to include the partition key. Partitioning on start_time would
-- force a copy of start_time into the child tables (breaking 3NF) to keep the
-- foreign keys. match_id is already in every key, and the API hands out match
-- IDs in time order (~700k per day as of Oct 2026), so each 700k-ID partition
-- holds roughly one day of matches. Only the last ~7 days are kept; see the
-- partition lifecycle section below.
--
-- Pruning by date: a start_time filter alone can't skip partitions, because
-- the tables are split on match_id. Add a match_id lower bound to each
-- partitioned table in the query, e.g.
--
--     WHERE m.start_time >= :since
--       AND m.match_id  >= optimized.first_match_id(:since)
--       AND mp.match_id >= optimized.first_match_id(:since)
--
-- The bound is the smallest match_id at or after :since, so it never drops a
-- correct row even if a few IDs arrive out of order; the start_time filter
-- still decides which rows qualify. The function result is known when the
-- query starts, so the executor removes partitions before scanning them
-- (EXPLAIN shows "Subplans Removed").
--
-- All three partitioned tables share the same bounds, so the planner can join
-- them partition by partition when enable_partitionwise_join is on (it is off
-- by default; toggle it per session to measure its effect).

DROP SCHEMA IF EXISTS optimized CASCADE;
CREATE SCHEMA optimized;
SET search_path TO optimized;

-- hero entity represents the playable characters in Deadlock
CREATE TABLE hero (
    hero_id      INTEGER PRIMARY KEY,
    name         VARCHAR(100) NOT NULL,
    hero_type    VARCHAR(50),
    complexity   INTEGER CHECK (complexity BETWEEN 1 AND 3)
);

-- item_tier entity holds the soul cost shared by every item in a tier
-- (kept separate so cost depends only on the tier, not on item_id)
CREATE TABLE item_tier (
    item_tier  INTEGER PRIMARY KEY CHECK (item_tier > 0),
    cost       INTEGER NOT NULL CHECK (cost >= 0)
);

-- item entity represents the items that players can buy in game
CREATE TABLE item (
    item_id         BIGINT PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    item_slot_type  VARCHAR(20),
    item_tier       INTEGER REFERENCES item_tier (item_tier)
);

-- player entity represents the human players in a Deadlock game
CREATE TABLE player (
    account_id          INTEGER PRIMARY KEY, -- SteamID3
    account_name        VARCHAR(255),
    ranked_badge_level  INTEGER CHECK (ranked_badge_level >= 0), -- tier * 10 + subtier, e.g. 86
    last_updated        TIMESTAMPTZ
);

-- match entity represents a single game of Deadlock
CREATE TABLE match (
    match_id       BIGINT PRIMARY KEY,
    start_time     TIMESTAMPTZ NOT NULL,
    duration_s     INTEGER NOT NULL CHECK (duration_s > 0),
    game_mode      VARCHAR(30) NOT NULL, -- e.g. 'Normal', 'StreetBrawl'
    match_mode     VARCHAR(30) NOT NULL, -- e.g. 'Ranked', 'Unranked'
    winning_team   SMALLINT NOT NULL CHECK (winning_team IN (0, 1)),
    average_badge  INTEGER CHECK (average_badge >= 0) -- avg rank across both teams
) PARTITION BY RANGE (match_id);

-- match_player relation represents the connection between player entity and match entity
-- one row per player per match (12 per match)
CREATE TABLE match_player (
    match_id       BIGINT NOT NULL REFERENCES match (match_id) ON DELETE CASCADE,
    account_id     INTEGER NOT NULL REFERENCES player (account_id),
    hero_id        INTEGER NOT NULL REFERENCES hero (hero_id),
    team           SMALLINT NOT NULL CHECK (team IN (0, 1)),
    assigned_lane  INTEGER, -- won is derived: team = match.winning_team
    kills          INTEGER NOT NULL DEFAULT 0 CHECK (kills >= 0),
    deaths         INTEGER NOT NULL DEFAULT 0 CHECK (deaths >= 0),
    assists        INTEGER NOT NULL DEFAULT 0 CHECK (assists >= 0),
    net_worth      INTEGER NOT NULL DEFAULT 0 CHECK (net_worth >= 0), -- final souls
    last_hits      INTEGER CHECK (last_hits >= 0),
    denies         INTEGER CHECK (denies >= 0),
    hero_level     INTEGER CHECK (hero_level >= 0),
    PRIMARY KEY (match_id, account_id)
) PARTITION BY RANGE (match_id);

-- match_player_item relation represents the items that a player purchases in game
CREATE TABLE match_player_item (
    match_id     BIGINT NOT NULL,
    account_id   INTEGER NOT NULL,
    item_id      BIGINT NOT NULL REFERENCES item (item_id),
    game_time_s  INTEGER NOT NULL CHECK (game_time_s >= 0), -- purchase time
    sold_time_s  INTEGER, -- NULL if never sold
    PRIMARY KEY (match_id, account_id, item_id, game_time_s),
    FOREIGN KEY (match_id, account_id)
        REFERENCES match_player (match_id, account_id) ON DELETE CASCADE,
    CHECK (sold_time_s IS NULL OR sold_time_s >= game_time_s)
) PARTITION BY RANGE (match_id);

-- Partition lifecycle: the database keeps a rolling window of about a week.
-- Partitions are created on demand rather than up front:
--   1. before inserting a batch of matches, the loader calls
--          SELECT optimized.ensure_partitions(<lowest match_id>, <highest match_id>);
--   2. after loading, it calls
--          SELECT optimized.drop_old_partitions();   -- default keep = 7 days
--          SELECT optimized.refresh_stats();
-- Dropping a partition frees its disk space immediately, with none of the
-- DELETE + VACUUM cost an unpartitioned table pays to expire old rows.

-- partition width in match IDs: ~700k matches start per day (Oct 2026), so
-- each partition holds about one day and the window is 7-8 partitions
CREATE FUNCTION partition_width()
RETURNS BIGINT
LANGUAGE sql IMMUTABLE
AS $$ SELECT 700000::BIGINT $$;

-- creates any missing partitions covering match IDs [from_id, to_id] for all
-- three partitioned tables; safe to re-run, existing partitions are skipped.
-- Bounds are multiples of the width and partitions are named by their first
-- ID, e.g. match_p119700000.
CREATE FUNCTION ensure_partitions(from_id BIGINT, to_id BIGINT)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    width  BIGINT := optimized.partition_width();
    lo     BIGINT := from_id - from_id % width;
    tbl    TEXT;
BEGIN
    WHILE lo <= to_id LOOP
        FOREACH tbl IN ARRAY ARRAY['match', 'match_player', 'match_player_item'] LOOP
            EXECUTE format(
                'CREATE TABLE IF NOT EXISTS optimized.%I PARTITION OF optimized.%I
                     FOR VALUES FROM (%s) TO (%s)',
                tbl || '_p' || lo, tbl, lo, lo + width);
        END LOOP;
        lo := lo + width;
    END LOOP;
END;
$$;

-- catch-all partitions so a match outside every partition still inserts
-- instead of failing the batch. drop_old_partitions() expires old rows here
-- too. A partition can't be created while the default holds rows in its
-- range, which is why ensure_partitions() must run before each insert.
CREATE TABLE match_default             PARTITION OF match             DEFAULT;
CREATE TABLE match_player_default      PARTITION OF match_player      DEFAULT;
CREATE TABLE match_player_item_default PARTITION OF match_player_item DEFAULT;

-- smallest match_id starting at or after since: a safe lower bound for
-- pruning (see the header). The OFFSET 0 keeps the planner from answering
-- min() by walking the primary key from the oldest match upward; instead it
-- reads only the start_time index entries inside the window.
CREATE FUNCTION first_match_id(since TIMESTAMPTZ)
RETURNS BIGINT
LANGUAGE plpgsql STABLE
AS $$
BEGIN
    RETURN COALESCE(
        (SELECT min(match_id)
         FROM (SELECT match_id FROM optimized.match
               WHERE start_time >= since OFFSET 0) in_window),
        9223372036854775807); -- no matches after since: prune everything
END;
$$;

-- drops every partition whose matches all started more than keep ago, and
-- deletes expired rows that landed in the default partitions. A partition is
-- dropped only when its upper bound is at or below first_match_id(cutoff), so
-- it can't hold a match inside the window. The partition straddling the
-- cutoff is kept, so up to one extra day survives. A recent match with an
-- unusually low ID lowers that bound and delays drops, but never removes a
-- match inside the window. Returns the number of partitions dropped per table.
CREATE FUNCTION drop_old_partitions(keep INTERVAL DEFAULT INTERVAL '7 days')
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    cutoff_id  BIGINT := optimized.first_match_id(now() - keep);
    part       RECORD;
    tbl        TEXT;
    dropped    INTEGER := 0;
BEGIN
    FOR part IN
        SELECT substring(c.relname FROM '^match_p(\d+)$')::BIGINT AS lo
        FROM pg_inherits i
        JOIN pg_class c ON c.oid = i.inhrelid
        WHERE i.inhparent = 'optimized.match'::regclass
          AND c.relname ~ '^match_p\d+$'
    LOOP
        CONTINUE WHEN part.lo + optimized.partition_width() > cutoff_id;
        -- children first: a match partition can only be detached once no
        -- match_player rows reference it
        FOREACH tbl IN ARRAY ARRAY['match_player_item', 'match_player', 'match'] LOOP
            EXECUTE format('ALTER TABLE optimized.%I DETACH PARTITION optimized.%I',
                           tbl, tbl || '_p' || part.lo);
            EXECUTE format('DROP TABLE optimized.%I', tbl || '_p' || part.lo);
        END LOOP;
        dropped := dropped + 1;
    END LOOP;

    -- cascades to match_player_default and match_player_item_default
    DELETE FROM optimized.match_default WHERE start_time < now() - keep;
    RETURN dropped;
END;
$$;

-- B-tree indexes (declared on the parent, so every partition gets its own copy)
-- The primary keys already cover the FK joins: match_player's key starts with
-- match_id and match_player_item's with (match_id, account_id).

-- date-range filters and first_match_id(); INCLUDE allows an index-only scan
CREATE INDEX match_start_time_idx ON match (start_time) INCLUDE (match_id);

-- hero stat pages; INCLUDE columns let the scan skip the heap
CREATE INDEX match_player_hero_idx ON match_player (hero_id)
    INCLUDE (team, kills, deaths, assists, net_worth);

-- a player's match history, newest first (match IDs increase over time)
CREATE INDEX match_player_account_idx ON match_player (account_id, match_id DESC);

-- item stat pages
CREATE INDEX match_player_item_item_idx ON match_player_item (item_id);

-- Materialized views: daily rollups so the dashboard sums a few rows per
-- hero or item per day instead of rescanning every match. Dates are UTC.
-- Refresh after each ingest with SELECT optimized.refresh_stats();

-- hero results per day, game mode and match mode
CREATE MATERIALIZED VIEW hero_daily_stats AS
SELECT
    (m.start_time AT TIME ZONE 'UTC')::DATE      AS match_date,
    m.game_mode,
    m.match_mode,
    mp.hero_id,
    COUNT(*)                                     AS games,
    COUNT(*) FILTER (WHERE mp.team = m.winning_team) AS wins,
    SUM(mp.kills)                                AS kills,
    SUM(mp.deaths)                               AS deaths,
    SUM(mp.assists)                              AS assists,
    SUM(mp.net_worth)                            AS net_worth
FROM match_player mp
JOIN match m USING (match_id)
GROUP BY 1, 2, 3, 4;

-- unique index is required for REFRESH ... CONCURRENTLY
CREATE UNIQUE INDEX hero_daily_stats_key
    ON hero_daily_stats (match_date, game_mode, match_mode, hero_id);

-- item results per day, game mode and match mode; a player who sells and
-- rebuys an item counts once for that game
CREATE MATERIALIZED VIEW item_daily_stats AS
SELECT
    (m.start_time AT TIME ZONE 'UTC')::DATE      AS match_date,
    m.game_mode,
    m.match_mode,
    bought.item_id,
    COUNT(*)                                     AS games,
    COUNT(*) FILTER (WHERE mp.team = m.winning_team) AS wins
FROM (
    SELECT DISTINCT match_id, account_id, item_id
    FROM match_player_item
) bought
JOIN match_player mp USING (match_id, account_id)
JOIN match m USING (match_id)
GROUP BY 1, 2, 3, 4;

CREATE UNIQUE INDEX item_daily_stats_key
    ON item_daily_stats (match_date, game_mode, match_mode, item_id);

-- rebuilds both rollups without blocking dashboard reads
CREATE FUNCTION refresh_stats()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY optimized.hero_daily_stats;
    REFRESH MATERIALIZED VIEW CONCURRENTLY optimized.item_daily_stats;
END;
$$;
