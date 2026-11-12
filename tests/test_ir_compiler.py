import unittest
from enterprise_qlik.stage1_extract.extractor import QIXExtractor
from enterprise_qlik.stage1_extract.ir_compiler import CanonicalIRCompiler
from enterprise_qlik.stage1_extract.schema_validator import validate_canonical_ir

class TestCanonicalIRCompiler(unittest.TestCase):
    def setUp(self):
        self.extractor = QIXExtractor(host="http://localhost:4848")
        self.compiler = CanonicalIRCompiler(include_compatibility=True)

    def test_compile_sample_app_to_canonical_ir(self):
        raw = self.extractor.build_sample_enterprise_app("Enterprise Test App")
        canonical_ir = self.compiler.compile(raw)

        # 1. Verify Root Structure
        self.assertEqual(canonical_ir["ir_version"], "2.0")
        self.assertEqual(canonical_ir["contract_type"], "OPEN_CANONICAL_IR")
        self.assertEqual(canonical_ir["app_metadata"]["app_name"], "Enterprise Test App")

        # 2. Verify Tier 1: Data Layer
        dl = canonical_ir["data_layer"]
        self.assertIn("tables", dl)
        self.assertIn("relationships", dl)
        self.assertIn("master_dimensions", dl)
        self.assertIn("master_measures", dl)
        self.assertTrue(any(t["is_fact"] for t in dl["tables"]))
        self.assertGreater(len(dl["relationships"]), 0)

        # 3. Verify Tier 2: Visual Catalog
        vc = canonical_ir["visual_catalog"]
        self.assertIn("sheets", vc)
        sheet = vc["sheets"][0]
        self.assertEqual(sheet["grid_columns"], 24)
        widgets = sheet["widgets"]
        self.assertGreater(len(widgets), 0)

        # Check geometry normalization (must fit within 24 columns)
        for w in widgets:
            layout = w["layout"]
            self.assertGreaterEqual(layout["looker_col"], 0)
            self.assertLessEqual(layout["looker_col"] + layout["looker_width"], 24)

        # 4. Verify Open Schema Validation
        is_valid, errors = validate_canonical_ir(canonical_ir)
        self.assertTrue(is_valid, f"Canonical IR validation failed: {errors}")

    def test_compile_sample_app_multi_sheet(self):
        raw = self.extractor.build_sample_enterprise_app(app_name="Multi-Sheet Retail App")
        self.assertEqual(raw["app_name"], "Multi-Sheet Retail App")
        self.assertEqual(len(raw["sheets"]), 4)

        canonical_ir = self.compiler.compile(raw)
        sheets = canonical_ir["visual_catalog"]["sheets"]
        self.assertEqual(len(sheets), 4)

        total_widgets = sum(len(s["widgets"]) for s in sheets)
        self.assertEqual(total_widgets, 27)
        self.assertEqual(len(canonical_ir["data_layer"]["tables"]), 5)

        for sheet in sheets:
            self.assertEqual(sheet["grid_columns"], 24)
            for w in sheet["widgets"]:
                layout = w["layout"]
                self.assertGreaterEqual(layout["looker_col"], 0)
                self.assertLessEqual(layout["looker_col"] + layout["looker_width"], 24)

        is_valid, errors = validate_canonical_ir(canonical_ir)
        self.assertTrue(is_valid, f"Canonical IR validation failed: {errors}")

if __name__ == "__main__":
    unittest.main()
