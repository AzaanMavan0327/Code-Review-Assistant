# Code Review Assistant - GitHub Action container.
#
# Packages the static analyzer, LLM enrichment, and PR comment poster
# into a single container that GitHub Actions invokes whenever a pull
# request is opened or updated.
#
# Design goals:
#   - Small image size: smaller container starts faster on every PR.
#   - Reproducible builds: dependencies are pinned in requirements.txt.
#   - Cached layers: copy requirements.txt before src/, so changing
#     source code doesn't invalidate the pip install layer.

# Start from the slim variant of Python 3.11. The slim image is about
# 50 MB vs ~120 MB for the full image, and it includes everything our
# pure-Python dependencies need.
FROM python:3.11-slim

# Disable output buffering. Without this, log lines from the action
# may appear in the Actions UI seconds late or completely out of order.
# Critical for debugging when something goes wrong.
ENV PYTHONUNBUFFERED=1

# All subsequent commands run from /app inside the container.
WORKDIR /app

# Copy requirements.txt and install dependencies BEFORE copying the
# source code. Docker caches each layer; this ordering means changing
# a Python file doesn't trigger a full re-install of pip packages.
# --no-cache-dir keeps the image small by not saving the pip cache.
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir -r requirements.txt

# Now copy the actual source code. Changes here only invalidate this
# layer and below, not the pip install layer above.
COPY src/ ./src/

# When GitHub Actions runs the container, it invokes the runner module.
# GitHub provides GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_EVENT_PATH,
# and GITHUB_EVENT_NAME automatically, plus any declared inputs as
# INPUT_<NAME> env vars.
ENTRYPOINT ["python", "-m", "src.action.runner"]