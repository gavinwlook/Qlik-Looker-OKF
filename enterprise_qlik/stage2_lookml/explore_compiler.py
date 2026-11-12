"""
LookML Explore Compiler (Explore-Centric Modeling)
=================================================
Translates the Canonical IR Data Layer into production-ready LookML Explores:
- Single-view Explores (denormalized tables)
- Star / Snowflake Multi-view Explores (fact table base view with dimension joins)
- Supports pre-existing enterprise Explore mapping

Consumes ONLY the Canonical IR dictionary.
"""

from typing import Any, Dict, List, Optional


class ExploreCompiler:
    """Compiles the Data Layer of Canonical IR into LookML Explore definitions."""

    def __init__(self, model_name: str = "enterprise_analytics"):
        self.model_name = model_name

    def compile_explore(self, canonical_ir: Dict[str, Any], target_explore_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Compiles the primary Explore for the data model.
        Returns: {
            "explore_name": str,
            "root_view": str,
            "explore_lkml": str,
            "model_lkml": str,
            "is_single_view": bool,
            "joined_views": List[str]
        }
        """
        data_layer = canonical_ir.get("data_layer", {})
        tables = data_layer.get("tables", [])
        relationships = data_layer.get("relationships", [])

        if not tables:
            # Fallback for empty data model
            explore_name = target_explore_name or "default_explore"
            return {
                "explore_name": explore_name,
                "root_view": explore_name,
                "explore_lkml": f"explore: {explore_name} {{\n  label: \"Default Explore\"\n}}\n",
                "model_lkml": f"connection: \"analytics_dw\"\n\ninclude: \"/views/*.view.lkml\"\n\nexplore: {explore_name} {{\n}}\n",
                "is_single_view": True,
                "joined_views": [],
            }

        # 1. Identify Root Fact View
        fact_tables = [t for t in tables if t.get("is_fact", False)]
        if fact_tables:
            root_table = max(fact_tables, key=lambda t: t.get("row_count", 0))
        else:
            root_table = max(tables, key=lambda t: t.get("row_count", 0))

        root_view_name = self._sanitize_identifier(root_table.get("name", "fact_data"))
        explore_name = target_explore_name or root_view_name

        # 2. Check if Single-View Explore
        is_single_view = len(tables) <= 1 or len(relationships) == 0
        joined_views: List[str] = []

        lines = [
            f"explore: {explore_name} {{",
            f'  label: "{canonical_ir.get("app_metadata", {}).get("app_name", explore_name)}"',
            f'  description: "Explore auto-generated from Canonical IR (Root view: {root_view_name})"',
            f"  view_name: {root_view_name}",
        ]

        # 3. Add Joins if Multi-View Star/Snowflake
        if not is_single_view:
            joined_set = set()
            for rel in relationships:
                from_tbl = self._sanitize_identifier(rel.get("from_table", ""))
                to_tbl = self._sanitize_identifier(rel.get("to_table", ""))
                from_fld = rel.get("from_field", "")
                to_fld = rel.get("to_field", "")

                # Join dimension to root fact
                if from_tbl == root_view_name and to_tbl not in joined_set and to_tbl != root_view_name:
                    joined_set.add(to_tbl)
                    joined_views.append(to_tbl)
                    lines.append("")
                    lines.append(f"  join: {to_tbl} {{")
                    lines.append("    type: left_outer")
                    lines.append("    relationship: many_to_one")
                    lines.append(f"    sql_on: ${{{root_view_name}.{self._sanitize_identifier(from_fld)}}} = ${{{to_tbl}.{self._sanitize_identifier(to_fld)}}} ;;")
                    lines.append("  }")
                elif to_tbl == root_view_name and from_tbl not in joined_set and from_tbl != root_view_name:
                    joined_set.add(from_tbl)
                    joined_views.append(from_tbl)
                    lines.append("")
                    lines.append(f"  join: {from_tbl} {{")
                    lines.append("    type: left_outer")
                    lines.append("    relationship: many_to_one")
                    lines.append(f"    sql_on: ${{{root_view_name}.{self._sanitize_identifier(to_fld)}}} = ${{{from_tbl}.{self._sanitize_identifier(from_fld)}}} ;;")
                    lines.append("  }")

        lines.append("}\n")
        explore_lkml = "\n".join(lines)

        # Build companion model file
        model_lines = [
            f'connection: "analytics_warehouse"',
            "",
            'include: "/views/*.view.lkml"',
            'include: "/dashboards/*.dashboard.lookml"',
            "",
            explore_lkml,
        ]
        model_lkml = "\n".join(model_lines)

        return {
            "explore_name": explore_name,
            "root_view": root_view_name,
            "explore_lkml": explore_lkml,
            "model_lkml": model_lkml,
            "is_single_view": is_single_view,
            "joined_views": joined_views,
        }

    def _sanitize_identifier(self, name: str) -> str:
        """Converts table or field name to clean LookML identifier."""
        import re
        s = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip().lower())
        return re.sub(r"_+", "_", s).strip("_")
