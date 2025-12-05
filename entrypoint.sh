#!/bin/bash
set -e

# Initialize database if it doesn't exist or run migrations
# For a simple app, we can just upgrade. If it's a fresh start, 'flask db upgrade' 
# might fail if migrations folder exists but DB is empty? 
# Actually, flask db upgrade is usually safe.
# But if migrations folder is missing, we might need 'flask db init' etc.
# Assuming migrations folder is committed in repo.

echo "Running database migrations..."
uv run flask db upgrade

# Start the application
echo "Starting Siphon..."
exec "$@"
