#!/bin/bash
set -e

# Run migrations
echo "Running database migrations..."
uv run flask db upgrade

# Start Gunicorn
echo "Starting Gunicorn..."
exec gunicorn -w 4 -b 0.0.0.0:5000 run:app
