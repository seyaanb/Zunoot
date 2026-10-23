"""A small, Neon-aware connection pool for backend/queries.py.

Before: queries.database() opened a new Postgres connection for every query
(TCP + TLS + SCRAM authentication to Neon) and closed it again. A library page
for a mid-sized library opened ~17 of them. This pool keeps a few connections
per worker process and hands them out instead.

It is deliberately transparent: queries.py still calls database() and
conn.close(); close() now returns the connection to the pool instead of
disconnecting. No query function had to change.

Design choices:
- Bounded per process (DB_POOL_SIZE, default 8). gunicorn runs WEB_CONCURRENCY
  workers x GUNICORN_THREADS threads, and a few query functions hold one
  connection while calling another, so size >= 2 x threads. Total connections
  to Neon = workers x size (16 by default), well under Neon's limit.
- Waits up to DB_POOL_TIMEOUT seconds for a free connection rather than failing
  instantly (psycopg2's ThreadedConnectionPool raises PoolError when exhausted).
- Idle connections are closed after DB_POOL_MAX_IDLE seconds (default 120),
  by a background reaper. This avoids handing out connections the server has
  silently dropped, and doesn't keep connections open through quiet periods.
  Neon scales compute to zero after 5 idle minutes.
- Every connection is rolled back when returned, so no transaction, lock or
  snapshot survives into the next request. That matches the old behaviour,
  where closing the connection rolled back implicitly.
- Broken connections (server closed them) are discarded, never reused.
- Fork-safe: created lazily per process (gunicorn workers fork after import).
- Kill switch: DB_POOL=0 restores the old connect-per-query behaviour.
"""

import os
import threading
import time

import psycopg2
import psycopg2.extensions

from observability import db as obs_db


class PoolTimeout(Exception):
    pass


class PooledConnection:
    """Behaves like a psycopg2 connection; close() hands it back to the pool."""

    __slots__ = ("_conn", "_pool", "_released")

    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool
        self._released = False

    def __getattr__(self, name):
        if self._released:
            raise psycopg2.InterfaceError("connection already returned to the pool")
        return getattr(self._conn, name)

    @property
    def closed(self):
        # From the caller's point of view the handle is closed once returned.
        return 1 if self._released else self._conn.closed

    def close(self):
        if not self._released:
            self._released = True
            self._pool.release(self._conn)

    def __del__(self):
        # A caller that forgot close() (or raised before it) must not leak the
        # pool slot forever.
        try:
            self.close()
        except Exception:
            pass


class Pool:
    def __init__(self, dsn, size=8, timeout=10.0, max_idle=120.0):
        self._dsn = dsn
        self._timeout = timeout
        self._max_idle = max_idle
        self._idle = []                       # LIFO stack of (conn, returned_at)
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(size)
        self._stop = threading.Event()
        reaper = threading.Thread(target=self._reap_forever, name="db-pool-reaper", daemon=True)
        reaper.start()

    def acquire(self):
        if not self._slots.acquire(timeout=self._timeout):
            raise PoolTimeout(f"no database connection free within {self._timeout}s")
        try:
            while True:
                with self._lock:
                    item = self._idle.pop() if self._idle else None
                if item is None:
                    return PooledConnection(obs_db.connect(self._dsn), self)
                conn, returned_at = item
                if conn.closed or time.monotonic() - returned_at > self._max_idle:
                    _close_quietly(conn)
                    continue
                return PooledConnection(conn, self)
        except BaseException:
            self._slots.release()
            raise

    def release(self, conn):
        try:
            if conn.closed:
                return
            if conn.get_transaction_status() != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                conn.rollback()
            with self._lock:
                self._idle.append((conn, time.monotonic()))
        except Exception:
            _close_quietly(conn)  # unusable: drop it, a new one is made on demand
        finally:
            self._slots.release()

    def idle_count(self):
        with self._lock:
            return len(self._idle)

    def prune(self):
        cutoff = time.monotonic() - self._max_idle
        with self._lock:
            stale = [c for c, t in self._idle if t < cutoff or c.closed]
            self._idle = [(c, t) for c, t in self._idle if t >= cutoff and not c.closed]
        for conn in stale:
            _close_quietly(conn)

    def close_all(self):
        self._stop.set()
        with self._lock:
            idle, self._idle = self._idle, []
        for conn, _ in idle:
            _close_quietly(conn)

    def _reap_forever(self):
        while not self._stop.wait(min(30.0, self._max_idle / 2)):
            self.prune()


def _close_quietly(conn):
    try:
        conn.close()
    except Exception:
        pass


_pool = None
_pool_pid = None
_pool_lock = threading.Lock()


def get_connection(dsn):
    """Return a pooled connection (or a plain one if DB_POOL=0)."""
    if os.environ.get("DB_POOL", "1") == "0":
        return obs_db.connect(dsn)
    global _pool, _pool_pid
    if _pool is None or _pool_pid != os.getpid():
        with _pool_lock:
            if _pool is None or _pool_pid != os.getpid():
                _pool = Pool(
                    dsn,
                    size=int(os.environ.get("DB_POOL_SIZE", "8")),
                    timeout=float(os.environ.get("DB_POOL_TIMEOUT", "10")),
                    max_idle=float(os.environ.get("DB_POOL_MAX_IDLE", "120")),
                )
                _pool_pid = os.getpid()
    return _pool.acquire()


def reset():
    """Close everything (tests, and anything that changes DATABASE_URL at runtime)."""
    global _pool, _pool_pid
    with _pool_lock:
        if _pool is not None:
            _pool.close_all()
        _pool, _pool_pid = None, None
