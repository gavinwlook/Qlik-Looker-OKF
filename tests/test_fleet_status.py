import unittest
import os
import json
import sqlite3
import urllib.request
import threading
from http.server import ThreadingHTTPServer

from enterprise_qlik.storage.db import DatabaseManager
from enterprise_qlik.storage.migrations import provision_sqlite
from enterprise_qlik.web.server import EnterpriseMigrationHandler


class TestFleetStatusAndHierarchy(unittest.TestCase):
    def setUp(self):
        self.db_path = "test_fleet_status.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.db = DatabaseManager(self.db_path)
        self.db.seed_default_instances()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_fleet_status_rollup(self):
        status = self.db.get_fleet_status()
        self.assertIn("summary", status)
        self.assertIn("hierarchy", status)

        summary = status["summary"]
        self.assertGreaterEqual(summary["total_apps"], 7)
        self.assertGreaterEqual(summary["ir_compiled_count"], 1)
        self.assertGreater(summary["completion_pct"], 0.0)
        self.assertGreater(summary["total_sheets"], 0)
        self.assertGreater(summary["total_widgets"], 0)

    def test_fleet_hierarchy_cloud_vs_onprem(self):
        status = self.db.get_fleet_status()
        hierarchy = status["hierarchy"]
        self.assertGreaterEqual(len(hierarchy), 2)

        cloud_inst = next((i for i in hierarchy if i["environment_type"] == "cloud"), None)
        self.assertIsNotNone(cloud_inst)
        self.assertEqual(cloud_inst["tenant_id"], "inst-cloud-001")
        
        # Verify Cloud container types (managed, shared, personal)
        cloud_cat_types = [c["type"] for c in cloud_inst["containers"]]
        self.assertIn("managed", cloud_cat_types)
        self.assertIn("shared", cloud_cat_types)
        self.assertIn("personal", cloud_cat_types)

        onprem_inst = next((i for i in hierarchy if i["environment_type"] == "on_prem"), None)
        self.assertIsNotNone(onprem_inst)
        self.assertEqual(onprem_inst["tenant_id"], "inst-onprem-002")

        # Verify On-Prem container types (stream, work)
        onprem_cat_types = [c["type"] for c in onprem_inst["containers"]]
        self.assertIn("stream", onprem_cat_types)
        self.assertIn("work", onprem_cat_types)

    def test_fleet_status_filtered_by_tenant(self):
        cloud_status = self.db.get_fleet_status(tenant_id="inst-cloud-001")
        self.assertEqual(len(cloud_status["hierarchy"]), 1)
        self.assertEqual(cloud_status["hierarchy"][0]["tenant_id"], "inst-cloud-001")

        onprem_status = self.db.get_fleet_status(tenant_id="inst-onprem-002")
        self.assertEqual(len(onprem_status["hierarchy"]), 1)
        self.assertEqual(onprem_status["hierarchy"][0]["tenant_id"], "inst-onprem-002")


class TestFleetEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "test_fleet_endpoint.db"
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        cls.db = DatabaseManager(cls.db_path)
        cls.db.seed_default_instances()

        EnterpriseMigrationHandler.db = cls.db
        cls.port = 8893
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), EnterpriseMigrationHandler)
        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)

    def test_get_fleet_status_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/fleet/status"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertIn("summary", data)
            self.assertIn("hierarchy", data)
            self.assertGreater(data["summary"]["total_apps"], 0)

    def test_get_fleet_hierarchy_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/fleet/hierarchy"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertIn("summary", data)
            self.assertIn("hierarchy", data)


if __name__ == "__main__":
    unittest.main()
