"""The directory prometheus_client's multi-process mode writes to.

Kept free of prometheus_client imports: gunicorn's master loads it from
gunicorn.conf.py before anything defines a metric.

Two rules, and why:

1. The directory must exist before the first metric is defined. With
   PROMETHEUS_MULTIPROC_DIR set, defining a Gauge immediately opens
   <dir>/gauge_<mode>_<pid>.db, and a missing directory raises
   FileNotFoundError at import time. ensure_dir() is called at the top of
   observability/metrics.py, so this holds however the app is started.

2. Stale files are cleared once per server start, by the gunicorn master,
   before it imports the app (gunicorn.conf.py runs before --preload does).
   Workers must never clear the directory: they would delete their siblings'
   live files. Files left by a previous run would otherwise be merged into
   the new run's counters.
"""

import glob
import os

ENV_VAR = "PROMETHEUS_MULTIPROC_DIR"
DEFAULT_DIR = "/tmp/zunoot-prometheus"
_RESET_MARKER = "ZUNOOT_METRICS_DIR_RESET_BY"


def ensure_dir():
    """Create the multi-process directory if multi-process mode is on."""
    path = os.environ.get(ENV_VAR)
    if path:
        os.makedirs(path, exist_ok=True)
    return path


def reset_once_per_master():
    """Empty the directory (keeping it) once per gunicorn master process.

    gunicorn re-reads its config file on SIGHUP while workers are still
    running. The marker records which master already reset the directory, so
    a reload never wipes live workers' files.
    """
    path = ensure_dir()
    if not path or os.environ.get(_RESET_MARKER) == str(os.getpid()):
        return
    for stale in glob.glob(os.path.join(path, "*.db")):
        try:
            os.remove(stale)
        except FileNotFoundError:
            pass
    os.environ[_RESET_MARKER] = str(os.getpid())
