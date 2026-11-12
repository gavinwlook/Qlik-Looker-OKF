import os
import tempfile
import unittest
from enterprise_qlik.storage.db import DatabaseManager
from enterprise_qlik.stage1_extract.connection import QlikConnectionService


class TestInstanceManagement(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.db = DatabaseManager(db_path=self.temp_db.name)

    def tearDown(self):
        if os.path.exists(self.temp_db.name):
            os.remove(self.temp_db.name)

    def test_instance_crud_and_activation(self):
        # 1. Seed defaults
        self.db.seed_default_instances()
        instances = self.db.get_instances()
        self.assertEqual(len(instances), 2)
        active = self.db.get_active_instance()
        self.assertIsNotNone(active)
        self.assertEqual(active["environment_type"], "cloud")

        # 2. Create custom On-Prem instance
        inst_id = self.db.create_instance(
            name="Zurich Private Banking Cluster",
            environment_type="on_prem",
            qlik_host="qlik-ch.internal.corp",
            auth_config={"qrs_port": 4242, "engine_port": 4747, "user_id": "ch_admin"},
            is_active=True
        )
        self.assertTrue(inst_id.startswith("inst-"))

        # Verify active switched to new instance
        active = self.db.get_active_instance()
        self.assertEqual(active["tenant_id"], inst_id)
        self.assertEqual(active["name"], "Zurich Private Banking Cluster")

        # 3. Update instance
        self.db.update_instance(
            tenant_id=inst_id,
            name="Zurich Private Banking Cluster (Updated)",
            environment_type="on_prem",
            qlik_host="qlik-ch.internal.corp",
            auth_config={"qrs_port": 4242, "engine_port": 4747, "user_id": "ch_admin_v2"}
        )
        updated = self.db.get_instance(inst_id)
        self.assertEqual(updated["name"], "Zurich Private Banking Cluster (Updated)")
        self.assertEqual(updated["auth_config"]["user_id"], "ch_admin_v2")

        # 4. Status update
        self.db.update_instance_status(inst_id, status="CONNECTED", version_info="QSEoW Patch 4")
        checked = self.db.get_instance(inst_id)
        self.assertEqual(checked["status"], "CONNECTED")
        self.assertEqual(checked["version_info"], "QSEoW Patch 4")

        # 5. Delete instance
        self.db.delete_instance(inst_id)
        self.assertIsNone(self.db.get_instance(inst_id))

    def test_connection_service_cloud_evaluation(self):
        # Demo token returns simulated connected state
        cloud_cfg = {
            "environment_type": "cloud",
            "qlik_host": "https://tenant.eu.qlikcloud.com",
            "auth_config": {"api_key": "demo_eval_token"}
        }
        res = QlikConnectionService.test_connection(cloud_cfg)
        self.assertTrue(res["connected"])
        self.assertEqual(res["environment_type"], "cloud")

        # Missing token returns error
        invalid_cfg = {
            "environment_type": "cloud",
            "qlik_host": "https://tenant.eu.qlikcloud.com",
            "auth_config": {"api_key": ""}
        }
        res_err = QlikConnectionService.test_connection(invalid_cfg)
        self.assertFalse(res_err["connected"])
        self.assertIn("required", res_err["error"])

    def test_connection_service_onprem_evaluation(self):
        # Demo on-prem host returns simulated connected state
        onprem_cfg = {
            "environment_type": "on_prem",
            "qlik_host": "demo-qseow.internal.mock",
            "auth_config": {"qrs_port": 4242, "user_id": "sa_api"}
        }
        res = QlikConnectionService.test_connection(onprem_cfg)
        self.assertTrue(res["connected"])
        self.assertEqual(res["environment_type"], "on_prem")

        # Non-existent certificate file path returns error
        cert_err_cfg = {
            "environment_type": "on_prem",
            "qlik_host": "real-server.corp.internal",
            "auth_config": {
                "qrs_port": 4242,
                "cert_path": "/nonexistent/path/client.pem",
                "key_path": "/nonexistent/path/client_key.pem"
            }
        }
        res_err = QlikConnectionService.test_connection(cert_err_cfg)
        self.assertFalse(res_err["connected"])
        self.assertIn("not found on disk", res_err["error"])

    def test_discover_apps_for_instance(self):
        inst = {
            "tenant_id": "test-inst-1",
            "name": "EMEA Cloud",
            "environment_type": "cloud",
            "qlik_host": "https://mock.qlikcloud.com",
            "auth_config": {"api_key": "demo_test"}
        }
        apps = QlikConnectionService.discover_apps_for_instance(inst)
        self.assertGreaterEqual(len(apps), 1)
        self.assertIn("app_id", apps[0])
        self.assertIn("name", apps[0])

    def test_discover_apps_for_onprem_instance(self):
        inst = {
            "tenant_id": "test-onprem-1",
            "name": "Frankfurt OnPrem",
            "environment_type": "on_prem",
            "qlik_host": "demo-qseow.internal.mock",
            "auth_config": {"qrs_port": 4242, "user_id": "sa_api"}
        }
        apps = QlikConnectionService.discover_apps_for_instance(inst)
        self.assertGreaterEqual(len(apps), 1)
        self.assertEqual(apps[0]["app_id"], "onprem-treasury-001")
        self.assertEqual(apps[0]["stream_or_space"], "Treasury")
        self.assertEqual(apps[0]["space_type"], "stream")


if __name__ == "__main__":
    unittest.main()
