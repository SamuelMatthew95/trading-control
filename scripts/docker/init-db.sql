-- Executed once by the postgres container on first boot
-- (mounted into /docker-entrypoint-initdb.d/ by docker-compose.yml).
-- The app's Alembic migrations assume the pgvector extension exists.
CREATE EXTENSION IF NOT EXISTS vector;
