-- item_win_rates.sql from the materialized view (same rows when :since is a UTC midnight)
SELECT
    i.item_id,
    i.name,
    i.item_tier,
    t.cost,
    s.games,
    s.wins,
    s.win_rate
FROM (
    SELECT
        item_id,
        SUM(games)                                    AS games,
        SUM(wins)                                     AS wins,
        ROUND(SUM(wins)::NUMERIC / SUM(games), 4)     AS win_rate
    FROM item_daily_stats
    WHERE match_date >= (CAST(:since AS TIMESTAMPTZ) AT TIME ZONE 'UTC')::DATE
      AND match_mode = :match_mode
    GROUP BY item_id
) s
JOIN item i USING (item_id)
LEFT JOIN item_tier t USING (item_tier)
ORDER BY s.win_rate DESC, i.item_id;
