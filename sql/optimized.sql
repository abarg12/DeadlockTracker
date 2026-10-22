-- Deadlock Statistics: OPTIMIZED schema, range partitioned on match_id (IDs increase over time)
-- Queries pass first_match_id(:since) as :min_match_id so old partitions are skipped

DROP SCHEMA IF EXISTS optimized CASCADE;
CREATE SCHEMA optimized;
-- bump when the layout changes; the app's ingest rebuilds a schema with an older version
COMMENT ON SCHEMA optimized IS 'deadlock-tracker v3';
SET search_path TO optimized;

-- hero entity represents the playable characters in Deadlock
CREATE TABLE hero (
    hero_id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    hero_type VARCHAR(50),
    complexity INTEGER CHECK (complexity > 0)
);

-- item_tier entity holds the soul cost shared by every item in a tier
-- (kept separate so cost depends only on the tier, not on item_id)
CREATE TABLE item_tier (
    item_tier INTEGER PRIMARY KEY CHECK (item_tier > 0),
    cost INTEGER NOT NULL CHECK (cost >= 0)
);

-- item entity represents the items that players can buy in game
CREATE TABLE item (
    item_id BIGINT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    item_slot_type VARCHAR(20),
    item_tier INTEGER REFERENCES item_tier (item_tier)
);

-- player entity represents the human players in a Deadlock game
CREATE TABLE player (
    account_id BIGINT PRIMARY KEY, -- SteamID3 (unsigned 32-bit, can exceed INTEGER)
    account_name VARCHAR(255),
    last_updated TIMESTAMPTZ
);

-- match entity represents a single game of Deadlock
CREATE TABLE match (
    match_id BIGINT PRIMARY KEY,
    start_time TIMESTAMPTZ NOT NULL,
    duration_s INTEGER NOT NULL CHECK (duration_s > 0),
    game_mode VARCHAR(30) NOT NULL, -- e.g. 'Normal', 'StreetBrawl'
    match_mode VARCHAR(30) NOT NULL, -- e.g. 'Ranked', 'Unranked'
    winning_team SMALLINT NOT NULL CHECK (winning_team IN (0, 1)),
    average_badge INTEGER CHECK (average_badge >= 0) -- avg rank across both teams
) PARTITION BY RANGE (match_id);

-- match_player relation represents the connection between player entity and match entity
-- one row per player per match (12 per match)
CREATE TABLE match_player (
    match_id BIGINT NOT NULL REFERENCES match (match_id) ON DELETE CASCADE,
    account_id BIGINT NOT NULL REFERENCES player (account_id),
    hero_id INTEGER NOT NULL REFERENCES hero (hero_id),
    team SMALLINT NOT NULL CHECK (team IN (0, 1)),
    assigned_lane INTEGER, -- won is derived: team = match.winning_team
    kills INTEGER NOT NULL DEFAULT 0 CHECK (kills >= 0),
    deaths INTEGER NOT NULL DEFAULT 0 CHECK (deaths >= 0),
    assists INTEGER NOT NULL DEFAULT 0 CHECK (assists >= 0),
    net_worth INTEGER NOT NULL DEFAULT 0 CHECK (net_worth >= 0), -- final souls
    last_hits INTEGER CHECK (last_hits >= 0),
    denies INTEGER CHECK (denies >= 0),
    hero_level INTEGER CHECK (hero_level >= 0),
    PRIMARY KEY (match_id, account_id)
) PARTITION BY RANGE (match_id);

-- match_player_item relation represents the items that a player purchases in game
CREATE TABLE match_player_item (
    match_id BIGINT NOT NULL,
    account_id BIGINT NOT NULL,
    item_id BIGINT NOT NULL REFERENCES item (item_id),
    game_time_s INTEGER NOT NULL CHECK (game_time_s >= 0), -- purchase time
    sold_time_s INTEGER, -- NULL if never sold
    PRIMARY KEY (match_id, account_id, item_id, game_time_s),
    FOREIGN KEY (match_id, account_id)
        REFERENCES match_player (match_id, account_id) ON DELETE CASCADE,
    CHECK (sold_time_s IS NULL OR sold_time_s >= game_time_s)
) PARTITION BY RANGE (match_id);

-- live ingest progress (one row); data_version increases with every commit so the app can drop stale caches
CREATE TABLE ingest_state (
    id BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),
    last_delta_hi BIGINT,
    references_refreshed_at TIMESTAMPTZ,
    last_run_at TIMESTAMPTZ,
    data_version BIGINT NOT NULL DEFAULT 0,
    backfill_done INTEGER,
    backfill_total INTEGER
);
INSERT INTO ingest_state DEFAULT VALUES;

-- ~700k matches start per day, so each partition holds about one day
CREATE FUNCTION partition_width()
RETURNS BIGINT
LANGUAGE sql IMMUTABLE
AS $$ SELECT 700000::BIGINT $$;

-- creates missing partitions covering [from_id, to_id]; run before each insert
CREATE FUNCTION ensure_partitions(from_id BIGINT, to_id BIGINT)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    width BIGINT := optimized.partition_width();
    lo BIGINT := from_id - from_id % width;
    tbl TEXT;
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

-- catch-all partitions for matches outside every range
CREATE TABLE match_default PARTITION OF match DEFAULT;
CREATE TABLE match_player_default PARTITION OF match_player DEFAULT;
CREATE TABLE match_player_item_default PARTITION OF match_player_item DEFAULT;

-- smallest match_id at or after since (OFFSET 0 stops a slow walk of the primary key)
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

-- drops partitions whose matches are all older than keep; returns how many
CREATE FUNCTION drop_old_partitions(keep INTERVAL DEFAULT INTERVAL '7 days')
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    cutoff_id BIGINT := optimized.first_match_id(now() - keep);
    part RECORD;
    tbl TEXT;
    dropped INTEGER := 0;
BEGIN
    FOR part IN
        SELECT substring(c.relname FROM '^match_p(\d+)$')::BIGINT AS lo
        FROM pg_inherits i
        JOIN pg_class c ON c.oid = i.inhrelid
        WHERE i.inhparent = 'optimized.match'::regclass
          AND c.relname ~ '^match_p\d+$'
    LOOP
        CONTINUE WHEN part.lo + optimized.partition_width() > cutoff_id;
        -- children first, so no foreign keys block the detach
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
