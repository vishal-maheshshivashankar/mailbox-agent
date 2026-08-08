# Single-process image: `mailbox-agent-serve` runs the scheduler (sort loop
# + retention sweep) and the Telegram approval listener together. No second
# service needed - SQLite is a file on a mounted volume, not a server. See
# docs/ARCHITECTURE.md section 11 for the deployment picture.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

# Production image: no [dev] extras (pytest/ruff/mypy) - keeps the image
# smaller and free of tooling that has no job at runtime.
RUN pip install --no-cache-dir .

# Runtime state (SQLite DBs, OAuth tokens) lives on mounted volumes, not
# baked into the image - see docker-compose.yml.
RUN mkdir -p /app/data /app/secrets/tokens \
    && useradd --create-home --uid 1000 agent \
    && chown -R agent:agent /app
USER agent

VOLUME ["/app/data", "/app/secrets"]

CMD ["mailbox-agent-serve"]
