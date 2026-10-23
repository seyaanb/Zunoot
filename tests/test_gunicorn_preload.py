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

    parent = _backend_pid(app_module)  # leaves a pooled connection, like app.py's create_all()

    # Without the hook the child reuses the parent's socket: proves the danger is real.
    assert _backend_pid_in_child(app_module, run_post_fork=False) == parent
    # With gunicorn.conf.py's post_fork, the child opens its own connection...
    assert _backend_pid_in_child(app_module, run_post_fork=True) != parent
    # ...and the parent's connection is still intact.
    assert _backend_pid(app_module) == parent
