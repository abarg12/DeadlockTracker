-- B-tree indexes, plus one trigram index for name search

-- date filters and first_match_id()
CREATE INDEX IF NOT EXISTS match_start_time_idx ON match (start_time) INCLUDE (match_id);

-- hero stats; INCLUDE allows index-only scans
CREATE INDEX IF NOT EXISTS match_player_hero_idx ON match_player (hero_id)
    INCLUDE (team, kills, deaths, assists, net_worth);

-- a player's match history, newest first
CREATE INDEX IF NOT EXISTS match_player_account_idx ON match_player (account_id, match_id DESC);

-- item stats
CREATE INDEX IF NOT EXISTS match_player_item_item_idx ON match_player_item (item_id);

-- player name search (ILIKE '%text%'): a b-tree can't serve a leading wildcard, trigrams can
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;
CREATE INDEX IF NOT EXISTS player_name_trgm_idx ON player USING gin (account_name public.gin_trgm_ops);
