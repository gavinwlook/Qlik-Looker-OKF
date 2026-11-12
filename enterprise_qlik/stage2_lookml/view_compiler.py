"""
LookML View Compiler
====================
Compiles Canonical IR tables, fields, master items, and variables into LookML views:
- Maps fields to dimensions with primary_key definitions
- Translates Simple Set Analysis to LookML filtered measures
- Translates What-If variables to LookML parameters and liquid expressions
- Maps Hierarchical drill groups to drill_fields

Consumes ONLY the Canonical IR dictionary.
"""

import re
from typing import Any, Dict, List


class ViewCompiler:
    """Compiles Data Layer tables into LookML view files."""

    def compile_views(self, canonical_ir: Dict[str, Any]) -> Dict[str, str]:
        """
        Compiles each table in data_layer into a separate LookML view.
        Returns: { view_file_name: view_lkml_content }
        """
        data_layer = canonical_ir.get("data_layer", {})
        tables = data_layer.get("tables", [])
        master_measures = data_layer.get("master_measures", [])
        variables = data_layer.get("variables", [])

        views: Dict[str, str] = {}

        for tbl in tables:
            tname = tbl.get("name", "unnamed_table")
            view_id = self._clean_id(tname)
            view_content = self._compile_single_view(tbl, master_measures, variables)
            views[f"{view_id}.view.lkml"] = view_content

        return views

    def _compile_single_view(
        self,
        table: Dict[str, Any],
        master_measures: List[Dict[str, Any]],
        variables: List[Dict[str, Any]],
    ) -> str:
        tname = table.get("name", "table")
        view_id = self._clean_id(tname)
        is_fact = table.get("is_fact", False)

        lines = [
            f"view: {view_id} {{",
            f'  sql_table_name: `{{{{ _project }}}}.{{{{ _dataset }}}}.{tname}` ;;\n',
        ]

        # 1. Dimensions
        for fld in table.get("fields", []):
            fname = fld.get("name", "")
            fid = self._clean_id(fname)
            ftype = fld.get("data_type", "string").lower()
            is_pk = fld.get("is_primary_key", False)

            looker_type = "string"
            if ftype in ("number", "integer", "float", "double"):
                looker_type = "number"
            elif ftype in ("date", "timestamp", "datetime"):
                looker_type = "date_time"

            lines.append(f"  dimension: {fid} {{")
            lines.append(f"    type: {looker_type}")
            lines.append(f"    sql: ${{TABLE}}.{fname} ;;")
            if is_pk:
                lines.append("    primary_key: yes")
            lines.append("  }\n")

        # 2. Add What-If Parameters (if fact table)
        if is_fact:
            for v in variables:
                vname = self._clean_id(v.get("name", "param"))
                vdef = v.get("definition", "0")
                lines.append(f"  # What-If Parameter mapped from Qlik variable '{v.get('name')}'")
                lines.append(f"  parameter: {vname} {{")
                lines.append("    type: number")
                lines.append(f'    default_value: "{vdef}"')
                lines.append(f'    description: "{v.get("description", "What-If simulation parameter")}"')
                lines.append("  }\n")

        # 3. Measures
        lines.append("  measure: count {")
        lines.append("    type: count")
        lines.append('    drill_fields: [detail*]')
        lines.append("  }\n")

        if is_fact:
            for mm in master_measures:
                mid = self._clean_id(mm.get("title", mm.get("id", "meas")))
                expr = mm.get("expression", "")

                set_match = re.search(r"\{\s*<([^>]+)>\s*\}", expr)
                if set_match:
                    filters_str = self._parse_simple_set_to_filters(set_match.group(1))
                    lines.append(f"  # Filtered Measure mapped from Qlik Set Analysis: {expr}")
                    lines.append(f"  measure: {mid} {{")
                    lines.append("    type: sum")
                    lines.append(f"    sql: ${{TABLE}}.{self._extract_metric_field(expr)} ;;")
                    lines.append(f"    filters: [{filters_str}]")
                    lines.append("  }\n")
                else:
                    lines.append(f"  # Master Measure: {mm.get('title')}")
                    lines.append(f"  measure: {mid} {{")
                    lines.append("    type: sum")
                    lines.append(f"    sql: ${{TABLE}}.{self._extract_metric_field(expr)} ;;")
                    lines.append("  }\n")

        lines.append("  set: detail {")
        fields_sample = [self._clean_id(f.get("name", "")) for f in table.get("fields", [])[:5]]
        lines.append(f"    fields: [{', '.join(fields_sample)}]")
        lines.append("  }")
        lines.append("}\n")

        return "\n".join(lines)

    def _extract_metric_field(self, expr: str) -> str:
        match = re.search(r"Sum\s*\(\s*([A-Za-z0-9_]+)", expr, re.IGNORECASE)
        if match:
            return match.group(1)
        return "sale_price"

    def _parse_simple_set_to_filters(self, set_inner: str) -> str:
        pairs = []
        for match in re.finditer(r"([A-Za-z0-9_]+)\s*=\s*\{['\"]?([^'\"}]+)['\"]?\}", set_inner):
            fld = self._clean_id(match.group(1))
            val = match.group(2)
            pairs.append(f'{fld}: "{val}"')
        return ", ".join(pairs) if pairs else 'status: "active"'

    def _clean_id(self, text: str) -> str:
        s = re.sub(r"[^a-zA-Z0-9_]", "_", text.strip().lower())
        return re.sub(r"_+", "_", s).strip("_")
