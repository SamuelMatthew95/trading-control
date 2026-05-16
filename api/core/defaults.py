"""Default payload sentinels.

Re-exports the default constants from ``api/constants.py`` so missing-data
defaults are imported from one well-named place. Use these instead of bare
``""`` so absent data stays visible rather than silently blank.
"""

from __future__ import annotations

from api.constants import (
    DEFAULT_AGENT_ID,
    DEFAULT_MSG_ID,
    DEFAULT_TRACE_ID,
    EMPTY_STRING,
    UNKNOWN_VALUE,
)

__all__ = [
    "DEFAULT_AGENT_ID",
    "DEFAULT_MSG_ID",
    "DEFAULT_TRACE_ID",
    "EMPTY_STRING",
    "UNKNOWN_VALUE",
]
