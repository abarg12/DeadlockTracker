-- Games and win rate per item since :since for one match mode; rebuys count once per game.
-- :min_match_id is first_match_id(:since).
SELECT
    i.item_id,
    i.name,
    i.item_tier,
    t.cost,
    s.games,
    s.wins,
    ROUND(s.wins::NUMERIC / s.games, 4)  AS win_rate
FROM (
    SELECT
        item_id,
        COUNT(*)                     AS games,
        COUNT(*) FILTER (WHERE won)  AS wins
    FROM (
        SELECT mpi.item_id, (mp.team = m.winning_team) AS won
        FROM match_player_item mpi
        JOIN match_player mp USING (match_id, account_id)
        JOIN match m USING (match_id)
        WHERE m.start_time >= :since
          AND m.match_mode = :match_mode
          AND m.match_id   >= :min_match_id
          AND mp.match_id  >= :min_match_id
          AND mpi.match_id >= :min_match_id
        GROUP BY mpi.match_id, mpi.account_id, mpi.item_id, won
    ) bought
    GROUP BY item_id
) s
JOIN item i USING (item_id)
LEFT JOIN item_tier t USING (item_tier)
ORDER BY win_rate DESC, i.item_id;
