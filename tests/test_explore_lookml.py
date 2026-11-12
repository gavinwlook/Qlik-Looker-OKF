import unittest
from enterprise_qlik.stage1_extract.extractor import QIXExtractor
from enterprise_qlik.stage1_extract.ir_compiler import CanonicalIRCompiler
from enterprise_qlik.stage2_lookml.generator import LookMLGenerator

class TestExploreLookMLModeling(unittest.TestCase):
    def setUp(self):
        extractor = QIXExtractor(host="http://localhost:4848")
        compiler = CanonicalIRCompiler(include_compatibility=True)
        raw = extractor.build_sample_enterprise_app("Enterprise Test App")
        self.canonical_ir = compiler.compile(raw)
        self.generator = LookMLGenerator(model_name="finance_analytics")

    def test_explore_centric_generation(self):
        artifacts = self.generator.generate(self.canonical_ir)

        # 1. Verify Explore Generation
        explores = artifacts["explores"]
        self.assertGreater(len(explores), 0)
        explore_key = list(explores.keys())[0]
        explore_content = explores[explore_key]

        # Must declare an explore block
        self.assertIn("explore: order_details", explore_content)
        # Must declare root fact view
        self.assertIn("view_name: order_details", explore_content)
        # Must declare joins to dimension views
        self.assertIn("join: products", explore_content)
        self.assertIn("relationship: many_to_one", explore_content)
        self.assertIn("type: left_outer", explore_content)

        # 2. Verify Dashboard Generation binds strictly to EXPLORE
        dashboards = artifacts["dashboards"]
        self.assertGreater(len(dashboards), 0)
        dash_key = list(dashboards.keys())[0]
        dash_content = dashboards[dash_key]

        self.assertIn("layout: newspaper", dash_content)
        self.assertIn("model: finance_analytics", dash_content)
        # CRITICAL TEST: Dashboard tile MUST reference the Explore, not a View!
        self.assertIn("explore: order_details", dash_content)
        # Fields must be qualified with view identifier
        self.assertIn("order_details.", dash_content)

        # 3. Verify Views Generation
        views = artifacts["views"]
        self.assertGreater(len(views), 0)
        self.assertIn("order_details.view.lkml", views)
        fact_view = views["order_details.view.lkml"]
        self.assertIn("view: order_details {", fact_view)
        # Verify What-If parameter exists
        self.assertIn("parameter: vdiscountrate", fact_view)

        # 4. Verify dbt models
        dbt = artifacts["dbt_models"]
        self.assertIn("fct_order_details.sql", dbt)

    def test_single_view_explore_when_single_table(self):
        single_table_ir = {
            "ir_version": "2.0",
            "contract_type": "OPEN_CANONICAL_IR",
            "app_metadata": {"app_id": "single_tbl_01", "app_name": "Single View App"},
            "data_layer": {
                "tables": [{
                    "name": "wide_transactions",
                    "is_fact": True,
                    "row_count": 1000,
                    "fields": [{"name": "id", "data_type": "string", "is_primary_key": True}]
                }],
                "relationships": [],
                "master_dimensions": [],
                "master_measures": [],
                "variables": []
            },
            "visual_catalog": {"sheets": []}
        }
        artifacts = self.generator.generate(single_table_ir)
        explores = artifacts["explores"]
        self.assertIn("wide_transactions.explore.lkml", explores)
        content = explores["wide_transactions.explore.lkml"]
        self.assertIn("explore: wide_transactions", content)
        self.assertNotIn("join:", content) # No joins for single view explore

if __name__ == "__main__":
    unittest.main()
