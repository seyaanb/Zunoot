-- Repair for BUG-3 (docs/BUGFIXES.md): every guild join incremented EVERY
-- guild's no_of_members, so stored counts in production are inflated.
--
-- This touches production data. Run it yourself, by hand, after the fix is
-- deployed (otherwise new joins re-corrupt the counts). Take a backup first
-- (docs/RESTORE_DRILL.md, "on-demand backup").
--
--   psql "$DATABASE_URL" -f db/repairs/001_guild_member_counts.sql
--
-- It ends in ROLLBACK, so the first run only shows you what would change.
-- When the preview looks right, change ROLLBACK to COMMIT and run it again.

BEGIN;

-- 1. Preview: stored vs actual member counts.
SELECT g.guild_name,
       g.no_of_members                AS stored_count,
       COUNT(s.username)              AS actual_count
FROM guilds g
LEFT JOIN students s ON s.guild_name = g.guild_name
GROUP BY g.guild_name, g.no_of_members
ORDER BY g.guild_name;

-- 2. Repair: set each guild's count from its actual members.
UPDATE guilds g
SET no_of_members = sub.actual
FROM (
    SELECT g2.guild_name, COUNT(s.username) AS actual
    FROM guilds g2
    LEFT JOIN students s ON s.guild_name = g2.guild_name
    GROUP BY g2.guild_name
) sub
WHERE g.guild_name = sub.guild_name
  AND g.no_of_members <> sub.actual;

-- 3. Check: this must return zero rows.
SELECT g.guild_name, g.no_of_members, COUNT(s.username) AS actual
FROM guilds g
LEFT JOIN students s ON s.guild_name = g.guild_name
GROUP BY g.guild_name, g.no_of_members
HAVING g.no_of_members <> COUNT(s.username);

ROLLBACK;  -- change to COMMIT once the preview above looks right
