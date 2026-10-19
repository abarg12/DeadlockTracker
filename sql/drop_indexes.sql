-- removes the indexes.sql indexes from whichever schema search_path points at

DROP INDEX IF EXISTS match_start_time_idx;
DROP INDEX IF EXISTS match_player_hero_idx;
DROP INDEX IF EXISTS match_player_account_idx;
DROP INDEX IF EXISTS match_player_item_item_idx;
