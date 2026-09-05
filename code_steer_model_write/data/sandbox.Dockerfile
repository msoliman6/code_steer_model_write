# The runtime's sandbox image (ARCHITECTURE.md 7.6): what a code check needs and nothing else.
# Built once by `csmw sandbox build`; every check of a run executes in a container from it,
# network off, the run folder the only mount, under the host user's uid.
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends git libatomic1 \
    && rm -rf /var/lib/apt/lists/*
# pyright's node comes from the wheel and its version is pinned, so no run needs a home
# directory or the network (with "latest" it phoned npm on every call and timed out offline)
ENV PYRIGHT_PYTHON_FORCE_VERSION=1.1.411 PYRIGHT_PYTHON_IGNORE_WARNINGS=1
RUN pip install --no-cache-dir "pytest>=8" "ruff>=0.6" "pyright[nodejs]==1.1.411" \
    && echo 'x: int = 1' > /tmp/probe.py && pyright /tmp/probe.py && rm /tmp/probe.py
ENV HOME=/tmp PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /work
