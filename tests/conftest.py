"""Test fixtures.

The suite runs against a real PostgreSQL database (the app uses raw psycopg2,
so SQLite or mocks would not exercise the real queries). Every test session
drops and recreates the public schema, so there is a hard guard below: the
target database name must end in "_test" and the host must be local. This
makes it impossible to point the suite at Neon/production by accident.
"""

import os
from urllib.parse import urlparse

import psycopg2
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TEST_DB = "postgresql://postgres:postgres@localhost:5432/zunoot_test"
SAFE_HOSTS = {"localhost", "127.0.0.1", "::1", "db", "postgres"}

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DB)


def _assert_safe_target(url):
    parsed = urlparse(url)
    dbname = parsed.path.lstrip("/")
    if parsed.hostname not in SAFE_HOSTS or not dbname.endswith("_test"):
        raise RuntimeError(
            f"Refusing to run tests against {parsed.hostname}/{dbname}: tests "
            "drop the schema. Use a local database whose name ends in _test."
        )


_assert_safe_target(TEST_DATABASE_URL)

# app.py reads config and touches the DB at import time, so the environment
# must be set before anything imports it.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("METRICS_TOKEN", "test-metrics-token")
os.environ.pop("FLASK_ENV", None)

APP_TABLES = [
    "communityflashcards", "communitytopics", "communitysubjects",
    "flashcards", "topics", "subjects", "guildrequests", "purchases",
    "guilds", "students",
]


def _run_sql_file(cur, name):
    with open(os.path.join(REPO_ROOT, "db", name)) as f:
        cur.execute(f.read())


def _reset_schema():
    conn = psycopg2.connect(TEST_DATABASE_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        _run_sql_file(cur, "schema.sql")
        _run_sql_file(cur, "seed_dev.sql")
    conn.close()


_reset_schema()


@pytest.fixture(scope="session")
def app():
    from app import app as flask_app

    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return flask_app


@pytest.fixture(autouse=True)
def clean_db(app):  # depends on app: importing it creates the sessions table
    """Empty user data between tests; keep reference data (shop, pointsreset)."""
    yield
    conn = psycopg2.connect(TEST_DATABASE_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE {', '.join(APP_TABLES)} RESTART IDENTITY CASCADE")
        cur.execute("DELETE FROM sessions")  # Flask-Session's table
    conn.close()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_cursor():
    conn = psycopg2.connect(TEST_DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    yield cur
    conn.close()


def register(client, username="alice", password="password123"):
    return client.post("/auth/register", data={
        "username": username, "first-name": "Test", "last-name": "User",
        "email": f"{username}@example.com", "password": password,
    })


def login(client, username="alice", password="password123"):
    return client.post("/auth/login", data={"username": username, "password": password})


@pytest.fixture
def logged_in(client):
    register(client)
    login(client)
    return client
