-- Reference data needed for the app to work in LOCAL DEV / TESTS / CI.
-- Never applied to production. insert_new_user() gives every new user
-- shop items 1 (default avatar) and 13 (default theme), so those IDs are fixed.

INSERT INTO shopitems (item_id, item_type, item_name, price) VALUES
    (1,  'avatar', 'default', 0),
    (2,  'avatar', 'chimp',   100),
    (3,  'avatar', 'penguin', 100),
    (4,  'avatar', 'rabbit',  100),
    (5,  'avatar', 'koala',   150),
    (6,  'avatar', 'rat',     150),
    (7,  'avatar', 'gecko',   150),
    (8,  'avatar', 'dog',     200),
    (9,  'avatar', 'wolf',    200),
    (10, 'avatar', 'frog',    200),
    (11, 'avatar', 'hamster', 250),
    (12, 'avatar', 'owl',     250),
    (13, 'theme',  'default', 0),
    (14, 'theme',  'ice',     300),
    (15, 'theme',  'sunset',  300),
    (16, 'theme',  'arcade',  400),
    (17, 'theme',  'forest',  400),
    (18, 'theme',  'matrix',  500),
    (19, 'theme',  'desert',  500),
    (20, 'avatar', 'tiger',   300)
ON CONFLICT (item_id) DO NOTHING;

SELECT setval(pg_get_serial_sequence('shopitems', 'item_id'), (SELECT MAX(item_id) FROM shopitems));

INSERT INTO pointsreset (reset_id, last_reset)
SELECT 1, to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD HH24:MI:SS.US')
WHERE NOT EXISTS (SELECT 1 FROM pointsreset);
