-- docker-compose only: a separate database for the test suite, so running the
-- tests (which reset the schema) never touches the local dev data.
CREATE DATABASE zunoot_test;
