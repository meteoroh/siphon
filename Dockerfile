FROM python:3.11-slim

WORKDIR /app

# Install ffmpeg and git (for yt-dlp updates if needed)
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

COPY . .

ENV FLASK_APP=run.py
ENV FLASK_ENV=production

EXPOSE 5000

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "run:app"]
