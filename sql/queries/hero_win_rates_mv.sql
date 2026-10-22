-- hero_win_rates.sql from the materialized view (same rows when :since is a UTC midnight)
SELECT
    h.hero_id,
    h.name,
    s.games,
    s.wins,
    s.win_rate,
    s.avg_kills,
    s.avg_deaths,
    s.avg_assists
FROM (
    SELECT
        hero_id,
        SUM(games) AS games,
        SUM(wins) AS wins,
        ROUND(SUM(wins)::NUMERIC / SUM(games), 4) AS win_rate,
        ROUND(SUM(kills)::NUMERIC / SUM(games), 2) AS avg_kills,
        ROUND(SUM(deaths)::NUMERIC / SUM(games), 2) AS avg_deaths,
        ROUND(SUM(assists)::NUMERIC / SUM(games), 2) AS avg_assists
    FROM hero_daily_stats
    WHERE match_date >= (CAST(:since AS TIMESTAMPTZ) AT TIME ZONE 'UTC')::DATE
      AND match_mode = :match_mode
    GROUP BY hero_id
) s
JOIN hero h USING (hero_id)
ORDER BY s.win_rate DESC, h.hero_id;
