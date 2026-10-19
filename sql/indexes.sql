-- B-tree indexes for whichever schema search_path points at.
-- The primary keys already cover the foreign key joins.

-- date filters and first_match_id()
CREATE INDEX IF NOT EXISTS match_start_time_idx ON match (start_time) INCLUDE (match_id);

-- hero stats; INCLUDE allows index-only scans
CREATE INDEX IF NOT EXISTS match_player_hero_idx ON match_player (hero_id)
    INCLUDE (team, kills, deaths, assists, net_worth);

-- a player's match history, newest first
CREATE INDEX IF NOT EXISTS match_player_account_idx ON match_player (account_id, match_id DESC);

-- item stats
CREATE INDEX IF NOT EXISTS match_player_item_item_idx ON match_player_item (item_id);
