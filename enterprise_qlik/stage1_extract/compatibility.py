"""
3-Tier Feature Compatibility & Migration Gap Engine
===================================================
Analyzes Qlik Sense application metadata across three distinct migration tiers:
- Category 1: Easily Worked Around / Mapped Differently (Autonomous LookML mapping)
- Category 2: Requires Upstream Modeling or Heavy LookML Refactoring (dbt / NDTs / Data Islands)
- Category 3: Cannot Realistically Be Reproduced / Deprecated in Target State (Associative, Loops, Triggers)

Zero external dependencies.
"""

import re
from typing import Any, Dict, List, Set, Optional


class CompatibilityAnalyzer:
    """Detects and categorizes Qlik architectural patterns into the 3-tier taxonomy."""

    def __init__(self):
        self.findings: List[Dict[str, Any]] = []

    def analyze(self, app_metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Runs the complete 3-Tier taxonomy analysis on sanitized app metadata."""
        self.findings = []

        data_model = app_metadata.get("data_model", {})
        sheets = app_metadata.get("sheets", [])
        load_script = data_model.get("load_script", "") or app_metadata.get("load_script", "")
        tables = data_model.get("tables", [])
        variables = app_metadata.get("variables", [])
        master_items = app_metadata.get("master_items", {})
        alternate_states = app_metadata.get("alternate_states", [])

        # 1. Analyze Data Model Architecture (Categories 1, 2, 3)
        self._analyze_data_model(tables, load_script)

        # 2. Analyze Variables & What-If Scenarios (Category 1)
        self._analyze_variables(variables)

        # 3. Analyze Master Items & Section Access (Category 1)
        self._analyze_master_items(master_items)

        # 4. Analyze Alternate States (Category 2)
        self._analyze_alternate_states(alternate_states)

        # 5. Analyze Visual Catalog & Expressions (Categories 1, 2, 3)
        self._analyze_sheets_and_widgets(sheets)

        cat1 = [f for f in self.findings if f["category"] == 1]
        cat2 = [f for f in self.findings if f["category"] == 2]
        cat3 = [f for f in self.findings if f["category"] == 3]

        critical = [f for f in self.findings if f["severity"] == "CRITICAL"]
        high = [f for f in self.findings if f["severity"] == "HIGH"]
        med = [f for f in self.findings if f["severity"] == "MEDIUM"]
        low = [f for f in self.findings if f["severity"] == "LOW"]

        total_hours = sum(f.get("estimated_remediation_hours", 0) for f in self.findings)

        return {
            "findings": self.findings,
            "summary": {
                "total_issues": len(self.findings),
                "category_breakdown": {
                    "category_1_mapped_differently": len(cat1),
                    "category_2_upstream_refactoring": len(cat2),
                    "category_3_target_deprecated": len(cat3),
                },
                "severity_breakdown": {
                    "critical": len(critical),
                    "high": len(high),
                    "medium": len(med),
                    "low": len(low),
                },
                "total_estimated_remediation_hours": total_hours,
                "hard_blockers_count": len(critical),
            },
            "deprecations_guide": self._generate_deprecations_guide(),
        }

    def _analyze_data_model(self, tables: List[Dict[str, Any]], load_script: str):
        if re.search(r"(?i)\bSECTION\s+ACCESS\b", load_script):
            self.findings.append({
                "category": 1,
                "severity": "HIGH",
                "item_type": "SECTION_ACCESS",
                "title": "Section Access Dynamic Security",
                "description": "Qlik Section Access data reduction detected in script.",
                "remediation": "Map to Looker User Attributes paired with access_filter on Explores or sql_always_where.",
                "lookml_template": "access_filter: {\n  field: users.region\n  user_attribute: allowed_regions\n}",
                "estimated_remediation_hours": 4.0,
                "scope_type": "data_model",
                "location": "Shared Data Model & Script",
                "sheet_title": None,
                "sheet_id": None,
                "widget_title": None,
            })

        etl_patterns = [r"(?i)\bRESIDENT\b", r"(?i)\bLEFT\s+JOIN\b", r"(?i)\bCONCATENATE\b", r"(?i)\bAPPLYMAP\b"]
        for p in etl_patterns:
            if re.search(p, load_script):
                kw = p.replace(r"(?i)\b", "").replace(r"\b", "").strip()
                self.findings.append({
                    "category": 2,
                    "severity": "HIGH",
                    "item_type": "QVS_LOAD_SCRIPT_ETL",
                    "title": f"Qlik Load Script ETL ({kw})",
                    "description": f"In-memory QVS data transformation '{kw}' detected. Looker is not an ETL engine.",
                    "remediation": f"Refactor '{kw}' into an upstream dbt model, BigQuery SQL View, or Persistent Derived Table (PDT).",
                    "lookml_template": "derived_table: {\n  sql: SELECT * FROM {{ ref('stg_sales') }} LEFT JOIN ... ;;\n  datagroup_trigger: daily_etl\n}",
                    "estimated_remediation_hours": 8.0,
                    "scope_type": "data_model",
                    "location": "Shared Data Model & Script",
                    "sheet_title": None,
                    "sheet_id": None,
                    "widget_title": None,
                })
                break

        for tbl in tables:
            tname = tbl.get("name", "")
            if "$Syn" in tname or "$syn" in tname:
                self.findings.append({
                    "category": 2,
                    "severity": "MEDIUM",
                    "item_type": "SYNTHETIC_KEY",
                    "title": f"Synthetic Key Table ({tname})",
                    "description": "Qlik created a synthetic key table to resolve multi-field composite keys.",
                    "remediation": "Combine composite keys upstream into a single surrogate key hash in your Cloud Data Warehouse.",
                    "lookml_template": "dimension: composite_key {\n  type: string\n  sql: CONCAT(${field_a}, '-', ${field_b}) ;;\n}",
                    "estimated_remediation_hours": 3.0,
                    "scope_type": "data_model",
                    "location": "Shared Data Model & Script",
                    "sheet_title": None,
                    "sheet_id": None,
                    "widget_title": None,
                })

        connected_tables: Set[str] = set()
        for tbl in tables:
            keys = tbl.get("keys", []) or []
            if len(keys) > 0:
                connected_tables.add(tbl.get("name", ""))

        for tbl in tables:
            tname = tbl.get("name", "")
            if tname not in connected_tables and not tname.startswith("$"):
                self.findings.append({
                    "category": 2,
                    "severity": "MEDIUM",
                    "item_type": "DATA_ISLAND",
                    "title": f"Data Island Table ({tname})",
                    "description": f"Table '{tname}' has zero join keys connecting it to the data model.",
                    "remediation": "Translate to a Looker parameter or standalone filter table with explicit type: cross join.",
                    "lookml_template": "join: " + tname.lower() + " {\n  type: cross\n  relationship: one_to_one\n}",
                    "estimated_remediation_hours": 3.5,
                    "scope_type": "data_model",
                    "location": "Shared Data Model & Script",
                    "sheet_title": None,
                    "sheet_id": None,
                    "widget_title": None,
                })

        if self._detect_table_cycles(tables):
            self.findings.append({
                "category": 3,
                "severity": "CRITICAL",
                "item_type": "CYCLIC_DATA_MODEL",
                "title": "Cyclic Join Loop in Data Model",
                "description": "Circular relationship loop detected among tables (e.g., A -> B -> C -> A). Looker's SQL engine requires a Directed Acyclic Graph (DAG).",
                "remediation": "CRITICAL: Must be refactored upstream into a star or snowflake schema with a clear fact table before Looker deployment.",
                "lookml_template": "# ERROR: Cyclic loops cannot be modeled directly in Looker. Break the loop upstream in dbt.",
                "estimated_remediation_hours": 16.0,
                "scope_type": "data_model",
                "location": "Shared Data Model & Script",
                "sheet_title": None,
                "sheet_id": None,
                "widget_title": None,
            })

        if re.search(r"(?i)CreateSearchIndexOnReload", load_script):
            self.findings.append({
                "category": 3,
                "severity": "LOW",
                "item_type": "GLOBAL_SMART_SEARCH",
                "title": "Global In-Memory Smart Search Index",
                "description": "CreateSearchIndexOnReload enabled. In Looker/BigQuery, full-table wildcard search across all fields generates prohibitive scan costs.",
                "remediation": "Deprecated in target state. Educate stakeholders to use indexed Looker field filters or BigQuery Search Indexes (SEARCH()).",
                "lookml_template": "# Deprecated: Use individual dimension filters in dashboard controls instead.",
                "estimated_remediation_hours": 1.0,
                "scope_type": "data_model",
                "location": "Shared Data Model & Script",
                "sheet_title": None,
                "sheet_id": None,
                "widget_title": None,
            })

    def _detect_table_cycles(self, tables: List[Dict[str, Any]]) -> bool:
        graph: Dict[str, Set[str]] = {}
        for tbl in tables:
            name = tbl.get("name", "")
            graph.setdefault(name, set())
            for key in tbl.get("keys", []):
                if isinstance(key, dict):
                    for target in key.get("target_tables", []):
                        if target != name:
                            graph[name].add(target)

        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for neighbor in graph.get(node, set()):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            rec_stack.remove(node)
            return False

        for node in graph:
            if node not in visited:
                if dfs(node):
                    return True
        return False

    def _analyze_variables(self, variables: List[Dict[str, Any]]):
        for v in variables:
            name = v.get("name", "")
            val = str(v.get("definition", ""))
            if re.match(r"(?i)^v.*(rate|discount|pct|threshold|factor|scenario|multiplier)", name):
                self.findings.append({
                    "category": 1,
                    "severity": "MEDIUM",
                    "item_type": "WHAT_IF_VARIABLE",
                    "title": f"What-If Parameter Variable ({name})",
                    "description": f"Variable '{name}' with value '{val}' acts as an interactive simulation parameter.",
                    "remediation": "Map to a LookML parameter and inject dynamically via Liquid variable {% parameter %}.",
                    "lookml_template": f"parameter: {name.lower()} {{\n  type: number\n  default_value: \"{val or '0'}\"\n}}\n\nmeasure: simulated_val {{\n  type: sum\n  sql: ${{amount}} * (1 - {{% parameter {name.lower()} %}}) ;;\n}}",
                    "estimated_remediation_hours": 2.5,
                    "scope_type": "global",
                    "location": "Global Master Items & Parameters",
                    "sheet_title": None,
                    "sheet_id": None,
                    "widget_title": None,
                })

    def _analyze_master_items(self, master_items: Dict[str, Any]):
        dims = master_items.get("dimensions", [])
        for d in dims:
            grouping = d.get("grouping", "N")
            title = d.get("title", "")
            if grouping == "H":
                self.findings.append({
                    "category": 1,
                    "severity": "LOW",
                    "item_type": "HIERARCHICAL_DRILL_GROUP",
                    "title": f"Hierarchical Drill Group ({title})",
                    "description": f"Master dimension '{title}' defines a hierarchical drill group.",
                    "remediation": "Map directly to LookML drill_fields parameter.",
                    "lookml_template": "dimension: category {\n  type: string\n  drill_fields: [subcategory, product_name]\n}",
                    "estimated_remediation_hours": 1.0,
                    "scope_type": "global",
                    "location": "Global Master Items & Parameters",
                    "sheet_title": None,
                    "sheet_id": None,
                    "widget_title": None,
                })
            elif grouping == "C":
                self.findings.append({
                    "category": 2,
                    "severity": "MEDIUM",
                    "item_type": "CYCLIC_DIMENSION_GROUP",
                    "title": f"Cyclic Dimension Group ({title})",
                    "description": f"Master dimension '{title}' allows user to toggle dimension dynamically.",
                    "remediation": "Translate to a LookML parameter with allowed_values and a dynamic dimension using CASE statements.",
                    "lookml_template": "parameter: choose_dim {\n  type: unquoted\n  allowed_value: { label: \"Region\" value: \"region\" }\n}\ndimension: dynamic_dim {\n  sql: {% if choose_dim._parameter_value == 'region' %} ${region} {% endif %} ;;\n}",
                    "estimated_remediation_hours": 3.0,
                    "scope_type": "global",
                    "location": "Global Master Items & Parameters",
                    "sheet_title": None,
                    "sheet_id": None,
                    "widget_title": None,
                })

    def _analyze_alternate_states(self, alternate_states: List[str]):
        for state in alternate_states:
            if state and state != "$" and state != "[inherit]":
                self.findings.append({
                    "category": 2,
                    "severity": "HIGH",
                    "item_type": "ALTERNATE_STATES",
                    "title": f"Alternate State Selection Space ({state})",
                    "description": f"Decoupled selection state '{state}' detected for comparative/cohort analysis.",
                    "remediation": "Duplicate the view join in the LookML Explore or use templated filters with Liquid {% condition %}.",
                    "lookml_template": "join: cohort_a {\n  from: users\n  sql_on: ... ;;\n}\njoin: cohort_b {\n  from: users\n  sql_on: ... ;;\n}",
                    "estimated_remediation_hours": 6.0,
                    "scope_type": "global",
                    "location": "Global Master Items & Parameters",
                    "sheet_title": None,
                    "sheet_id": None,
                    "widget_title": None,
                })

    def _analyze_sheets_and_widgets(self, sheets: List[Dict[str, Any]]):
        for sheet in sheets:
            sheet_title = sheet.get("title", "Untitled")
            sheet_id = sheet.get("id")
            actions = sheet.get("actions", []) or sheet.get("triggers", [])
            if actions:
                self.findings.append({
                    "category": 3,
                    "severity": "HIGH",
                    "item_type": "SHEET_TRIGGERS_MACROS",
                    "title": f"Sheet-Level Trigger / Action ({sheet_title})",
                    "description": f"Sheet '{sheet_title}' contains OnActivateSheet macros or automated filter triggers.",
                    "remediation": "Deprecated in target state. Looker dashboards are stateless URLs. Replace with default dashboard filters or URL parameters.",
                    "lookml_template": "# Deprecated: Use default: 'EMEA' in dashboard filter configuration instead.",
                    "estimated_remediation_hours": 2.0,
                    "scope_type": "sheet",
                    "location": sheet_title,
                    "sheet_title": sheet_title,
                    "sheet_id": sheet_id,
                    "widget_title": None,
                })

            sheet_filterpanes = []
            for widget in sheet.get("widgets", []):
                wtype = widget.get("type", "")
                wtitle = widget.get("title", "Untitled")

                if wtype in ("filterpane", "listbox"):
                    sheet_filterpanes.append(wtitle)

                for m in widget.get("measures", []):
                    expr = m.get("expression", "") or m.get("label", "")
                    self._inspect_expression(expr, sheet_title, wtitle, sheet_id=sheet_id)

            if sheet_filterpanes:
                fp_label = ", ".join(f"'{fp}'" for fp in sheet_filterpanes[:2])
                if len(sheet_filterpanes) > 2:
                    fp_label += f" (+{len(sheet_filterpanes)-2} more)"
                self.findings.append({
                    "category": 3,
                    "severity": "MEDIUM",
                    "item_type": "ASSOCIATIVE_SELECTION_EXPERIENCE",
                    "title": f"Associative Selection Filterpane ({sheet_title})",
                    "description": f"Sheet '{sheet_title}' contains filterpane(s) [{fp_label}] calculating in-memory exclusion states across unselected tables. In relational SQL, unselected values are filtered out entirely.",
                    "remediation": "Deprecated in target state. Educate stakeholders on standard relational SQL WHERE filtering; replicate critical cross-filters with Looker cross-filtering.",
                    "lookml_template": "# Deprecated: Replaced by Looker native cross_filtering: true at dashboard level.",
                    "estimated_remediation_hours": 1.5,
                    "scope_type": "sheet",
                    "location": sheet_title,
                    "sheet_title": sheet_title,
                    "sheet_id": sheet_id,
                    "widget_title": sheet_filterpanes[0] if len(sheet_filterpanes) == 1 else "Filterpanes",
                })

    def _inspect_expression(self, expr: str, sheet_title: str, widget_title: str, sheet_id: Optional[str] = None):
        if not expr:
            return

        if re.search(r"[PE]\s*\(", expr) or re.search(r"\$\(=.*?\)", expr):
            self.findings.append({
                "category": 2,
                "severity": "HIGH",
                "item_type": "COMPLEX_SET_ANALYSIS",
                "title": f"Complex Set Analysis with P()/E() ({widget_title})",
                "description": f"Expression '{expr}' in '{widget_title}' uses element functions P() or E() for dynamic set reduction.",
                "remediation": "Refactor into a LookML Native Derived Table (NDT) or correlated subquery in the Explore.",
                "lookml_template": "view: customer_cohort_p {\n  derived_table: {\n    explore_source: orders {\n      column: customer_id {}\n      filters: { field: orders.status value: \"complete\" }\n    }\n  }\n}",
                "estimated_remediation_hours": 5.0,
                "scope_type": "sheet",
                "location": sheet_title,
                "sheet_title": sheet_title,
                "sheet_id": sheet_id,
                "widget_title": widget_title,
            })
        elif re.search(r"\{[^}]*<[^>]+>[^}]*\}", expr):
            self.findings.append({
                "category": 1,
                "severity": "LOW",
                "item_type": "SIMPLE_SET_ANALYSIS",
                "title": f"Simple Set Analysis ({widget_title})",
                "description": f"Expression '{expr}' contains static filter brackets {{<Field={{'Val'}}>}}.",
                "remediation": "Map autonomously to a LookML measure with the filters parameter.",
                "lookml_template": "measure: filtered_sales {\n  type: sum\n  sql: ${sales} ;;\n  filters: [region: \"EMEA\"]\n}",
                "estimated_remediation_hours": 0.5,
                "scope_type": "sheet",
                "location": sheet_title,
                "sheet_title": sheet_title,
                "sheet_id": sheet_id,
                "widget_title": widget_title,
            })

    def _generate_deprecations_guide(self) -> str:
        return """# Target State Deprecations & Change Management Guide

### Category 3 Items: Non-Reproducible Architectural Features
Certain legacy Qlik features cannot or should not be reproduced in a modern Cloud Data Warehouse (BigQuery, Snowflake) and Looker semantic layer:

1. **Green / White / Gray Associative Engine Logic:**
   - *Qlik Reality:* Uses in-RAM bit arrays to retain and display excluded records in white/gray.
   - *Looker Reality:* Generates SQL `WHERE` clauses against columnar databases. Records not matching the filter are not scanned or returned.
   - *Remediation:* Enable Looker dashboard `cross_filtering: true`. Educate business users on relational query behavior.

2. **Global In-Memory Smart Search:**
   - *Qlik Reality:* Wildcard search across all fields in RAM via `CreateSearchIndexOnReload`.
   - *Looker Reality:* Wildcard string scans across billions of records generate prohibitive BigQuery slot scan costs.
   - *Remediation:* Replace with targeted dashboard dimension filters or BigQuery Search Indexes (`SEARCH()`).

3. **Sheet Triggers & Visual Basic Macros:**
   - *Qlik Reality:* Imperative event-driven triggers (`OnActivateSheet`).
   - *Looker Reality:* Declarative, stateless URL architecture.
   - *Remediation:* Replicate default filter states via Looker dashboard URL filters (`dashboard_url?Region=EMEA`).

4. **Cyclic Join Loops:**
   - *Qlik Reality:* QIX resolves cycles through synthetic tables or loose joins.
   - *Looker Reality:* SQL compilation requires a Directed Acyclic Graph (DAG). Circular joins generate an execution error.
   - *Remediation:* Break the loop upstream in dbt/SQL into a star or snowflake schema.
"""
