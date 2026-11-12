import unittest
from enterprise_qlik.stage1_extract.compatibility import CompatibilityAnalyzer

class TestCompatibilityAnalyzer(unittest.TestCase):
    def setUp(self):
        self.analyzer = CompatibilityAnalyzer()

    def test_category_1_simple_set_analysis(self):
        metadata = {
            "sheets": [{
                "widgets": [{
                    "title": "Filtered KPI",
                    "measures": [{"expression": "Sum({$<Region={'EMEA'}, Year={'2025'}>} Sales)"}]
                }]
            }]
        }
        res = self.analyzer.analyze(metadata)
        types = [f["item_type"] for f in res["findings"]]
        self.assertIn("SIMPLE_SET_ANALYSIS", types)
        f = next(f for f in res["findings"] if f["item_type"] == "SIMPLE_SET_ANALYSIS")
        self.assertEqual(f["category"], 1)

    def test_category_1_what_if_variable(self):
        metadata = {
            "variables": [{"name": "vDiscountRate", "definition": "0.15"}]
        }
        res = self.analyzer.analyze(metadata)
        types = [f["item_type"] for f in res["findings"]]
        self.assertIn("WHAT_IF_VARIABLE", types)
        f = next(f for f in res["findings"] if f["item_type"] == "WHAT_IF_VARIABLE")
        self.assertEqual(f["category"], 1)

    def test_category_1_section_access(self):
        metadata = {
            "data_model": {"load_script": "SECTION ACCESS; LOAD * INLINE [ ACCESS, USERID ];"}
        }
        res = self.analyzer.analyze(metadata)
        types = [f["item_type"] for f in res["findings"]]
        self.assertIn("SECTION_ACCESS", types)
        f = next(f for f in res["findings"] if f["item_type"] == "SECTION_ACCESS")
        self.assertEqual(f["category"], 1)

    def test_category_2_complex_set_analysis_p_e(self):
        metadata = {
            "sheets": [{
                "widgets": [{
                    "title": "Complex KPI",
                    "measures": [{"expression": "Sum({<CustomerID=P({<OrderYear={'2024'}>} CustomerID)>} Sales)"}]
                }]
            }]
        }
        res = self.analyzer.analyze(metadata)
        types = [f["item_type"] for f in res["findings"]]
        self.assertIn("COMPLEX_SET_ANALYSIS", types)
        f = next(f for f in res["findings"] if f["item_type"] == "COMPLEX_SET_ANALYSIS")
        self.assertEqual(f["category"], 2)

    def test_category_2_qvs_load_script_etl(self):
        metadata = {
            "data_model": {"load_script": "AggTable: LOAD OrderID, Sum(Amt) RESIDENT RawOrders GROUP BY OrderID;"}
        }
        res = self.analyzer.analyze(metadata)
        types = [f["item_type"] for f in res["findings"]]
        self.assertIn("QVS_LOAD_SCRIPT_ETL", types)
        f = next(f for f in res["findings"] if f["item_type"] == "QVS_LOAD_SCRIPT_ETL")
        self.assertEqual(f["category"], 2)

    def test_category_2_data_island(self):
        metadata = {
            "data_model": {
                "tables": [
                    {"name": "Orders", "keys": [{"key_field": "CustID", "target_tables": ["Customers"]}]},
                    {"name": "Customers", "keys": [{"key_field": "CustID", "target_tables": ["Orders"]}]},
                    {"name": "ScenarioInputs", "keys": []} # 0 keys -> Data island
                ]
            }
        }
        res = self.analyzer.analyze(metadata)
        types = [f["item_type"] for f in res["findings"]]
        self.assertIn("DATA_ISLAND", types)
        f = next(f for f in res["findings"] if f["item_type"] == "DATA_ISLAND")
        self.assertEqual(f["category"], 2)

    def test_category_2_alternate_states(self):
        metadata = {
            "alternate_states": ["$", "GroupA", "GroupB"]
        }
        res = self.analyzer.analyze(metadata)
        types = [f["item_type"] for f in res["findings"]]
        self.assertIn("ALTERNATE_STATES", types)
        f = next(f for f in res["findings"] if f["item_type"] == "ALTERNATE_STATES")
        self.assertEqual(f["category"], 2)

    def test_category_3_cyclic_data_model(self):
        metadata = {
            "data_model": {
                "tables": [
                    {"name": "A", "keys": [{"target_tables": ["B"]}]},
                    {"name": "B", "keys": [{"target_tables": ["C"]}]},
                    {"name": "C", "keys": [{"target_tables": ["A"]}]}, # Cycle A->B->C->A
                ]
            }
        }
        res = self.analyzer.analyze(metadata)
        types = [f["item_type"] for f in res["findings"]]
        self.assertIn("CYCLIC_DATA_MODEL", types)
        f = next(f for f in res["findings"] if f["item_type"] == "CYCLIC_DATA_MODEL")
        self.assertEqual(f["category"], 3)
        self.assertEqual(f["severity"], "CRITICAL")

    def test_category_3_sheet_triggers(self):
        metadata = {
            "sheets": [{
                "title": "Sheet1",
                "actions": [{"type": "OnActivateSheet", "action": "ClearFilters"}]
            }]
        }
        res = self.analyzer.analyze(metadata)
        types = [f["item_type"] for f in res["findings"]]
        self.assertIn("SHEET_TRIGGERS_MACROS", types)
        f = next(f for f in res["findings"] if f["item_type"] == "SHEET_TRIGGERS_MACROS")
        self.assertEqual(f["category"], 3)

    def test_category_3_associative_experience(self):
        metadata = {
            "sheets": [{
                "widgets": [{"title": "Filters", "type": "filterpane"}]
            }]
        }
        res = self.analyzer.analyze(metadata)
        types = [f["item_type"] for f in res["findings"]]
        self.assertIn("ASSOCIATIVE_SELECTION_EXPERIENCE", types)
        f = next(f for f in res["findings"] if f["item_type"] == "ASSOCIATIVE_SELECTION_EXPERIENCE")
        self.assertEqual(f["category"], 3)

    def test_finding_location_scoping(self):
        metadata = {
            "sheets": [{
                "id": "sheet-01",
                "title": "Executive Summary",
                "widgets": [{
                    "title": "KPI Revenue",
                    "measures": [{"expression": "Sum({<Region={'EMEA'}>} Sales)"}]
                }]
            }],
            "variables": [{"name": "vTaxRate", "definition": "0.20"}],
            "data_model": {
                "load_script": "SECTION ACCESS; LOAD * INLINE [ ACCESS, USERID ];"
            }
        }
        res = self.analyzer.analyze(metadata)
        findings = res["findings"]
        
        sheet_f = next(f for f in findings if f["item_type"] == "SIMPLE_SET_ANALYSIS")
        self.assertEqual(sheet_f["scope_type"], "sheet")
        self.assertEqual(sheet_f["location"], "Executive Summary")
        self.assertEqual(sheet_f["sheet_title"], "Executive Summary")
        self.assertEqual(sheet_f["widget_title"], "KPI Revenue")

        var_f = next(f for f in findings if f["item_type"] == "WHAT_IF_VARIABLE")
        self.assertEqual(var_f["scope_type"], "global")
        self.assertEqual(var_f["location"], "Global Master Items & Parameters")

        dm_f = next(f for f in findings if f["item_type"] == "SECTION_ACCESS")
        self.assertEqual(dm_f["scope_type"], "data_model")
        self.assertEqual(dm_f["location"], "Shared Data Model & Script")

if __name__ == "__main__":
    unittest.main()
