# Container image for the HTTP transport (see README "Remote / hosted").
#
# The stdio transport does not need this -- for a local vault, a client launches
# the server directly. This exists so the same server can be reached at a URL.
FROM python:3.12-slim

# Never write .pyc files or buffer stdout: in a container both just cost you
# clarity when reading logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependency metadata first, so a code-only change reuses the cached pip layer.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir ".[http]"

# The notes that get served. Swap this for your own folder (and mind that
# anything copied in here is readable by whoever can reach the URL).
COPY demo-notes/ ./demo-notes/

# Run as a non-root user: this process reads a notes folder and speaks HTTP, so
# it has no business owning the filesystem it runs on.
RUN useradd --create-home --shell /usr/sbin/nologin notes \
    && chown -R notes:notes /app
USER notes

ENV MCP_TRANSPORT=http \
    NOTES_DIR=/app/demo-notes \
    HOST=0.0.0.0 \
    PORT=8000

# No auth credential is baked in on purpose. Supply NOTES_URL_SECRET or
# NOTES_TOKEN at deploy time; with neither, the server refuses to start rather
# than publishing the notes folder to anyone who finds the URL.

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT','8000')}/healthz\", timeout=4).status==200 else 1)"

CMD ["python", "-m", "notes_mcp.server"]
