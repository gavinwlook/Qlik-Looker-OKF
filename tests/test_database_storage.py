import unittest
import os
import shutil
import tempfile
from enterprise_qlik.storage.db import DatabaseManager

class TestDatabaseStorage(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.db = DatabaseManager(db_path=self.temp_db.name)

    def tearDown(self):
        if os.path.exists(self.temp_db.name):
            os.remove(self.temp_db.name)
        if hasattr(self, "db") and os.path.exists(self.db.okf_catalog_dir):
            shutil.rmtree(self.db.okf_catalog_dir, ignore_errors=True)

    def test_app_lifecycle_and_ir_cache(self):
        # 1. Upsert App
        self.db.upsert_app(
            app_id="app_test_99",
            name="Treasury Risk Analytics",
            stream_or_space="Finance",
            extraction_status="DISCOVERED"
        )
        app = self.db.get_app("app_test_99")
        self.assertIsNotNone(app)
        self.assertEqual(app["name"], "Treasury Risk Analytics")

        # 2. Save Canonical IR
        sample_ir = {
            "ir_version": "2.0",
            "contract_type": "OPEN_CANONICAL_IR",
            "app_metadata": {"app_id": "app_test_99", "app_name": "Treasury Risk Analytics"},
            "data_layer": {"tables": [{"name": "positions", "fields": []}]},
            "visual_catalog": {"sheets": [{"sheet_id": "s1", "widgets": []}]}
        }
        self.db.save_canonical_ir("app_test_99", sample_ir)

        # 3. Retrieve Canonical IR
        retrieved_ir = self.db.get_canonical_ir("app_test_99")
        self.assertIsNotNone(retrieved_ir)
        self.assertEqual(retrieved_ir["ir_version"], "2.0")
        self.assertEqual(len(retrieved_ir["data_layer"]["tables"]), 1)

        # 4. Save and Retrieve Compatibility Findings
        findings = [
            {"category": 1, "severity": "LOW", "item_type": "SIMPLE_SET_ANALYSIS", "title": "Simple Set", "lookml_template": "filters: []"},
            {"category": 3, "severity": "CRITICAL", "item_type": "CYCLIC_DATA_MODEL", "title": "Loop", "lookml_template": "# ERROR"}
        ]
        self.db.save_compatibility_findings("app_test_99", findings)
        retrieved_findings = self.db.get_compatibility_findings("app_test_99")
        self.assertEqual(len(retrieved_findings), 2)
        # Verify ordering (category ASC, severity DESC)
        self.assertEqual(retrieved_findings[0]["category"], 1)
        self.assertEqual(retrieved_findings[1]["category"], 3)

        # 5. Job Queue
        job_id = self.db.create_job("app_test_99", "EXTRACT")
        self.db.update_job(job_id, status="COMPLETED", progress_pct=100)

    def test_leads_roster_crud_and_orphaned_assignment(self):
        # 1. Verify default seeded roster
        initial_leads = self.db.get_leads()
        self.assertGreaterEqual(len(initial_leads), 6)
        lead_names = {l["name"] for l in initial_leads}
        self.assertIn("Gavin Looker", lead_names)
        self.assertIn("Autonomous AI Migration Agent", lead_names)

        # 2. Create custom lead
        new_lead = self.db.create_lead(
            name="Alice Walker",
            email="alice.walker@enterprise.com",
            role="Senior Analytics Engineer",
            specialty="dbt Models & Data Modeling",
        )
        self.assertIsNotNone(new_lead)
        self.assertEqual(new_lead["name"], "Alice Walker")
        self.assertEqual(new_lead["role"], "Senior Analytics Engineer")
        self.assertEqual(new_lead["specialty"], "dbt Models & Data Modeling")

        # 3. Assign app to this lead and verify active app count
        self.db.upsert_app(
            app_id="app_lead_test_1",
            name="Lead Test App",
            stream_or_space="Finance",
            extraction_status="DISCOVERED",
            assigned_lead="Alice Walker",
        )
        fetched = self.db.get_lead(new_lead["lead_id"])
        self.assertEqual(fetched["active_apps_count"], 1)

        # 4. Update lead name and verify cascading update to assigned apps
        updated = self.db.update_lead(new_lead["lead_id"], name="Alice B. Walker")
        self.assertEqual(updated["name"], "Alice B. Walker")
        app = self.db.get_app("app_lead_test_1")
        self.assertEqual(app["assigned_lead"], "Alice B. Walker")

        # 5. Delete lead and verify assigned apps safely revert to Unassigned
        deleted = self.db.delete_lead(new_lead["lead_id"])
        self.assertTrue(deleted)
        self.assertIsNone(self.db.get_lead(new_lead["lead_id"]))
        reverted_app = self.db.get_app("app_lead_test_1")
        self.assertEqual(reverted_app["assigned_lead"], "Unassigned")

    def test_policies_and_portfolio_export(self):
        # 1. Default seeded policies
        policies = self.db.get_policies()
        self.assertGreaterEqual(len(policies), 5)
        # Check priority order
        priorities = [p["priority"] for p in policies]
        self.assertEqual(priorities, sorted(priorities))

        # Check default policy names
        policy_names = [p["name"] for p in policies]
        self.assertIn("Sandbox & Prototype Retirement", policy_names)
        self.assertIn("High-Complexity & Multi-Fact Models", policy_names)
        self.assertIn("Rapid Proof-of-Value / Quick Wins", policy_names)

        # 2. Create custom policy rule
        custom_rule = self.db.save_policy(
            name="Retail Priority Pilot",
            conditions={"name_keywords": ["retail"], "space_types": ["managed"]},
            actions={"target_wave": "wave1", "target_lead": "Elena Rostova"},
            priority=1,
            description="Prioritize retail apps to Wave 1",
        )
        self.assertIsNotNone(custom_rule)
        self.assertEqual(custom_rule["name"], "Retail Priority Pilot")
        self.assertEqual(custom_rule["priority"], 1)

        # 3. Simulate policies on test applications
        self.db.upsert_app(
            app_id="app_sandbox_1",
            name="Personal Scratchpad dev",
            stream_or_space="Personal",
            space_type="personal",
            sheet_count=2,
            widget_count=10,
        )
        self.db.upsert_app(
            app_id="app_complex_1",
            name="Global Wealth Risk Hub",
            stream_or_space="Finance",
            space_type="managed",
            sheet_count=9,
            widget_count=55,
        )
        self.db.upsert_app(
            app_id="app_quick_1",
            name="Executive KPI Card",
            stream_or_space="Sales",
            space_type="managed",
            sheet_count=3,
            widget_count=15,
        )

        sim = self.db.simulate_policies(app_ids=["app_sandbox_1", "app_complex_1", "app_quick_1"])
        self.assertEqual(sim["summary"]["total_apps"], 3)
        res_map = {r["app_id"]: r for r in sim["results"]}

        # Sandbox app should be recommended for decommissioned
        self.assertEqual(res_map["app_sandbox_1"]["proposed_wave"], "decommissioned")
        self.assertEqual(res_map["app_sandbox_1"]["proposed_lead"], "Unassigned")

        # Complex risk app should be Wave 3 assigned to Gavin Looker
        self.assertEqual(res_map["app_complex_1"]["proposed_wave"], "wave3")
        self.assertEqual(res_map["app_complex_1"]["proposed_lead"], "Gavin Looker")

        # Quick app (<=4 sheets) in managed space should be Wave 1 assigned to Autonomous AI
        self.assertEqual(res_map["app_quick_1"]["proposed_wave"], "wave1")
        self.assertEqual(res_map["app_quick_1"]["proposed_lead"], "Autonomous AI Migration Agent")

        # 4. Apply policies
        applied_res = self.db.apply_policies()
        self.assertEqual(applied_res["status"], "SUCCESS")
        self.assertGreaterEqual(applied_res["applied_count"], 3)

        # Verify persisted changes
        app_sandbox = self.db.get_app("app_sandbox_1")
        self.assertEqual(app_sandbox["migration_wave"], "decommissioned")
        self.assertEqual(app_sandbox["is_decommissioned"], 1)

        app_complex = self.db.get_app("app_complex_1")
        self.assertEqual(app_complex["migration_wave"], "wave3")
        self.assertEqual(app_complex["assigned_lead"], "Gavin Looker")

        # 5. Portfolio export data
        export_records = self.db.get_portfolio_export_data()
        self.assertGreaterEqual(len(export_records), 3)
        exp_map = {r["app_id"]: r for r in export_records}
        self.assertIn("app_complex_1", exp_map)
        r = exp_map["app_complex_1"]
        self.assertEqual(r["app_name"], "Global Wealth Risk Hub")
        self.assertEqual(r["migration_wave"], "wave3")
        self.assertEqual(r["wave_label"], "Wave 3: Complex Multi-Fact")
        self.assertEqual(r["assigned_lead"], "Gavin Looker")
        self.assertIn("Principal Data Architect", r["lead_role"])
        self.assertEqual(r["is_decommissioned"], "No")
        self.assertEqual(r["sheet_count"], 9)
        self.assertEqual(r["widget_count"], 55)

        # 6. Delete custom rule
        del_success = self.db.delete_policy(custom_rule["policy_id"])
        self.assertTrue(del_success)
        self.assertIsNone(self.db.get_policy(custom_rule["policy_id"]))

    def test_fleet_summary_semantic_savings_zero_and_multi_app(self):
        # 1. Empty database (0 apps)
        empty_summary = self.db.get_executive_metrics()
        savings_0 = empty_summary["semantic_savings"]
        self.assertEqual(savings_0["total_apps_analyzed"], 0)
        self.assertEqual(savings_0["clusters_identified"], 0)
        self.assertEqual(savings_0["models_consolidated"], 0)
        self.assertEqual(savings_0["estimated_hours_saved"], 0)

        # 2. Single app (no consolidation possible)
        self.db.upsert_app(
            app_id="app_single_1",
            name="Single App",
            stream_or_space="Finance",
            extraction_status="DISCOVERED",
            sheet_count=4,
        )
        single_summary = self.db.get_executive_metrics()
        savings_1 = single_summary["semantic_savings"]
        self.assertEqual(savings_1["total_apps_analyzed"], 1)
        self.assertEqual(savings_1["clusters_identified"], 0)
        self.assertEqual(savings_1["models_consolidated"], 0)
        self.assertEqual(savings_1["estimated_hours_saved"], 0)

        # 3. Two apps (1 model consolidated)
        self.db.upsert_app(
            app_id="app_single_2",
            name="Second App",
            stream_or_space="Finance",
            extraction_status="DISCOVERED",
            sheet_count=5,
        )
        two_summary = self.db.get_executive_metrics()
        savings_2 = two_summary["semantic_savings"]
        self.assertEqual(savings_2["total_apps_analyzed"], 2)
        self.assertEqual(savings_2["clusters_identified"], 1)
        self.assertEqual(savings_2["models_consolidated"], 1)
        self.assertGreaterEqual(savings_2["estimated_hours_saved"], 24)

        # 4. Three apps (2 clusters, 1 model consolidated: 3-2 = 1)
        self.db.upsert_app(
            app_id="app_single_3",
            name="Third App",
            stream_or_space="Sales",
            extraction_status="DISCOVERED",
            sheet_count=3,
        )
        three_summary = self.db.get_executive_metrics()
        savings_3 = three_summary["semantic_savings"]
        self.assertEqual(savings_3["total_apps_analyzed"], 3)
        self.assertEqual(savings_3["clusters_identified"], 2)
        self.assertEqual(savings_3["models_consolidated"], 1)

if __name__ == "__main__":
    unittest.main()
