"""Guardrail: no production module may import ``declarative_base`` from the
deprecated ``sqlalchemy.ext.declarative`` path.

SQLAlchemy 2.0 moved ``declarative_base`` to ``sqlalchemy.orm``; the old path
emits ``MovedIn20Warning`` and is slated for removal. This source-text scan
fails CI if the deprecated import is reintroduced anywhere under ``api/``.

Regression for: ``api/core/models/base.py`` importing
``from sqlalchemy.ext.declarative import declarative_base``.
"""

from __future__ import annotations

from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2] / "api"
DEPRECATED_IMPORT = "from sqlalchemy.ext.declarative import declarative_base"


def test_no_deprecated_declarative_base_import() -> None:
    offenders = [
        str(path.relative_to(API_ROOT.parent))
        for path in API_ROOT.rglob("*.py")
        if DEPRECATED_IMPORT in path.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        "Deprecated SQLAlchemy import found — use "
        "`from sqlalchemy.orm import declarative_base` instead: " + ", ".join(offenders)
    )
