"""Centralized payload-key names.

``PayloadKey`` is the canonical ``FieldName`` enum, re-exported under the
name the hardening guidelines reference. It is deliberately an alias — not a
second list of strings — so there is exactly one source of truth and no
producer/consumer drift.
"""

from __future__ import annotations

from api.constants import FieldName

PayloadKey = FieldName

__all__ = ["PayloadKey"]
