-- Matches per UTC day and average duration since :since.
-- :min_match_id is first_match_id(:since).
SELECT
    (m.start_time AT TIME ZONE 'UTC')::DATE           AS match_date,
    COUNT(*)                                          AS matches,
    ROUND(AVG(m.duration_s), 1)                       AS avg_duration_s
FROM match m
WHERE m.start_time >= :since
  AND m.match_id >= :min_match_id
GROUP BY 1
ORDER BY 1;
