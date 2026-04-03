"""Centralized version constants to avoid API/schema naming confusion.

Important:
- DASHBOARD_API_VERSION tracks route contract versions (`/dashboard_v2`).
- DB_SCHEMA_VERSION tracks persisted event/table payload schema version.
"""

DASHBOARD_API_VERSION = "v2"
DB_SCHEMA_VERSION = "v3"
ACCEPTED_DB_SCHEMA_VERSIONS = {DB_SCHEMA_VERSION, "legacy", None, ""}
