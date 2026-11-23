-- player_search.sql for names that START with the text (:prefix is text || '%', wildcards escaped).
-- An anchored pattern on lower(account_name) can be served by a b-tree index on that expression.
SELECT p.account_id, p.account_name, COUNT(*) AS matches
FROM player p
JOIN match_player mp USING (account_id)
WHERE lower(p.account_name) LIKE lower(:prefix)
GROUP BY p.account_id, p.account_name
ORDER BY lower(p.account_name) = lower(:text) DESC, matches DESC, p.account_id
LIMIT 20;
