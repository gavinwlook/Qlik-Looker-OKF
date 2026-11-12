"""
Upstream dbt / BigQuery SQL Blueprint Generator
===============================================
Translates Qlik Load Script ETL transformations (RESIDENT, LEFT JOIN, APPLYMAP)
flagged in the Canonical IR into upstream SQL models for modern cloud data warehouses.

Consumes ONLY the Canonical IR dictionary.
"""

from typing import Any, Dict, List


class DbtBlueprintCompiler:
    """Generates dbt model SQL and schema.yml blueprints for Qlik ETL load scripts."""

    def compile_blueprints(self, canonical_ir: Dict[str, Any]) -> Dict[str, str]:
        """
        Generates dbt SQL models for tables that require upstream transformations.
        Returns: { filename: sql_content }
        """
        data_layer = canonical_ir.get("data_layer", {})
        tables = data_layer.get("tables", [])
        relationships = data_layer.get("relationships", [])

        blueprints: Dict[str, str] = {}

        for tbl in tables:
            tname = tbl.get("name", "table")
            fields = tbl.get("fields", [])
            is_fact = tbl.get("is_fact", False)

            if is_fact:
                model_name = f"fct_{tname.lower()}"
                sql = self._generate_fact_dbt_sql(tname, fields, relationships)
                blueprints[f"{model_name}.sql"] = sql

        return blueprints

    def _generate_fact_dbt_sql(
        self,
        table_name: str,
        fields: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
    ) -> str:
        field_list = [f"    {f.get('name')}" for f in fields]
        select_clause = ",\n".join(field_list) if field_list else "    *"

        lines = [
            "{{ config(",
            "    materialized='table',",
            "    partition_by={'field': 'order_date', 'data_type': 'date'} if target.type == 'bigquery' else none",
            ") }}",
            "",
            f"-- Auto-generated dbt model replacing Qlik QVS Load Script for: {table_name}",
            "WITH source_data AS (",
            f"    SELECT * FROM {{{{ source('raw_data', '{table_name}') }}}}",
            "),",
            "",
            "transformed AS (",
            "    SELECT",
            select_clause,
            "    FROM source_data",
            ")",
            "",
            "SELECT * FROM transformed;",
        ]
        return "\n".join(lines)
