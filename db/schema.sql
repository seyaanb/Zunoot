-- Zunoot schema for LOCAL DEV, TESTS and CI only.
--
-- IMPORTANT: this file was reconstructed from backend/queries.py and the
-- templates, not dumped from production. It is never applied to production.
-- Column ORDER matters: several queries use `select *` and unpack rows
-- positionally into constructors (User, Subject, Topic, Flashcard) or index
-- them in templates (guild[3], item[2], ...).
--
-- To check it against the real database (structure only, no rows):
--   pg_dump --schema-only --no-owner --no-privileges "$DATABASE_URL" > /tmp/prod_schema.sql
-- and diff the table definitions. If they differ, replace this file with the
-- real dump; tests and CI will then run against the true schema.

CREATE TABLE IF NOT EXISTS students (
    username        VARCHAR(255) PRIMARY KEY,
    first_name      VARCHAR(255) NOT NULL,
    last_name       VARCHAR(255) NOT NULL,
    password        VARCHAR(512) NOT NULL,
    email_address   VARCHAR(255) NOT NULL,
    date_joined     DATE,
    guild_name      VARCHAR(255),
    coins           INTEGER NOT NULL DEFAULT 0,
    avatar          VARCHAR(255) NOT NULL DEFAULT 'default',
    theme           VARCHAR(255) NOT NULL DEFAULT 'default',
    last_login      TIMESTAMP,
    guild_role      VARCHAR(50),
    points          INTEGER NOT NULL DEFAULT 0
);

-- students <-> guilds reference each other (see README, "Data model").
CREATE TABLE IF NOT EXISTS guilds (
    guild_name       VARCHAR(255) PRIMARY KEY,
    leader_username  VARCHAR(255) REFERENCES students(username) ON DELETE CASCADE,
    points           INTEGER NOT NULL DEFAULT 0,
    no_of_members    INTEGER NOT NULL DEFAULT 0
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'students_guild_name_fkey') THEN
        ALTER TABLE students
            ADD CONSTRAINT students_guild_name_fkey
            FOREIGN KEY (guild_name) REFERENCES guilds(guild_name) ON DELETE SET NULL;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS subjects (
    subject_id    SERIAL PRIMARY KEY,
    subject_name  VARCHAR(255) NOT NULL,
    username      VARCHAR(255) NOT NULL REFERENCES students(username) ON DELETE CASCADE,
    position      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS topics (
    topic_id    SERIAL PRIMARY KEY,
    topic_name  VARCHAR(255) NOT NULL,
    subject_id  INTEGER NOT NULL REFERENCES subjects(subject_id) ON DELETE CASCADE,
    position    INTEGER NOT NULL DEFAULT 0
);

-- easiness_factor must be a float type: flashcard.py does float arithmetic on
-- it, which would raise TypeError against a NUMERIC (Decimal) column.
CREATE TABLE IF NOT EXISTS flashcards (
    flashcard_id     SERIAL PRIMARY KEY,
    front            TEXT NOT NULL,
    back             TEXT NOT NULL,
    review_interval  INTEGER NOT NULL DEFAULT 0,
    repetition_no    INTEGER NOT NULL DEFAULT 0,
    easiness_factor  DOUBLE PRECISION NOT NULL DEFAULT 2.5,
    last_review      DATE,
    next_review      DATE,
    topic_id         INTEGER NOT NULL REFERENCES topics(topic_id) ON DELETE CASCADE,
    position         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS guildrequests (
    request_id        SERIAL PRIMARY KEY,
    request_username  VARCHAR(255) NOT NULL REFERENCES students(username) ON DELETE CASCADE,
    status            VARCHAR(50) NOT NULL,
    guild_name        VARCHAR(255) REFERENCES guilds(guild_name) ON DELETE CASCADE
);

-- last_reset is compared against str(datetime) in queries.points_reset(), so it
-- is stored as text (carried over from the SQLite schema).
CREATE TABLE IF NOT EXISTS pointsreset (
    reset_id    SERIAL PRIMARY KEY,
    last_reset  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shopitems (
    item_id    SERIAL PRIMARY KEY,
    item_type  VARCHAR(50) NOT NULL,
    item_name  VARCHAR(255) NOT NULL,
    price      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS purchases (
    username  VARCHAR(255) NOT NULL REFERENCES students(username) ON DELETE CASCADE,
    item_id   INTEGER NOT NULL REFERENCES shopitems(item_id),
    PRIMARY KEY (username, item_id)
);

CREATE TABLE IF NOT EXISTS communitysubjects (
    community_subject_id    SERIAL PRIMARY KEY,
    community_subject_name  VARCHAR(255) NOT NULL,
    uploader_username       VARCHAR(255) REFERENCES students(username) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS communitytopics (
    community_topic_id    SERIAL PRIMARY KEY,
    community_topic_name  VARCHAR(255) NOT NULL,
    community_subject_id  INTEGER REFERENCES communitysubjects(community_subject_id) ON DELETE CASCADE,
    uploader_username     VARCHAR(255) REFERENCES students(username) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS communityflashcards (
    community_flashcard_id  SERIAL PRIMARY KEY,
    community_topic_id      INTEGER NOT NULL REFERENCES communitytopics(community_topic_id) ON DELETE CASCADE,
    front                   TEXT NOT NULL,
    back                    TEXT NOT NULL
);
