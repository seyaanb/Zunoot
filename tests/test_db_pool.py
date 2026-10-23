"""Connection pool behaviour (backend/db_pool.py)."""

import threading
import time

import psycopg2
import pytest
from prometheus_client import REGISTRY

from backend import db_pool
from backend import queries as q


@pytest.fixture(autouse=True)
def fresh_pool():
    db_pool.reset()
    yield
    db_pool.reset()


def connects():
    return REGISTRY.get_sample_value("zunoot_db_connect_duration_seconds_count") or 0


def test_connections_are_reused():
    before = connects()
    for _ in range(20):
        conn = q.database()
        with conn.cursor() as cur:
            cur.execute("select 1")
        conn.close()
    assert connects() - before == 1


def test_close_rolls_back_uncommitted_work():
    conn = q.database()
    cur = conn.cursor()
    cur.execute("insert into students(username, first_name, last_name, password, email_address)"
                " values ('ghost','a','b','x','g@e.com')")
    conn.close()  # no commit
    conn = q.database()
    cur = conn.cursor()
    cur.execute("select count(*) from students where username = 'ghost'")
    assert cur.fetchone()[0] == 0
    import psycopg2.extensions as ext
    assert conn.get_transaction_status() in (ext.TRANSACTION_STATUS_IDLE, ext.TRANSACTION_STATUS_INTRANS)
    conn.close()


def test_released_handle_reports_closed_and_refuses_use():
    conn = q.database()
    conn.close()
    assert conn.closed
    with pytest.raises(psycopg2.InterfaceError):
        conn.cursor()


def test_broken_connections_are_discarded():
    conn = q.database()
    raw = conn._conn
    raw.close()           # simulate the server dropping it
    conn.close()
    conn2 = q.database()
    assert conn2._conn is not raw and not conn2.closed
    conn2.close()


def test_stale_idle_connections_are_not_reused(monkeypatch):
    monkeypatch.setenv("DB_POOL_MAX_IDLE", "0.05")
    db_pool.reset()
    conn = q.database()
    raw = conn._conn
    conn.close()
    time.sleep(0.1)
    conn2 = q.database()
    assert conn2._conn is not raw and raw.closed
    conn2.close()


def test_pool_is_bounded_and_waits(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "2")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "0.2")
    db_pool.reset()
    a, b = q.database(), q.database()
    with pytest.raises(db_pool.PoolTimeout):
        q.database()
    # a waiter gets the connection as soon as one is returned
    got = []
    t = threading.Thread(target=lambda: got.append(q.database()))
    monkeypatch.setenv("DB_POOL_TIMEOUT", "2")
    db_pool._pool._timeout = 2
    t.start()
    time.sleep(0.05)
    a.close()
    t.join(1)
    assert got and not got[0].closed
    for c in (b, got[0]):
        c.close()


def test_forgotten_close_does_not_leak_a_slot(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "1")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "0.5")
    db_pool.reset()

    def leaky():
        conn = q.database()
        conn.cursor().execute("select 1")  # never closed

    leaky()
    conn = q.database()  # would time out if the slot leaked
    conn.close()


def test_kill_switch_disables_pooling(monkeypatch):
    monkeypatch.setenv("DB_POOL", "0")
    before = connects()
    for _ in range(3):
        q.database().close()
    assert connects() - before == 3


def test_app_flow_uses_far_fewer_connections(logged_in):
    for name in ("A", "B", "C"):
        logged_in.post("/library/", data={"new-subject": name})
        logged_in.post(f"/library/{name}", data={"new-topic": "T1"})
        logged_in.post(f"/library/{name}", data={"new-topic": "T2"})
    before = connects()
    for _ in range(5):
        assert logged_in.get("/library/").status_code == 200
    # 5 library views = 5 x (1 + 3 + 6) queries; before pooling, ~50 connections
    assert connects() - before <= 2
