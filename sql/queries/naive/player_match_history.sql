-- NAIVE player_match_history.sql. Mistake: a type cast on the indexed column.
-- The account ID arrives as text (say, from a search box), and the column is cast to match it
-- instead of the parameter. Postgres must cast every row's account_id before comparing, so the
-- (account_id, match_id DESC) index can't be used: every row of match_player is read.
SELECT
    m.match_id,
    m.start_time,
    m.match_mode,
    m.duration_s,
    h.name AS hero,
    mp.kills,
    mp.deaths,
    mp.assists,
    mp.net_worth,
    (mp.team = m.winning_team) AS won
FROM match_player mp
JOIN match m USING (match_id)
JOIN hero h USING (hero_id)
WHERE CAST(mp.account_id AS TEXT) = CAST(:account_id AS TEXT)
ORDER BY mp.match_id DESC
LIMIT 20;
