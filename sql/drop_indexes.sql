-- removes the indexes.sql indexes to help with testing process

DROP INDEX IF EXISTS match_start_time_idx;
DROP INDEX IF EXISTS match_player_hero_idx;
DROP INDEX IF EXISTS match_player_account_idx;
DROP INDEX IF EXISTS match_player_item_item_idx;
