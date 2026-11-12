"""
Qlik-to-Looker OKF v0.2 Fleet Migration & Consolidation Engine
==============================================================
A modular, 3-stage enterprise migration framework built on the Open Knowledge Format (OKF v0.2):
- Stage 1: QIX Engine Extraction, PII Sanitization, 3-Tier Compatibility Auditing, and Coarse-Grained OKF v0.2 Concept Emission.
- Stage 1.5: Fleet Semantic Reconciliation & Canonical Looker Explore Consolidation across 500+ Qlik Apps (`okf_catalog/`).
- Stage 2: Decoupled Target Code Generation (Shared LookML Views, Consolidated Explores, Re-bound Dashboards, and dbt models).
- Storage: Dual-Namespace (`extracted:` vs `governance:`) OKF disk storage with nanosecond `os.scandir()` SQLite WAL write-through index.
"""

__version__ = "3.0.0"
__author__ = "Gavin W"
