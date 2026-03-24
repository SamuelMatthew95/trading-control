#!/bin/bash
set -e

# Only run if explicitly enabled
if [ "$RUN_DB_HOTFIX" != "true" ]; then
    echo "Database hotfix disabled — skipping"
    exit 0
fi

echo "Running one-time database hotfix"

# Run Alembic migrations (including hotfix migration)
python -m alembic upgrade head

echo "Hotfix migration complete"
