"""
Stage 2: Target Code Generation (Explore-First LookML & dbt Modeling)
====================================================================
Completely decoupled downstream consumer that reads ONLY the open Canonical IR.
Generates:
- LookML Explores (Single-view or Multi-view star/snowflake join graphs)
- LookML Views (Dimensions, Measures, Derived Tables, Parameters)
- LookML Dashboards (Tiles bound strictly to Explores with qualified fields)
- Upstream dbt / BigQuery SQL model blueprints

ZERO imports from Stage 1 or Qlik.
"""

from enterprise_qlik.stage2_lookml.generator import LookMLGenerator

__all__ = ["LookMLGenerator"]
