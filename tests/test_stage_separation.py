import sys
import unittest
import json
import tempfile
import os

class TestStageSeparation(unittest.TestCase):
    def test_stage2_isolated_execution(self):
        # Sample standalone Canonical IR JSON (no Qlik code or models needed)
        standalone_ir = {
            "ir_version": "2.0",
            "contract_type": "OPEN_CANONICAL_IR",
            "app_metadata": {
                "app_id": "isolated_app_123",
                "app_name": "Isolated Banking App",
                "source_engine": "Generic BI",
                "sanitized": True
            },
            "data_layer": {
                "tables": [
                    {
                        "name": "fct_loans",
                        "is_fact": True,
                        "row_count": 50000,
                        "fields": [
                            {"name": "loan_id", "data_type": "string", "is_primary_key": True},
                            {"name": "customer_id", "data_type": "string"},
                            {"name": "loan_amount", "data_type": "number"}
                        ],
                        "keys": [{"key_field": "customer_id", "target_tables": ["dim_borrowers"]}]
                    },
                    {
                        "name": "dim_borrowers",
                        "is_fact": False,
                        "row_count": 10000,
                        "fields": [
                            {"name": "customer_id", "data_type": "string", "is_primary_key": True},
                            {"name": "credit_rating", "data_type": "string"}
                        ],
                        "keys": [{"key_field": "customer_id", "target_tables": ["fct_loans"]}]
                    }
                ],
                "relationships": [
                    {
                        "from_table": "fct_loans",
                        "to_table": "dim_borrowers",
                        "from_field": "customer_id",
                        "to_field": "customer_id",
                        "join_type": "left_outer",
                        "relationship": "many_to_one"
                    }
                ],
                "master_dimensions": [],
                "master_measures": [
                    {
                        "id": "meas_total_loans",
                        "title": "Total Loans",
                        "expression": "Sum(loan_amount)"
                    }
                ],
                "variables": []
            },
            "visual_catalog": {
                "sheets": [
                    {
                        "sheet_id": "sheet_loans",
                        "title": "Loan Portfolio Summary",
                        "grid_columns": 12,
                        "widgets": [
                            {
                                "widget_id": "kpi_total",
                                "title": "Total Volume",
                                "type": "single_value",
                                "layout": {"looker_col": 0, "looker_row": 0, "looker_width": 6, "looker_height": 3},
                                "measures": [{"label": "Total Loans", "expression": "Sum(loan_amount)"}]
                            },
                            {
                                "widget_id": "bar_rating",
                                "title": "Volume by Credit Rating",
                                "type": "looker_column",
                                "layout": {"looker_col": 6, "looker_row": 0, "looker_width": 6, "looker_height": 6},
                                "dimensions": [{"field": "credit_rating", "table": "dim_borrowers"}],
                                "measures": [{"label": "Total Loans", "expression": "Sum(loan_amount)"}]
                            }
                        ]
                    }
                ]
            }
        }

        # Ensure Stage 1 modules are NOT loaded prior to Stage 2 import
        stage1_modules = [m for m in sys.modules if "stage1_extract" in m]
        for m in stage1_modules:
            del sys.modules[m]

        # Import ONLY Stage 2
        from enterprise_qlik.stage2_lookml.generator import LookMLGenerator

        # Verify Stage 1 is still NOT imported by Stage 2
        self.assertFalse(any("stage1_extract" in m for m in sys.modules))

        # Run Stage 2 generation
        generator = LookMLGenerator(model_name="banking_analytics")
        artifacts = generator.generate(standalone_ir)

        # Assert successful target artifacts created from standalone contract
        self.assertIn("banking_analytics.model.lkml", artifacts["model"])
        self.assertIn("fct_loans.explore.lkml", artifacts["explores"])
        self.assertIn("loan_portfolio_summary.dashboard.lookml", artifacts["dashboards"])

        # Check explore binding in dashboard
        dash = artifacts["dashboards"]["loan_portfolio_summary.dashboard.lookml"]
        self.assertIn("explore: fct_loans", dash)
        self.assertIn("fct_loans.", dash)

if __name__ == "__main__":
    unittest.main()
