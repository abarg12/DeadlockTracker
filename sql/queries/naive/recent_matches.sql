-- NAIVE study/recent_matches.sql. Mistake: arithmetic on the filtered column.
-- "match age <= :hours" means the same as "start_time >= :as_of - :hours", but Postgres must
-- compute the age of every match to check it, so the index on start_time can't be used.
SELECT
    match_mode,
    COUNT(*) AS matches,
    ROUND(AVG(duration_s), 1) AS avg_duration_s,
    ROUND(AVG(average_badge), 1) AS avg_badge
FROM match
WHERE CAST(:as_of AS TIMESTAMPTZ) - start_time <= make_interval(hours => :hours)
GROUP BY match_mode
ORDER BY match_mode;
