-- Deadlock Statistics: BASELINE schema (data from https://api.deadlock-api.com/docs)
-- 3NF tables with keys and constraints only: the control group for the experiments.

DROP SCHEMA IF EXISTS baseline CASCADE;
CREATE SCHEMA baseline;
SET search_path TO baseline;

-- hero entity represents the playable characters in Deadlock
CREATE TABLE hero (
    hero_id      INTEGER PRIMARY KEY,
    name         VARCHAR(100) NOT NULL,
    hero_type    VARCHAR(50),
    complexity   INTEGER CHECK (complexity > 0)
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
    account_id          BIGINT PRIMARY KEY, -- SteamID3 (unsigned 32-bit, can exceed INTEGER)
    account_name        VARCHAR(255),
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
);

-- match_player relation represents the connection between player entity and match entity
-- one row per player per match (12 per match)
CREATE TABLE match_player (
    match_id       BIGINT NOT NULL REFERENCES match (match_id) ON DELETE CASCADE,
    account_id     BIGINT NOT NULL REFERENCES player (account_id),
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
);

-- match_player_item relation represents the items that a player purchases in game
CREATE TABLE match_player_item (
    match_id     BIGINT NOT NULL,
    account_id   BIGINT NOT NULL,
    item_id      BIGINT NOT NULL REFERENCES item (item_id),
    game_time_s  INTEGER NOT NULL CHECK (game_time_s >= 0), -- purchase time
    sold_time_s  INTEGER, -- NULL if never sold
    PRIMARY KEY (match_id, account_id, item_id, game_time_s),
    FOREIGN KEY (match_id, account_id)
        REFERENCES match_player (match_id, account_id) ON DELETE CASCADE,
    CHECK (sold_time_s IS NULL OR sold_time_s >= game_time_s)
);

-- smallest match_id at or after since; same as in optimized.sql so both run identical queries
CREATE FUNCTION first_match_id(since TIMESTAMPTZ)
RETURNS BIGINT
LANGUAGE plpgsql STABLE
AS $$
BEGIN
    RETURN COALESCE(
        (SELECT min(match_id)
         FROM (SELECT match_id FROM baseline.match
               WHERE start_time >= since OFFSET 0) in_window),
        9223372036854775807); -- no matches after since
END;
$$;
