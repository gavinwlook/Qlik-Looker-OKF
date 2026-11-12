"""
Master Stage 2 Generator Orchestrator (OKF v0.2 & Fleet-Consolidated LookML)
============================================================================
Coordinates the compilation of LookML models, Canonical Explores, shared Views,
re-bound Dashboards, and dbt blueprints from an OKF v0.2 Knowledge Base or IR dictionary.

CRITICAL ARCHITECTURAL GUARANTEE:
This module has ZERO imports from Stage 1 (`stage1_extract`) or Qlik.
It runs in an isolated air-gapped environment with only the OKF `.md` catalog or IR contract.
"""

import json
import os
from typing import Any, Dict, List, Optional, Union
from enterprise_qlik.okf.frontmatter import concept_slug, parse_okf_document
from enterprise_qlik.stage2_lookml.explore_compiler import ExploreCompiler
from enterprise_qlik.stage2_lookml.view_compiler import ViewCompiler
from enterprise_qlik.stage2_lookml.dashboard_compiler import DashboardCompiler
from enterprise_qlik.stage2_lookml.dbt_compiler import DbtBlueprintCompiler


class LookMLGenerator:
    """Consumes OKF v0.2 Knowledge Bundles (or IR dicts) to generate deduplicated LookML & dbt models."""

    def __init__(self, model_name: str = "enterprise_analytics"):
        self.model_name = model_name
        self.explore_compiler = ExploreCompiler(model_name=model_name)
        self.view_compiler = ViewCompiler()
        self.dashboard_compiler = DashboardCompiler(model_name=model_name)
        self.dbt_compiler = DbtBlueprintCompiler()

    def _hydrate_ir_from_okf_app_markdown(self, md_text: str) -> Dict[str, Any]:
        parsed = parse_okf_document(md_text)
        fm = parsed.get("frontmatter", {})
        ext = parsed.get("extracted", {})
        gov = parsed.get("governance", {})
        return {
            "ir_version": "3.0-OKF",
            "okf_version": fm.get("okf_version", "0.2"),
            "contract_type": "OPEN_KNOWLEDGE_FORMAT_OKF",
            "app_metadata": {
                "app_id": fm.get("app_id") or ext.get("app_id", "app"),
                "app_name": fm.get("title") or ext.get("app_name", "Qlik App"),
                "bound_explore": gov.get("bound_explore", ""),
            },
            "data_layer": {
                "tables": ext.get("tables", []),
                "relationships": ext.get("relationships", []),
                "master_dimensions": ext.get("master_dimensions", []),
                "master_measures": ext.get("master_measures", []),
                "variables": ext.get("variables", []),
            },
            "visual_catalog": {
                "sheets": ext.get("sheets", []),
            },
            "feature_compatibility": {
                "summary": ext.get("compatibility_summary", {}),
                "findings": ext.get("findings", []),
            },
        }

    def generate(
        self,
        canonical_ir_input: Union[str, Dict[str, Any]],
        target_explore_name: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes Stage 2 target code generation from an OKF `.md` file, OKF directory,
        JSON file path, or in-memory IR dictionary.
        """
        if isinstance(canonical_ir_input, str):
            if canonical_ir_input.lstrip().startswith("---"):
                canonical_ir = self._hydrate_ir_from_okf_app_markdown(canonical_ir_input)
            elif os.path.isdir(canonical_ir_input):
                return self.generate_from_okf_catalog(canonical_ir_input, output_dir=output_dir)
            elif canonical_ir_input.endswith(".md"):
                with open(canonical_ir_input, "r", encoding="utf-8") as f:
                    canonical_ir = self._hydrate_ir_from_okf_app_markdown(f.read())
            else:
                with open(canonical_ir_input, "r", encoding="utf-8") as f:
                    canonical_ir = json.load(f)
        else:
            canonical_ir = canonical_ir_input

        # If the app is bound to a Canonical Explore from Stage 1.5, honor its target explore name
        if not target_explore_name:
            bound = canonical_ir.get("app_metadata", {}).get("bound_explore", "")
            if bound:
                bound_slug = bound.split("/")[-1].replace(".md", "")
                if bound_slug.startswith("canonical_"):
                    bound_slug = bound_slug[len("canonical_"):]
                target_explore_name = bound_slug

        # 1. Compile LookML Explore & Model
        explore_result = self.explore_compiler.compile_explore(
            canonical_ir=canonical_ir,
            target_explore_name=target_explore_name,
        )
        explore_name = explore_result["explore_name"]
        root_view_name = explore_result["root_view"]

        # 2. Compile LookML Views
        views = self.view_compiler.compile_views(canonical_ir=canonical_ir)

        # 3. Compile LookML Dashboards (bound strictly to explore_name)
        dashboards = self.dashboard_compiler.compile_dashboards(
            canonical_ir=canonical_ir,
            explore_name=explore_name,
            root_view_name=root_view_name,
        )

        # 4. Compile dbt Blueprints
        dbt_models = self.dbt_compiler.compile_blueprints(canonical_ir=canonical_ir)

        artifacts = {
            "model": {
                f"{self.model_name}.model.lkml": explore_result["model_lkml"],
            },
            "explores": {
                f"{explore_name}.explore.lkml": explore_result["explore_lkml"],
            },
            "views": views,
            "dashboards": dashboards,
            "dbt_models": dbt_models,
            "metadata": {
                "explore_name": explore_name,
                "root_view": root_view_name,
                "is_single_view": explore_result["is_single_view"],
                "total_views": len(views),
                "total_dashboards": len(dashboards),
            },
        }

        if output_dir:
            self._write_artifacts(artifacts, output_dir)

        return artifacts

    def generate_from_okf_catalog(
        self,
        okf_source: Union[str, Dict[str, str]],
        output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        FLEET-SCALE STAGE 2 COMPILER:
        Consumes a complete OKF v0.2 Catalog (`okf_catalog/` directory or `{rel_path: md_text}` map)
        and synthesizes:
        1. ONE shared LookML View per `tables/<slug>.md` (zero duplicate Views across 500 apps)
        2. ONE Canonical LookML Explore per `explores/<slug>.md` (15-30 Explores instead of 500)
        3. All applications' LookML Dashboards from `apps/<app_id>.md` bound to their Canonical Explore
        4. Shared upstream dbt models per `tables/<slug>.md`
        """
        files_map: Dict[str, str] = {}
        if isinstance(okf_source, str):
            for sub in ("explores", "tables", "metrics", "apps"):
                sub_dir = os.path.join(okf_source, sub)
                if not os.path.isdir(sub_dir):
                    continue
                for fname in sorted(os.listdir(sub_dir)):
                    if fname.endswith(".md"):
                        rel = f"{sub}/{fname}"
                        with open(os.path.join(sub_dir, fname), "r", encoding="utf-8") as f:
                            files_map[rel] = f.read()
        else:
            files_map = {k.replace("\\", "/").lstrip("/"): v for k, v in okf_source.items()}

        shared_tables: List[Dict[str, Any]] = []
        shared_measures: List[Dict[str, Any]] = []
        canonical_explores_parsed: Dict[str, Dict[str, Any]] = {}
        app_irs: List[Dict[str, Any]] = []

        for rel_path, md_text in sorted(files_map.items()):
            parsed = parse_okf_document(md_text)
            fm = parsed.get("frontmatter", {})
            ext = parsed.get("extracted", {})
            gov = parsed.get("governance", {})

            if rel_path.startswith("tables/"):
                shared_tables.append({
                    "name": gov.get("lookml_view_name") or ext.get("table_name") or fm.get("title", "table"),
                    "is_fact": bool(ext.get("is_fact", False)),
                    "row_count": int(ext.get("row_count", 0)),
                    "fields": ext.get("fields", []),
                    "keys": ext.get("keys", []),
                    "description": fm.get("description", ""),
                    "curated_notes": parsed.get("curated_notes", ""),
                })
            elif rel_path.startswith("metrics/"):
                shared_measures.append({
                    "id": ext.get("measure_id") or gov.get("lookml_measure_name"),
                    "title": fm.get("title", "Measure"),
                    "expression": ext.get("qlik_expression", "Sum(value)"),
                })
            elif rel_path.startswith("explores/"):
                exp_key = rel_path[:-3]
                canonical_explores_parsed[exp_key] = {
                    "rel_path": rel_path,
                    "title": fm.get("title", exp_key),
                    "description": fm.get("description", ""),
                    "explore_name": gov.get("explore_name") or concept_slug(fm.get("title", "explore")),
                    "base_view": (gov.get("base_view") or "").split("/")[-1],
                    "joins": gov.get("joins", []),
                    "curated_notes": parsed.get("curated_notes", ""),
                }
            elif rel_path.startswith("apps/"):
                app_irs.append(self._hydrate_ir_from_okf_app_markdown(md_text))

        # 1. Compile Deduplicated Shared Views & dbt Models from `tables/*.md`
        synthetic_fleet_ir = {
            "ir_version": "3.0-OKF",
            "contract_type": "OPEN_KNOWLEDGE_FORMAT_OKF",
            "app_metadata": {"app_id": "fleet_okf", "app_name": "Enterprise Fleet OKF Semantic Layer"},
            "data_layer": {
                "tables": shared_tables,
                "relationships": [],
                "master_dimensions": [],
                "master_measures": shared_measures,
                "variables": [],
            },
            "visual_catalog": {"sheets": []},
        }
        all_views = self.view_compiler.compile_views(synthetic_fleet_ir) if shared_tables else {}
        all_dbt = self.dbt_compiler.compile_blueprints(synthetic_fleet_ir) if shared_tables else {}

        # 2. Compile Canonical Explores from `explores/*.md`
        all_explores: Dict[str, str] = {}
        explore_lookup: Dict[str, Tuple[str, str]] = {}  # exp_key -> (explore_name, base_view)
        for exp_key, exp_info in canonical_explores_parsed.items():
            exp_name = exp_info["explore_name"]
            base_view = exp_info["base_view"] or exp_name
            explore_lookup[exp_key] = (exp_name, base_view)

            lines = [
                f"# Canonical Looker Explore synthesized from OKF: {exp_info['rel_path']}",
                f"# {exp_info['description']}",
                f"include: \"/views/*.view.lkml\"",
                "",
                f"explore: {exp_name} {{",
                f"  label: \"{exp_info['title']}\"",
                f"  view_name: {base_view}",
            ]
            for j in exp_info.get("joins", []):
                j_view = j.get("view_name") or (j.get("view", "").split("/")[-1])
                if not j_view or j_view == base_view:
                    continue
                j_type = j.get("type", "left_outer")
                j_rel = j.get("relationship", "many_to_one")
                j_on = j.get("sql_on") or f"${{{base_view}.id}} = ${{{j_view}.id}}"
                lines.extend([
                    "",
                    f"  join: {j_view} {{",
                    f"    type: {j_type}",
                    f"    relationship: {j_rel}",
                    f"    sql_on: {j_on} ;;",
                    "  }",
                ])
            lines.append("}")
            all_explores[f"{exp_name}.explore.lkml"] = "\n".join(lines) + "\n"

        # 3. Compile Dashboards for all Apps bound to their Canonical Explore
        all_dashboards: Dict[str, str] = {}
        for app_ir in app_irs:
            if not all_views and app_ir.get("data_layer", {}).get("tables"):
                all_views.update(self.view_compiler.compile_views(app_ir))
                all_dbt.update(self.dbt_compiler.compile_blueprints(app_ir))

            bound_key = app_ir.get("app_metadata", {}).get("bound_explore", "")
            if bound_key in explore_lookup:
                exp_name, root_view = explore_lookup[bound_key]
            elif explore_lookup:
                exp_name, root_view = next(iter(explore_lookup.values()))
            else:
                res = self.explore_compiler.compile_explore(app_ir)
                exp_name = res["explore_name"]
                root_view = res["root_view"]
                all_explores[f"{exp_name}.explore.lkml"] = res["explore_lkml"]

            dashes = self.dashboard_compiler.compile_dashboards(
                canonical_ir=app_ir,
                explore_name=exp_name,
                root_view_name=root_view,
            )
            all_dashboards.update(dashes)

        model_lkml = "\n".join([
            f"connection: \"enterprise_cloud_dw\"",
            "include: \"/views/*.view.lkml\"",
            "include: \"/explores/*.explore.lkml\"",
            "include: \"/dashboards/*.dashboard.lookml\"",
            "",
        ])

        artifacts = {
            "model": {f"{self.model_name}.model.lkml": model_lkml},
            "explores": all_explores,
            "views": all_views,
            "dashboards": all_dashboards,
            "dbt_models": all_dbt,
            "metadata": {
                "okf_version": "0.2",
                "total_canonical_explores": len(all_explores),
                "total_views": len(all_views),
                "total_dashboards": len(all_dashboards),
                "total_apps_compiled": len(app_irs),
            },
        }

        if output_dir:
            self._write_artifacts(artifacts, output_dir)

        return artifacts

    def _write_artifacts(self, artifacts: Dict[str, Any], base_dir: str):
        os.makedirs(os.path.join(base_dir, "models"), exist_ok=True)
        os.makedirs(os.path.join(base_dir, "explores"), exist_ok=True)
        os.makedirs(os.path.join(base_dir, "views"), exist_ok=True)
        os.makedirs(os.path.join(base_dir, "dashboards"), exist_ok=True)
        os.makedirs(os.path.join(base_dir, "dbt"), exist_ok=True)

        for fname, content in artifacts["model"].items():
            with open(os.path.join(base_dir, "models", fname), "w", encoding="utf-8") as f:
                f.write(content)

        for fname, content in artifacts.get("explores", {}).items():
            with open(os.path.join(base_dir, "explores", fname), "w", encoding="utf-8") as f:
                f.write(content)

        for fname, content in artifacts["views"].items():
            with open(os.path.join(base_dir, "views", fname), "w", encoding="utf-8") as f:
                f.write(content)

        for fname, content in artifacts["dashboards"].items():
            with open(os.path.join(base_dir, "dashboards", fname), "w", encoding="utf-8") as f:
                f.write(content)

        for fname, content in artifacts["dbt_models"].items():
            with open(os.path.join(base_dir, "dbt", fname), "w", encoding="utf-8") as f:
                f.write(content)
