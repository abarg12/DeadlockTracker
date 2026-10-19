-- Games, wins, win rate and average K/D/A per hero since :since for one match mode.
-- :min_match_id is first_match_id(:since).
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
        mp.hero_id,
        COUNT(*)                                          AS games,
        COUNT(*) FILTER (WHERE mp.team = m.winning_team)  AS wins,
        ROUND(AVG((mp.team = m.winning_team)::INT), 4)    AS win_rate,
        ROUND(AVG(mp.kills), 2)                           AS avg_kills,
        ROUND(AVG(mp.deaths), 2)                          AS avg_deaths,
        ROUND(AVG(mp.assists), 2)                         AS avg_assists
    FROM match_player mp
    JOIN match m USING (match_id)
    WHERE m.start_time >= :since
      AND m.match_mode = :match_mode
      AND m.match_id  >= :min_match_id
      AND mp.match_id >= :min_match_id
    GROUP BY mp.hero_id
) s
JOIN hero h USING (hero_id)
ORDER BY s.win_rate DESC, h.hero_id;
