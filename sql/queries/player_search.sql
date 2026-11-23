-- Up to 20 players whose name contains the search text: exact matches first, then the most active.
-- :pattern is '%' || text || '%' with LIKE wildcards escaped. The leading % rules out a b-tree
-- index; the trigram index in indexes.sql serves it.
SELECT p.account_id, p.account_name, COUNT(*) AS matches
FROM player p
JOIN match_player mp USING (account_id)
WHERE p.account_name ILIKE :pattern
GROUP BY p.account_id, p.account_name
ORDER BY lower(p.account_name) = lower(:text) DESC, matches DESC, p.account_id
LIMIT 20;
