-- NAIVE hero_win_rates.sql. Mistake: aggregating everything first, then filtering.
-- A general "stats per hero, day and mode" CTE is built over the whole table, and only then
-- narrowed to :match_mode and :since. MATERIALIZED makes the CTE an optimization fence, as every
-- CTE was before PostgreSQL 12 (and one referenced twice still is), so the filters can't be
-- pushed below the aggregation and every row of every mode and day is grouped.
WITH daily AS MATERIALIZED (
    SELECT
        (m.start_time AT TIME ZONE 'UTC')::DATE AS match_date,
        m.match_mode,
        mp.hero_id,
        COUNT(*) AS games,
        COUNT(*) FILTER (WHERE mp.team = m.winning_team) AS wins,
        SUM(mp.kills) AS kills,
        SUM(mp.deaths) AS deaths,
        SUM(mp.assists) AS assists
    FROM match_player mp
    JOIN match m USING (match_id)
    GROUP BY 1, 2, 3
)
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
    FROM daily
    WHERE match_date >= (CAST(:since AS TIMESTAMPTZ) AT TIME ZONE 'UTC')::DATE
      AND match_mode = :match_mode
    GROUP BY hero_id
) s
JOIN hero h USING (hero_id)
ORDER BY s.win_rate DESC, h.hero_id;
