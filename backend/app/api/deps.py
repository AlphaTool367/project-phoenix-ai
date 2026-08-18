"""Shared API dependencies."""
from __future__ import annotations

from ..database import SessionLocal


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
