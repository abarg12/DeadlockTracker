-- Deadlock Statistics schemas
-- Filled with data from the Deadlock API: https://api.deadlock-api.com/docs

-- hero entity represents the playable characters in Deadlock
CREATE TABLE IF NOT EXISTS hero (
    hero_id      INTEGER PRIMARY KEY,
    name         VARCHAR(100) NOT NULL,
    hero_type    VARCHAR(50),
    complexity   INTEGER
);

-- item entity represents the items that players can buy in game
CREATE TABLE IF NOT EXISTS item (
    item_id         BIGINT PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    item_slot_type  VARCHAR(20),
    item_tier       INTEGER,
    cost            INTEGER
);

-- player entity represents the human players in a Deadlock game
CREATE TABLE IF NOT EXISTS player (
    account_id          INTEGER PRIMARY KEY, -- SteamID3
    account_name        VARCHAR(255),
    ranked_badge_level  INTEGER, -- tier * 10 + subtier, e.g. 86
    last_updated        TIMESTAMPTZ
);

-- match entity represents a single game of Deadlock
CREATE TABLE IF NOT EXISTS match (
    match_id       BIGINT PRIMARY KEY,
    start_time     TIMESTAMPTZ NOT NULL,
    duration_s     INTEGER NOT NULL,
    game_mode      VARCHAR(30) NOT NULL, -- e.g. 'Normal', 'StreetBrawl'
    match_mode     VARCHAR(30) NOT NULL, -- e.g. 'Ranked', 'Unranked'
    winning_team   SMALLINT NOT NULL,
    average_badge  INTEGER -- avg rank across both teams
);

-- match_player relation represents the connection between player entity and match entity
-- one row per player per match (12 per match)
CREATE TABLE IF NOT EXISTS match_player (
    match_id       BIGINT NOT NULL REFERENCES match (match_id) ON DELETE CASCADE,
    account_id     INTEGER NOT NULL REFERENCES player (account_id),
    hero_id        INTEGER NOT NULL REFERENCES hero (hero_id),
    team           SMALLINT NOT NULL,
    assigned_lane  INTEGER,
    won            BOOLEAN NOT NULL,
    kills          INTEGER NOT NULL DEFAULT 0,
    deaths         INTEGER NOT NULL DEFAULT 0,
    assists        INTEGER NOT NULL DEFAULT 0,
    net_worth      INTEGER NOT NULL DEFAULT 0, -- final souls
    last_hits      INTEGER,
    denies         INTEGER,
    hero_level     INTEGER,
    PRIMARY KEY (match_id, account_id)
);

-- match_player_item relation represents the items that a player purchases in game
CREATE TABLE IF NOT EXISTS match_player_item (
    match_id     BIGINT NOT NULL,
    account_id   INTEGER NOT NULL,
    item_id      BIGINT NOT NULL REFERENCES item (item_id),
    game_time_s  INTEGER NOT NULL, -- purchase time
    sold_time_s  INTEGER, -- NULL if never sold
    PRIMARY KEY (match_id, account_id, item_id, game_time_s),
    FOREIGN KEY (match_id, account_id)
        REFERENCES match_player (match_id, account_id) ON DELETE CASCADE
);
