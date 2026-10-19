-- Smallest match_id at or after :since, passed to the windowed queries as :min_match_id.
SELECT first_match_id(:since) AS min_match_id;
