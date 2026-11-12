import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error

from enterprise_qlik.web.server import EnterpriseMigrationHandler, ThreadingHTTPServer
from enterprise_qlik.storage.db import DatabaseManager


class TestServerEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.temp_db.close()
        EnterpriseMigrationHandler.db = DatabaseManager(db_path=cls.temp_db.name)
        EnterpriseMigrationHandler.db.seed_default_instances()

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), EnterpriseMigrationHandler)
        cls.port = cls.httpd.server_port
        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}"

    def setUp(self):
        EnterpriseMigrationHandler.db.set_active_instance("inst-cloud-001")

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        if os.path.exists(cls.temp_db.name):
            os.remove(cls.temp_db.name)
        if hasattr(EnterpriseMigrationHandler.db, "okf_catalog_dir") and os.path.exists(EnterpriseMigrationHandler.db.okf_catalog_dir):
            shutil.rmtree(EnterpriseMigrationHandler.db.okf_catalog_dir, ignore_errors=True)

    def test_options_preflight(self):
        req = urllib.request.Request(f"{self.base_url}/api/instances/test", method="OPTIONS")
        with urllib.request.urlopen(req, timeout=3) as resp:
            self.assertEqual(resp.status, 204)
            headers = dict(resp.headers)
            self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")
            self.assertIn("POST", headers.get("Access-Control-Allow-Methods", ""))

    def test_get_instances(self):
        req = urllib.request.Request(f"{self.base_url}/api/instances")
        with urllib.request.urlopen(req, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("instances", data)
            self.assertGreaterEqual(len(data["instances"]), 2)
            self.assertIn("active_instance", data)
            self.assertIsNotNone(data["active_instance"])

    def test_get_instances_with_trailing_slash(self):
        req = urllib.request.Request(f"{self.base_url}/api/instances/")
        with urllib.request.urlopen(req, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("instances", data)

    def test_get_active_instance(self):
        req = urllib.request.Request(f"{self.base_url}/api/instances/active")
        with urllib.request.urlopen(req, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("active_instance", data)
            self.assertEqual(data["active_instance"]["tenant_id"], "inst-cloud-001")

    def test_post_instances_test(self):
        payload = json.dumps({
            "name": "Live Cloud Test",
            "environment_type": "cloud",
            "qlik_host": "https://tenant.eu.qlikcloud.com",
            "auth_config": {"api_key": "demo_eval_key"}
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/instances/test",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data.get("connected"))
            self.assertEqual(data.get("environment_type"), "cloud")

    def test_post_instances_test_trailing_slash(self):
        payload = json.dumps({
            "name": "Live Cloud Test",
            "environment_type": "cloud",
            "qlik_host": "https://tenant.eu.qlikcloud.com",
            "auth_config": {"api_key": "demo_eval_key"}
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/instances/test/",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data.get("connected"))

    def test_discover_fleet_apps(self):
        req = urllib.request.Request(
            f"{self.base_url}/api/instances/inst-cloud-001/discover",
            data=b"{}",
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "SUCCESS")
            self.assertGreaterEqual(data["discovered_count"], 1)

    def test_activate_instance(self):
        req = urllib.request.Request(
            f"{self.base_url}/api/instances/inst-onprem-002/activate",
            data=b"{}",
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ACTIVATED")

        # Verify active instance switched
        req_active = urllib.request.Request(f"{self.base_url}/api/instances/active")
        with urllib.request.urlopen(req_active, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["active_instance"]["tenant_id"], "inst-onprem-002")


    def test_run_server_port_in_use_graceful_exit(self):
        from enterprise_qlik.web.server import run_server
        import io
        import contextlib
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            run_server(port=self.port, db_path=self.temp_db.name, secondary_port=None)
        output = f.getvalue()
        self.assertIn("already in use", output)

    def test_get_executive_metrics(self):
        req = urllib.request.Request(f"{self.base_url}/api/fleet/executive")
        with urllib.request.urlopen(req, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("summary", data)
            self.assertIn("total_apps", data["summary"])
            self.assertIn("wave_distribution", data)
            self.assertIn("space_breakdown", data)
            self.assertIn("semantic_savings", data)

    def test_get_semantic_clusters(self):
        req = urllib.request.Request(f"{self.base_url}/api/fleet/clusters")
        with urllib.request.urlopen(req, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("clusters", data)
            self.assertIsInstance(data["clusters"], list)

    def test_get_and_assign_waves(self):
        # 1. Get initial waves
        req = urllib.request.Request(f"{self.base_url}/api/waves")
        with urllib.request.urlopen(req, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("waves", data)
            self.assertIn("columns", data)

        all_apps = []
        for w_apps in data["waves"].values():
            all_apps.extend(w_apps)
        target_app_id = all_apps[0]["app_id"] if all_apps else "f2aea43f-a85e-4a59-812b-0cd20ef34ba6"

        # 2. Assign an app to Wave 1 with a lead
        payload = json.dumps({
            "app_ids": [target_app_id],
            "wave": "wave1",
            "lead": "Alex Mercer",
            "lifecycle_stage": "ir_compiled"
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/waves/assign",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "SUCCESS")
            wave1_apps = [a["app_id"] for a in data["waves"]["waves"]["wave1"]]
            self.assertIn(target_app_id, wave1_apps)

    def test_batch_extract_and_decommission(self):
        # 1. Batch extract
        payload = json.dumps({
            "app_ids": ["f2aea43f-a85e-4a59-812b-0cd20ef34ba6"]
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/apps/batch_extract",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "SUCCESS")
            self.assertGreaterEqual(data["extracted_count"], 1)

        # 2. Decommission
        payload = json.dumps({
            "app_ids": ["f2aea43f-a85e-4a59-812b-0cd20ef34ba6"],
            "decommissioned": True
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/apps/decommission",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "SUCCESS")
            self.assertTrue(data["is_decommissioned"])

    def test_post_apps_register(self):
        payload = json.dumps({
            "name": "Executive Sales Content",
            "app_id": "05bdadd9-0358-4a45-a16f-fc30a8aa16ef",
            "stream_or_space": "Personal",
            "space_type": "personal",
            "tenant_id": "inst-cloud-001"
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/apps/register",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "SUCCESS")
            self.assertEqual(data["app"]["name"], "Executive Sales Content")
            self.assertEqual(data["app"]["app_id"], "05bdadd9-0358-4a45-a16f-fc30a8aa16ef")

        # Verify it appears in /api/apps
        req_apps = urllib.request.Request(f"{self.base_url}/api/apps")
        with urllib.request.urlopen(req_apps, timeout=3) as resp_a:
            apps_data = json.loads(resp_a.read().decode("utf-8"))
            names = [a["name"] for a in apps_data["apps"]]
            self.assertIn("Executive Sales Content", names)

    def test_discover_apps_includes_catalog_apps(self):
        req = urllib.request.Request(
            f"{self.base_url}/api/instances/inst-cloud-001/discover",
            data=b"{}",
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "SUCCESS")
            app_names = [a["name"] for a in data["apps"]]
            self.assertIn("Enterprise Sales & Margin (Sample)", app_names)
            self.assertIn("Spark Electronics - Sales Dashboard", app_names)

    def test_leads_endpoints_crud_and_wave_assignment(self):
        # 1. GET /api/leads
        req = urllib.request.Request(f"{self.base_url}/api/leads")
        with urllib.request.urlopen(req, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("leads", data)
            self.assertGreaterEqual(len(data["leads"]), 6)
            names = [l["name"] for l in data["leads"]]
            self.assertIn("Gavin Looker", names)
            self.assertIn("Autonomous AI Migration Agent", names)

        # 2. POST /api/leads - Create new lead
        payload = json.dumps({
            "name": "Robert Taylor",
            "email": "robert.taylor@enterprise.com",
            "role": "LookML Modeling Specialist",
            "specialty": "Liquid & Access Filters",
        }).encode("utf-8")
        req_create = urllib.request.Request(
            f"{self.base_url}/api/leads",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_create, timeout=3) as resp_c:
            self.assertEqual(resp_c.status, 200)
            c_data = json.loads(resp_c.read().decode("utf-8"))
            self.assertEqual(c_data["status"], "SUCCESS")
            lead = c_data["lead"]
            lead_id = lead["lead_id"]
            self.assertEqual(lead["name"], "Robert Taylor")
            self.assertEqual(lead["role"], "LookML Modeling Specialist")

        # 3. Assign app to this newly created lead via /api/waves/assign
        assign_payload = json.dumps({
            "app_ids": ["f2aea43f-a85e-4a59-812b-0cd20ef34ba6"],
            "lead": "Robert Taylor",
        }).encode("utf-8")
        req_assign = urllib.request.Request(
            f"{self.base_url}/api/waves/assign",
            data=assign_payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_assign, timeout=3) as resp_as:
            self.assertEqual(resp_as.status, 200)

        # 4. GET /api/leads/<id> - Verify assigned app count
        req_single = urllib.request.Request(f"{self.base_url}/api/leads/{lead_id}")
        with urllib.request.urlopen(req_single, timeout=3) as resp_s:
            self.assertEqual(resp_s.status, 200)
            s_data = json.loads(resp_s.read().decode("utf-8"))
            self.assertEqual(s_data["lead"]["active_apps_count"], 1)

        # 5. DELETE /api/leads/<id> - Delete lead
        req_del = urllib.request.Request(f"{self.base_url}/api/leads/{lead_id}", method="DELETE")
        with urllib.request.urlopen(req_del, timeout=3) as resp_d:
            self.assertEqual(resp_d.status, 200)
            d_data = json.loads(resp_d.read().decode("utf-8"))
            self.assertTrue(d_data["deleted"])

        # 6. Verify assigned app safely reset to Unassigned
        req_apps = urllib.request.Request(f"{self.base_url}/api/apps")
        with urllib.request.urlopen(req_apps, timeout=3) as resp_apps:
            apps_data = json.loads(resp_apps.read().decode("utf-8"))
            target_app = next(a for a in apps_data["apps"] if a["app_id"] == "f2aea43f-a85e-4a59-812b-0cd20ef34ba6")
            self.assertEqual(target_app["assigned_lead"], "Unassigned")

    def test_policies_and_portfolio_export_endpoints(self):
        # 1. GET /api/policies
        req_pol = urllib.request.Request(f"{self.base_url}/api/policies")
        with urllib.request.urlopen(req_pol, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("policies", data)
            self.assertGreaterEqual(len(data["policies"]), 5)

        # 2. POST /api/policies - Create custom rule
        create_payload = json.dumps({
            "name": "Integration Test Rule",
            "conditions": {"name_keywords": ["test"], "max_sheets": 5},
            "actions": {"target_wave": "wave1", "target_lead": "Marcus Vance"},
            "priority": 1,
            "description": "Rule created during API integration test",
        }).encode("utf-8")
        req_create = urllib.request.Request(
            f"{self.base_url}/api/policies",
            data=create_payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_create, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            c_data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(c_data["status"], "SUCCESS")
            created_policy = c_data["policy"]
            policy_id = created_policy["policy_id"]
            self.assertEqual(created_policy["name"], "Integration Test Rule")

        # 3. POST /api/policies/simulate
        sim_payload = json.dumps({}).encode("utf-8")
        req_sim = urllib.request.Request(
            f"{self.base_url}/api/policies/simulate",
            data=sim_payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_sim, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            s_data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("simulation", s_data)
            sim = s_data["simulation"]
            self.assertIn("summary", sim)
            self.assertIn("results", sim)
            self.assertGreaterEqual(sim["summary"]["total_apps"], 1)

        # 4. POST /api/policies/apply
        apply_payload = json.dumps({}).encode("utf-8")
        req_apply = urllib.request.Request(
            f"{self.base_url}/api/policies/apply",
            data=apply_payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_apply, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            a_data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(a_data["status"], "SUCCESS")
            self.assertIn("result", a_data)

        # 5. DELETE /api/policies/<id>
        req_del = urllib.request.Request(f"{self.base_url}/api/policies/{policy_id}", method="DELETE")
        with urllib.request.urlopen(req_del, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            del_data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(del_data["deleted"])

        # 6. GET /api/portfolio/export?format=csv
        req_csv = urllib.request.Request(f"{self.base_url}/api/portfolio/export?format=csv")
        with urllib.request.urlopen(req_csv, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            headers = dict(resp.headers)
            self.assertIn("text/csv", headers.get("Content-Type", ""))
            self.assertIn("attachment", headers.get("Content-Disposition", ""))
            self.assertIn(".csv", headers.get("Content-Disposition", ""))
            csv_text = resp.read().decode("utf-8")
            self.assertIn("Application Name", csv_text)
            self.assertIn("Migration Wave", csv_text)
            self.assertIn("Assigned Lead Owner", csv_text)
            self.assertIn("Sheet Count", csv_text)

        # 7. GET /api/portfolio/export?format=json
        req_json = urllib.request.Request(f"{self.base_url}/api/portfolio/export?format=json")
        with urllib.request.urlopen(req_json, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            headers = dict(resp.headers)
            self.assertIn("application/json", headers.get("Content-Type", ""))
            self.assertIn("attachment", headers.get("Content-Disposition", ""))
            self.assertIn(".json", headers.get("Content-Disposition", ""))
            json_data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(json_data["status"], "SUCCESS")
            self.assertIn("portfolio", json_data)
            self.assertGreaterEqual(json_data["total_applications"], 1)

    def test_stage1_extract_sample_app(self):
        sample_id = "sample-enterprise-001"
        payload = json.dumps({"app_id": sample_id, "use_sample": True, "app_name": "Sample Retail Analytics"}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/stage1/extract",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "SUCCESS")
            self.assertEqual(data["app_id"], sample_id)
            ir = data.get("canonical_ir", {})
            self.assertEqual(ir.get("app_metadata", {}).get("app_name"), "Sample Retail Analytics")
            self.assertGreaterEqual(len(ir.get("visual_catalog", {}).get("sheets", [])), 1)
            self.assertGreaterEqual(len(ir.get("data_layer", {}).get("tables", [])), 1)

            # Verify that database was updated with sheet count and IR_COMPILED status
            saved_app = EnterpriseMigrationHandler.db.get_app(sample_id)
            self.assertIsNotNone(saved_app)
            self.assertEqual(saved_app["extraction_status"], "IR_COMPILED")
            self.assertGreaterEqual(saved_app["sheet_count"], 1)
            self.assertGreaterEqual(saved_app["widget_count"], 1)

    def test_auto_discover_active_instance(self):
        from enterprise_qlik.web.server import _auto_discover_active_instance
        # Create dedicated temp db to test auto discovery
        tfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tfile.close()
        try:
            test_db = DatabaseManager(db_path=tfile.name)
            # Create an active on-prem instance with mock host
            test_db.create_instance(
                name="Auto Mock OnPrem",
                environment_type="on_prem",
                qlik_host="demo-qseow.internal.mock",
                auth_config={"qrs_port": 4242, "user_id": "sa_api"},
                is_active=True,
                tenant_id="inst-auto-test"
            )
            self.assertEqual(len(test_db.get_apps(tenant_id="inst-auto-test")), 0)
            _auto_discover_active_instance(test_db)
            discovered = test_db.get_apps(tenant_id="inst-auto-test")
            self.assertGreaterEqual(len(discovered), 1)
            self.assertEqual(discovered[0]["app_id"], "onprem-treasury-001")
        finally:
            if os.path.exists(tfile.name):
                os.remove(tfile.name)
            if "test_db" in locals() and os.path.exists(test_db.okf_catalog_dir):
                shutil.rmtree(test_db.okf_catalog_dir, ignore_errors=True)

    def test_okf_catalog_reconcile_and_fleet_compile_endpoints(self):
        # 1. Extract two sample apps so OKF catalog has concepts
        for app_id, app_name in [("okf-sample-1", "Finance Revenue Tracker"), ("okf-sample-2", "Regional Margin Tracker")]:
            payload = json.dumps({"app_id": app_id, "use_sample": True, "app_name": app_name}).encode("utf-8")
            req_ext = urllib.request.Request(
                f"{self.base_url}/api/stage1/extract",
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req_ext, timeout=5) as resp_e:
                self.assertEqual(resp_e.status, 200)

        # 2. POST /api/okf/reconcile (Stage 1.5 Explore Consolidation)
        req_rec = urllib.request.Request(
            f"{self.base_url}/api/okf/reconcile",
            data=b"{}",
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_rec, timeout=5) as resp_r:
            self.assertEqual(resp_r.status, 200)
            rec_data = json.loads(resp_r.read().decode("utf-8"))
            self.assertEqual(rec_data["status"], "SUCCESS")
            self.assertGreaterEqual(rec_data["reconciliation"]["canonical_explores_created"], 1)

        # 3. GET /api/okf/catalog
        req_cat = urllib.request.Request(f"{self.base_url}/api/okf/catalog")
        with urllib.request.urlopen(req_cat, timeout=5) as resp_c:
            self.assertEqual(resp_c.status, 200)
            cat_data = json.loads(resp_c.read().decode("utf-8"))
            self.assertEqual(cat_data["status"], "SUCCESS")
            self.assertIn("concepts", cat_data)
            self.assertGreaterEqual(len(cat_data["concepts"]["explores"]), 1)
            self.assertGreaterEqual(len(cat_data["concepts"]["apps"]), 2)
            app_concept_path = cat_data["concepts"]["apps"][0]["concept_path"]

        # 4. GET /api/okf/concept?path=...
        req_get_concept = urllib.request.Request(f"{self.base_url}/api/okf/concept?path={app_concept_path}")
        with urllib.request.urlopen(req_get_concept, timeout=5) as resp_gc:
            self.assertEqual(resp_gc.status, 200)
            concept_data = json.loads(resp_gc.read().decode("utf-8"))
            self.assertEqual(concept_data["status"], "SUCCESS")
            concept = concept_data["concept"]
            self.assertEqual(concept["concept_path"], app_concept_path)

        # 5. POST /api/okf/concept (Save governance & curated notes with optimistic concurrency)
        update_payload = json.dumps({
            "concept_path": app_concept_path,
            "governance_updates": {"migration_wave": "wave1", "assigned_lead": "Elena Rostova"},
            "curated_notes": "Approved for Wave 1 consolidated explore binding.",
            "expected_sha256": concept["content_sha256"],
        }).encode("utf-8")
        req_upd = urllib.request.Request(
            f"{self.base_url}/api/okf/concept",
            data=update_payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_upd, timeout=5) as resp_u:
            self.assertEqual(resp_u.status, 200)
            upd_data = json.loads(resp_u.read().decode("utf-8"))
            self.assertEqual(upd_data["status"], "SUCCESS")
            self.assertEqual(upd_data["concept"]["governance"]["migration_wave"], "wave1")
            self.assertIn("Approved for Wave 1", upd_data["concept"]["curated_notes"])

        # 6. POST /api/okf/compile-fleet (Stage 2 Consolidated LookML Compilation)
        compile_payload = json.dumps({"model_name": "consolidated_enterprise_bi"}).encode("utf-8")
        req_comp = urllib.request.Request(
            f"{self.base_url}/api/okf/compile-fleet",
            data=compile_payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_comp, timeout=5) as resp_cmp:
            self.assertEqual(resp_cmp.status, 200)
            cmp_data = json.loads(resp_cmp.read().decode("utf-8"))
            self.assertEqual(cmp_data["status"], "SUCCESS")
            self.assertEqual(cmp_data["source_mode"], "OKF_V02_FLEET_CATALOG")
            self.assertGreaterEqual(len(cmp_data["artifacts"]["views"]), 1)
            self.assertGreaterEqual(len(cmp_data["artifacts"]["explores"]), 1)

        # 7. GET /api/okf/export.zip
        req_zip = urllib.request.Request(f"{self.base_url}/api/okf/export.zip")
        with urllib.request.urlopen(req_zip, timeout=5) as resp_z:
            self.assertEqual(resp_z.status, 200)
            self.assertEqual(resp_z.headers.get("Content-Type"), "application/zip")
            zip_bytes = resp_z.read()
            self.assertGreater(len(zip_bytes), 100)


if __name__ == "__main__":
    unittest.main()
