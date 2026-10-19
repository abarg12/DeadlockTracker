-- A player's 20 most recent matches (match IDs increase over time).
SELECT
    m.match_id,
    m.start_time,
    m.match_mode,
    m.duration_s,
    h.name                          AS hero,
    mp.kills,
    mp.deaths,
    mp.assists,
    mp.net_worth,
    (mp.team = m.winning_team)      AS won
FROM match_player mp
JOIN match m USING (match_id)
JOIN hero h USING (hero_id)
WHERE mp.account_id = :account_id
ORDER BY mp.match_id DESC
LIMIT 20;
