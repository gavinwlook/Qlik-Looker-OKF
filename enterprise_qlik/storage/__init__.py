"""
Application Database & State Storage Layer
==========================================
Provides persistence for tenant discovery, app catalog, Canonical IR caching,
3-Tier compatibility findings, Explore mappings, and batch migration jobs.
Supports embedded SQLite (WAL) and enterprise PostgreSQL.
"""

from enterprise_qlik.storage.db import DatabaseManager

__all__ = ["DatabaseManager"]
