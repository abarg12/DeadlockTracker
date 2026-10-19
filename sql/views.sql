-- Daily (UTC) hero and item rollups for whichever schema search_path points at.
-- Refresh after each load with SELECT refresh_stats();

DROP MATERIALIZED VIEW IF EXISTS hero_daily_stats;
DROP MATERIALIZED VIEW IF EXISTS item_daily_stats;
DROP FUNCTION IF EXISTS refresh_stats();

-- hero results per day, game mode and match mode
CREATE MATERIALIZED VIEW hero_daily_stats AS
SELECT
    (m.start_time AT TIME ZONE 'UTC')::DATE          AS match_date,
    m.game_mode,
    m.match_mode,
    mp.hero_id,
    COUNT(*)                                         AS games,
    COUNT(*) FILTER (WHERE mp.team = m.winning_team) AS wins,
    SUM(mp.kills)                                    AS kills,
    SUM(mp.deaths)                                   AS deaths,
    SUM(mp.assists)                                  AS assists,
    SUM(mp.net_worth)                                AS net_worth
FROM match_player mp
JOIN match m USING (match_id)
GROUP BY 1, 2, 3, 4;

-- unique index is required for REFRESH ... CONCURRENTLY
CREATE UNIQUE INDEX hero_daily_stats_key
    ON hero_daily_stats (match_date, game_mode, match_mode, hero_id);

-- item results per day, game mode and match mode; rebuys count once per game
CREATE MATERIALIZED VIEW item_daily_stats AS
SELECT
    match_date,
    game_mode,
    match_mode,
    item_id,
    COUNT(*)                                         AS games,
    COUNT(*) FILTER (WHERE won)                      AS wins
FROM (
    SELECT
        (m.start_time AT TIME ZONE 'UTC')::DATE      AS match_date,
        m.game_mode,
        m.match_mode,
        mpi.item_id,
        (mp.team = m.winning_team)                   AS won
    FROM match_player_item mpi
    JOIN match_player mp USING (match_id, account_id)
    JOIN match m USING (match_id)
    GROUP BY mpi.match_id, mpi.account_id, mpi.item_id, m.start_time, m.game_mode, m.match_mode, won
) bought
GROUP BY 1, 2, 3, 4;

CREATE UNIQUE INDEX item_daily_stats_key
    ON item_daily_stats (match_date, game_mode, match_mode, item_id);

-- rebuilds both rollups without blocking reads, in the schema it was created in
CREATE FUNCTION refresh_stats()
RETURNS VOID
LANGUAGE plpgsql
SET search_path FROM CURRENT
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY hero_daily_stats;
    REFRESH MATERIALIZED VIEW CONCURRENTLY item_daily_stats;
END;
$$;
