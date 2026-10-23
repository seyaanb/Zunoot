"""Running under gunicorn --preload, as Render's native Python runtime does.

Render sets GUNICORN_CMD_ARGS="--preload --access-logfile - --bind=0.0.0.0:10000"
for Python services, and that overrides gunicorn.conf.py. These tests cover
the two ways preloading broke or endangered the app:

1. metrics defined before the multi-process directory existed (boot crash)
2. forked workers inheriting the master's pooled database connection
"""

import importlib.util
import os
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]


def _load_gunicorn_conf():
    """Execute gunicorn.conf.py as gunicorn's master would.

    Loading it sets environment variables (PROMETHEUS_MULTIPROC_DIR and a reset
    marker). Those are restored afterwards so they can't leak into other tests:
    with PROMETHEUS_MULTIPROC_DIR left set, /metrics would read from the
    multi-process files instead of this process's in-memory registry.
    """
    saved = dict(os.environ)
    try:
        spec = importlib.util.spec_from_file_location("zunoot_gunicorn_conf", REPO / "gunicorn.conf.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_metrics_import_creates_a_missing_multiproc_dir(tmp_path):
    """The crash: PROMETHEUS_MULTIPROC_DIR set, directory missing, metrics imported."""
    target = tmp_path / "does" / "not" / "exist"
    env = dict(os.environ, PROMETHEUS_MULTIPROC_DIR=str(target))
    result = subprocess.run(
        [sys.executable, "-c", "import observability.metrics"],
        cwd=REPO, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert target.is_dir()
    assert any(p.name.startswith("gauge_livesum_") for p in target.iterdir())


def test_config_load_clears_stale_files_once_per_master(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    monkeypatch.delenv("ZUNOOT_METRICS_DIR_RESET_BY", raising=False)
    (tmp_path / "counter_99999.db").write_bytes(b"stale")
    _load_gunicorn_conf()
    assert not (tmp_path / "counter_99999.db").exists()

    # A config reload (SIGHUP) in the same master must not delete live files.
    # The first load recorded this master's PID; simulate that persisting.
    monkeypatch.setenv("ZUNOOT_METRICS_DIR_RESET_BY", str(os.getpid()))
    (tmp_path / "counter_12345.db").write_bytes(b"live worker")
    _load_gunicorn_conf()
    assert (tmp_path / "counter_12345.db").exists()


def test_on_starting_keeps_files_a_preloaded_app_wrote(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    conf = _load_gunicorn_conf()
    (tmp_path / "gauge_max_1.db").write_bytes(b"written by the preloaded master")
    conf.on_starting(server=None)
    assert (tmp_path / "gauge_max_1.db").exists()


def _backend_pid(app_module):
    with app_module.app.app_context():
        with app_module.db.engine.connect() as conn:
            return conn.exec_driver_sql("select pg_backend_pid()").scalar()


def _pooled_backend_pids(app_module):
    """Backend PIDs of every connection idle in the parent's pool (app.py's
    import-time setup can leave more than one)."""
    with app_module.app.app_context():
        engine = app_module.db.engine
        conns = [engine.connect() for _ in range(max(engine.pool.checkedin(), 1))]
        try:
            return {c.exec_driver_sql("select pg_backend_pid()").scalar() for c in conns}
        finally:
            for c in conns:
                c.close()


def _backend_pid_in_child(app_module, run_post_fork):
    """Fork like gunicorn does; return the Postgres backend PID the child uses."""
    conf = _load_gunicorn_conf()
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:  # child
        try:
            os.close(read_fd)
            if run_post_fork:
                conf.post_fork(server=None, worker=None)
            os.write(write_fd, str(_backend_pid(app_module)).encode())
        finally:
            os._exit(0)
    os.close(write_fd)
    os.waitpid(pid, 0)
    with os.fdopen(read_fd) as f:
        return int(f.read())


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs fork()")
def test_forked_workers_get_their_own_database_connection(app):
    import app as app_module

    _backend_pid(app_module)  # make sure the pool holds at least one idle connection
    parent = _pooled_backend_pids(app_module)

    # Without the hook the child reuses one of the parent's sockets: the danger is real.
    assert _backend_pid_in_child(app_module, run_post_fork=False) in parent
    # With gunicorn.conf.py's post_fork, the child opens its own connection...
    assert _backend_pid_in_child(app_module, run_post_fork=True) not in parent
    # ...and the parent's connections are untouched.
    assert _pooled_backend_pids(app_module) == parent


# Without --preload, every gunicorn worker imports app.py at the same moment.
# Each process below is patched so SQLAlchemy's "does the table exist?" check
# sleeps for a second after answering: that widens the race window CI hit, and
# without the schema-setup lock in app.py, all processes then try CREATE TABLE.
_SLOW_CHECK_THEN_IMPORT = """
import time
import sqlalchemy.dialects.postgresql.base as pg
_orig = pg.PGDialect.has_table
def _slow(self, *a, **k):
    r = _orig(self, *a, **k)
    time.sleep(1.0)
    return r
pg.PGDialect.has_table = _slow
import app
"""


def test_workers_starting_together_on_a_fresh_database():
    from urllib.parse import urlparse, urlunparse

    import psycopg2

    from conftest import TEST_DATABASE_URL

    admin = psycopg2.connect(TEST_DATABASE_URL)
    admin.autocommit = True
    scratch = "zunoot_startup_race_test"
    with admin.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {scratch}")
        cur.execute(f"CREATE DATABASE {scratch}")
    url = urlunparse(urlparse(TEST_DATABASE_URL)._replace(path=f"/{scratch}"))
    try:
        env = dict(os.environ, DATABASE_URL=url, SECRET_KEY="test")
        env.pop("PROMETHEUS_MULTIPROC_DIR", None)
        procs = [subprocess.Popen([sys.executable, "-c", _SLOW_CHECK_THEN_IMPORT], cwd=REPO, env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                 for _ in range(3)]
        errors = [p.communicate(timeout=60)[1] for p in procs if p.wait(timeout=60) != 0]
        assert not errors, errors[0][-800:]
    finally:
        with admin.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {scratch} WITH (FORCE)")
        admin.close()
