FROM python:3.13-slim-bookworm

WORKDIR /app

# Install ffmpeg and git (for yt-dlp updates if needed)
# We also need to install dependencies for playwright if we don't use the 'playwright install-deps' command
# But 'playwright install --with-deps' is easier.
RUN apt-get update && \
    apt-get install -y ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install Deno
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

# Install dependencies
COPY pyproject.toml uv.lock ./
RUN UV_PROJECT_ENVIRONMENT=/usr/local uv sync --frozen --no-dev --compile-bytecode

# Install Playwright browsers and dependencies
# We need to run this after installing the python package 'playwright' which is in the dependencies
RUN uv run playwright install --with-deps chromium

COPY . .

ENV FLASK_APP=run.py
ENV FLASK_ENV=production

EXPOSE 5000

COPY scripts/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

CMD ["/app/entrypoint.sh"]
