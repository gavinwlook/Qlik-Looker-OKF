import os
import shutil
import tempfile
import time
import unittest

from enterprise_qlik.okf.frontmatter import (
    concept_slug,
    merge_okf_reextraction,
    parse_okf_document,
    serialize_okf_document,
)
from enterprise_qlik.okf.validator import validate_okf_catalog, validate_okf_document
from enterprise_qlik.stage1_extract.extractor import QIXExtractor
from enterprise_qlik.stage1_extract.ir_compiler import CanonicalIRCompiler
from enterprise_qlik.stage2_lookml.generator import LookMLGenerator
from enterprise_qlik.storage.db import DatabaseManager


class TestOKFArchitecture(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_okf_")
        self.db_path = os.path.join(self.temp_dir, "test_okf.db")
        self.catalog_dir = os.path.join(self.temp_dir, "okf_catalog")
        self.db = DatabaseManager(db_path=self.db_path, okf_catalog_dir=self.catalog_dir)
        self.extractor = QIXExtractor(host="http://localhost:4848")
        self.compiler = CanonicalIRCompiler(include_compatibility=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_adr02_concept_slug_prevents_collisions_and_long_paths(self):
        long_qlik_name = "% YoY Gross Margin Growth (Excl. Intercompany & FX - EMEA/APAC) [v2]"
        slug = concept_slug(long_qlik_name, max_len=32)
        self.assertLessEqual(len(slug), 39)  # 32 chars + '_' + 6-char hash
        self.assertRegex(slug, r"^[a-z0-9_]+$")

    def test_adr03_zero_dependency_frontmatter_handles_complex_qlik_set_analysis(self):
        complex_expr = 'Sum({$<[Order:Status]={\'Paid\'}, Year={"$(=Max(Year)-1)"}>} [Net # Sales])'
        fm = {
            "okf_version": "0.2",
            "type": "metric",
            "title": "Prior Year Net Sales",
            "status": "active",
            "extracted": {
                "qlik_expression": complex_expr,
                "compatibility_category": 2,
            },
            "governance": {
                "lookml_measure_name": "prior_year_net_sales",
            },
        }
        doc = serialize_okf_document(
            frontmatter=fm,
            curated_notes="Consolidated across 18 regional sales apps.",
            auto_catalog="```qlik\n" + complex_expr + "\n```",
        )
        is_valid, errs = validate_okf_document("metrics/prior_year_net_sales.md", doc)
        self.assertTrue(is_valid, f"OKF validation failed: {errs}")

        parsed = parse_okf_document(doc)
        self.assertEqual(parsed["extracted"]["qlik_expression"], complex_expr)
        self.assertEqual(parsed["governance"]["lookml_measure_name"], "prior_year_net_sales")
        self.assertIn("Consolidated across 18 regional sales apps.", parsed["curated_notes"])

    def test_adr04_and_adr05_zero_drift_sync_and_dual_namespace_preservation(self):
        raw = self.extractor.build_sample_enterprise_app("EMEA Commercial Sales")
        ir = self.compiler.compile(raw)
        self.db.save_canonical_ir("app_emea_01", ir, raw)

        # Verify write-through to disk OKF catalog
        summary = self.db.get_okf_catalog_summary()
        self.assertTrue(summary["is_valid"], f"Catalog invalid: {summary['validation_errors']}")
        self.assertGreaterEqual(summary["counts"]["apps"], 1)
        self.assertGreaterEqual(summary["counts"]["tables"], 3)

        # Assign wave and lead via DB -> verify written through to `apps/app_emea_01.md` on disk
        self.db.assign_wave(["app_emea_01"], wave="wave1", lead="Sarah Chen")
        concept = self.db.get_okf_concept("apps/app_emea_01.md")
        self.assertIsNotNone(concept)
        self.assertEqual(concept["governance"]["migration_wave"], "wave1")
        self.assertEqual(concept["governance"]["assigned_lead"], "Sarah Chen")

        # Update curated notes via API method with optimistic concurrency SHA-256
        updated = self.db.update_okf_concept(
            concept_path="apps/app_emea_01.md",
            governance_updates={"bound_explore": "explores/canonical_order_details"},
            curated_notes="Custom architect note: mapped to canonical_order_details.",
            expected_sha256=concept["content_sha256"],
        )
        self.assertEqual(updated["governance"]["bound_explore"], "explores/canonical_order_details")

        # Verify stale SHA-256 raises optimistic concurrency error
        with self.assertRaises(ValueError):
            self.db.update_okf_concept(
                concept_path="apps/app_emea_01.md",
                curated_notes="Stale edit",
                expected_sha256="0000000000000000",
            )

        # Re-extract Stage 1 -> verify `governance:` and `curated_notes` are strictly preserved!
        self.db.save_canonical_ir("app_emea_01", ir, raw)
        after_reextract = self.db.get_okf_concept("apps/app_emea_01.md")
        self.assertEqual(after_reextract["governance"]["migration_wave"], "wave1")
        self.assertEqual(after_reextract["governance"]["assigned_lead"], "Sarah Chen")
        self.assertEqual(after_reextract["governance"]["bound_explore"], "explores/canonical_order_details")
        self.assertIn("Custom architect note: mapped to canonical_order_details.", after_reextract["curated_notes"])

    def test_stage15_fleet_reconciliation_and_stage2_canonical_explore_compilation(self):
        # Extract 3 regional Qlik apps built on overlapping underlying tables
        for idx, region in enumerate(["EMEA", "AMER", "APAC"], start=1):
            raw = self.extractor.build_sample_enterprise_app(f"{region} Commercial Analytics")
            ir = self.compiler.compile(raw)
            self.db.save_canonical_ir(f"app_reg_{idx}", ir, raw)

        # Run Stage 1.5 Fleet Reconciliation
        rec = self.db.reconcile_fleet_okf(similarity_threshold=0.45)
        self.assertEqual(rec["status"], "SUCCESS")
        self.assertEqual(rec["total_apps_reconciled"], 3)
        self.assertEqual(rec["canonical_explores_count"], 1)
        self.assertEqual(rec["duplicate_explores_eliminated"], 2)
        self.assertGreater(rec["saved_cat2_effort_hours"], 0.0)

        # Run Stage 2 Fleet LookML Compilation from the OKF catalog
        generator = LookMLGenerator(model_name="global_commerce")
        artifacts = generator.generate_from_okf_catalog(self.catalog_dir)
        self.assertEqual(artifacts["metadata"]["total_canonical_explores"], 1)
        self.assertEqual(artifacts["metadata"]["total_apps_compiled"], 3)
        self.assertGreaterEqual(len(artifacts["views"]), 5)
        self.assertGreaterEqual(len(artifacts["dashboards"]), 4)


if __name__ == "__main__":
    unittest.main()
