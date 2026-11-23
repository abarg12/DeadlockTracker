-- Matches, average duration and average rank per match mode in the :hours hours before :as_of.
-- The filter compares the bare column to a constant, so the index on start_time can serve it.
SELECT
    match_mode,
    COUNT(*) AS matches,
    ROUND(AVG(duration_s), 1) AS avg_duration_s,
    ROUND(AVG(average_badge), 1) AS avg_badge
FROM match
WHERE start_time >= CAST(:as_of AS TIMESTAMPTZ) - make_interval(hours => :hours)
GROUP BY match_mode
ORDER BY match_mode;
