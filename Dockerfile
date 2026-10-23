# syntax=docker/dockerfile:1
#
# Production image for Zunoot.
#  - multi-stage: build tools never reach the runtime image
#  - slim Debian base (glibc, so psycopg2-binary / greenlet wheels just work;
#    Alpine's musl would force compiling them from source)
#  - runs as an unprivileged user with a read-only app directory
#  - gunicorn (config in gunicorn.conf.py) as PID 1's child via tini, so
#    SIGTERM from Render reaches gunicorn and in-flight requests drain

ARG PYTHON_VERSION=3.13

# ---------------------------------------------------------------- builder ---
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt .
RUN pip install -r requirements.txt

# ---------------------------------------------------------------- runtime ---
FROM python:${PYTHON_VERSION}-slim AS runtime

# tini: minimal init that forwards signals and reaps zombies.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 zunoot \
    && useradd --system --uid 10001 --gid zunoot --no-create-home --shell /usr/sbin/nologin zunoot

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000 \
    FLASK_ENV=production

WORKDIR /app
# Owned by root, read-only to the app user: a compromised process can't
# rewrite its own code. Only /tmp is writable.
COPY --chown=root:root . .

ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}
LABEL org.opencontainers.image.source="https://github.com/seyaanb/zunoot" \
      org.opencontainers.image.revision="${GIT_SHA}"

# numeric UID so Kubernetes-style runAsNonRoot checks can verify it
USER 10001:10001
EXPOSE 10000

# Used by docker-compose / local runs. Render uses its own health check
# (healthCheckPath in render.yaml), which hits the same endpoint.
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '10000') + '/livez', timeout=2)"]

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
