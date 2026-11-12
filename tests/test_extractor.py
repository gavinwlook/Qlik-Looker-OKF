import unittest
from enterprise_qlik.stage1_extract.extractor import QIXExtractor
from enterprise_qlik.stage1_extract.ir_compiler import CanonicalIRCompiler
from enterprise_qlik.stage1_extract.schema_validator import validate_canonical_ir


class TestExtractorSheetEnumeration(unittest.TestCase):
    def setUp(self):
        self.extractor = QIXExtractor(host="http://localhost:4848")
        self.compiler = CanonicalIRCompiler(include_compatibility=True)

    def test_multi_source_sheet_lifecycle_compilation(self):
        """Verify that public/approved sheets and private/My own sheets are cleanly compiled and distinguished."""
        raw_metadata = {
            "app_id": "test-app-001",
            "app_name": "Spark Electronics - Sales Dashboard",
            "stream_or_space": "Trial",
            "space_type": "shared",
            "data_model": {
                "load_script": "LOAD 1 as id AUTOGENERATE 1;",
                "tables": [
                    {
                        "name": "Sales",
                        "fields": [
                            {"name": "id", "data_type": "INTEGER", "is_primary_key": True},
                            {"name": "amount", "data_type": "FLOAT", "is_primary_key": False}
                        ],
                        "keys": ["id"],
                        "row_count": 100
                    }
                ]
            },
            "sheets": [
                {
                    "id": "dRKtK",
                    "sheet_id": "dRKtK",
                    "title": "Sales Dashboard",
                    "description": "Main corporate sales dashboard",
                    "section": "Public",
                    "sheet_lifecycle": "approved",
                    "publication_status": "published",
                    "is_approved": True,
                    "is_published": True,
                    "widgets": [
                        {
                            "id": "w1",
                            "title": "Monthly Revenue Trend",
                            "type": "linechart",
                            "col": 0, "row": 0, "width": 12, "height": 6,
                            "dimensions": [{"field": "Month", "label": "Month"}],
                            "measures": [{"expression": "Sum(amount)", "label": "Revenue"}]
                        }
                    ]
                },
                {
                    "id": "sh_private_1",
                    "sheet_id": "sh_private_1",
                    "title": "Looker-Gap Advanced Innovations: Control...",
                    "description": "Personal sandbox sheet",
                    "section": "My own",
                    "sheet_lifecycle": "my_own",
                    "publication_status": "unpublished",
                    "is_approved": False,
                    "is_published": False,
                    "widgets": [
                        {
                            "id": "w2",
                            "title": "Control Chart",
                            "type": "barchart",
                            "col": 0, "row": 0, "width": 6, "height": 4,
                            "dimensions": [{"field": "id", "label": "ID"}],
                            "measures": [{"expression": "Count(id)", "label": "Count"}]
                        }
                    ]
                },
                {
                    "id": "sh_private_2",
                    "sheet_id": "sh_private_2",
                    "title": "Executive Sales Analytics",
                    "description": "Custom executive cut",
                    "section": "My own",
                    "sheet_lifecycle": "my_own",
                    "publication_status": "unpublished",
                    "is_approved": False,
                    "is_published": False,
                    "widgets": []
                },
                {
                    "id": "sh_private_3",
                    "sheet_id": "sh_private_3",
                    "title": "Executive Sales Analytics",
                    "description": "Duplicate iteration",
                    "section": "My own",
                    "sheet_lifecycle": "my_own",
                    "publication_status": "unpublished",
                    "is_approved": False,
                    "is_published": False,
                    "widgets": []
                },
                {
                    "id": "sh_private_4",
                    "sheet_id": "sh_private_4",
                    "title": "Sales Dashboard (1)",
                    "description": "Private copy of main sales dashboard",
                    "section": "My own",
                    "sheet_lifecycle": "my_own",
                    "publication_status": "unpublished",
                    "is_approved": False,
                    "is_published": False,
                    "widgets": []
                }
            ]
        }

        canonical_ir = self.compiler.compile(raw_metadata)
        sheets = canonical_ir["visual_catalog"]["sheets"]
        self.assertEqual(len(sheets), 5)

        # Verify Public sheet
        public_sheets = [s for s in sheets if s["section"] == "Public" or s["sheet_lifecycle"] == "approved"]
        self.assertEqual(len(public_sheets), 1)
        self.assertEqual(public_sheets[0]["title"], "Sales Dashboard")
        self.assertTrue(public_sheets[0]["is_approved"])
        self.assertEqual(public_sheets[0]["publication_status"], "published")

        # Verify My Own sheets
        my_own_sheets = [s for s in sheets if s["section"] == "My own" or s["sheet_lifecycle"] == "my_own"]
        self.assertEqual(len(my_own_sheets), 4)
        titles = [s["title"] for s in my_own_sheets]
        self.assertIn("Looker-Gap Advanced Innovations: Control...", titles)
        self.assertIn("Sales Dashboard (1)", titles)
        self.assertEqual(titles.count("Executive Sales Analytics"), 2)

        for s in my_own_sheets:
            self.assertFalse(s["is_approved"])
            self.assertEqual(s["sheet_lifecycle"], "my_own")

        is_valid, errors = validate_canonical_ir(canonical_ir)
        self.assertTrue(is_valid, f"Validation failed: {errors}")


if __name__ == "__main__":
    unittest.main()
