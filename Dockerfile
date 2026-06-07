# Code Review Assistant - GitHub Action container.
#
# Packages the static analyzer, LLM enrichment, and PR comment poster
# into a single container that GitHub Actions invokes whenever a pull
# request is opened or updated.

# Slim Python 3.11. About 50 MB vs ~120 MB for the full image.
FROM python:3.11-slim

# Disable output buffering so log lines appear in the Actions UI
# immediately rather than seconds late.
ENV PYTHONUNBUFFERED=1

# Tell Python to look for modules in /app, regardless of which directory
# the container's process happens to be running from. This matters because
# GitHub Actions overrides the working directory to /github/workspace
# when it starts the container — without PYTHONPATH, Python wouldn't find
# our `src` package.
ENV PYTHONPATH=/app

WORKDIR /app

# Install dependencies in a separate layer so changing source code
# doesn't invalidate the pip install cache.
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir -r requirements.txt

# Copy the application source.
COPY src/ ./src/

# When GitHub Actions runs the container, invoke the runner module.
# PYTHONPATH=/app (set above) ensures Python finds src.action.runner
# even if the working directory is /github/workspace.
ENTRYPOINT ["python", "-m", "src.action.runner"]