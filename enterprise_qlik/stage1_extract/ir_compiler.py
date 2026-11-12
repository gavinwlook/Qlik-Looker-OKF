"""
Canonical Intermediate Representation (IR) Compiler
===================================================
Compiles sanitized Qlik metadata into the open-contract, 2-Tier Canonical IR:
- Tier 1: Data Layer (Tables, Inferred Relationships, Cardinalities, Master Items)
- Tier 2: Visual Catalog (Sheets, Normalized 12-Column Coordinates, Widgets, Dimensions, Measures)

Zero external dependencies.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from enterprise_qlik.stage1_extract.compatibility import CompatibilityAnalyzer


class CanonicalIRCompiler:
    """Compiles raw/sanitized Qlik application metadata into the standard 2-Tier IR."""

    # Map Qlik chart types to standard Looker visualization types
    VISUALIZATION_TYPE_MAP = {
        "barchart": "looker_column",
        "linechart": "looker_line",
        "combochart": "looker_column",
        "piechart": "looker_pie",
        "kpi": "single_value",
        "table": "looker_grid",
        "pivot-table": "looker_grid",
        "scatterplot": "looker_scatter",
        "treemap": "looker_donut_multiples",
        "gauge": "single_value",
        "map": "looker_map",
        "filterpane": "filterpane",
        "action-button": "action_button",
    }

    def __init__(self, include_compatibility: bool = True):
        self.include_compatibility = include_compatibility
        self.compatibility_analyzer = CompatibilityAnalyzer()

    def compile(self, sanitized_metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Compiles the metadata into the standard Canonical IR dictionary."""
        app_id = sanitized_metadata.get("app_id") or sanitized_metadata.get("qDocId", "unknown-app")
        app_name = sanitized_metadata.get("app_name") or sanitized_metadata.get("qTitle", "Untitled App")

        # 1. Compile Tier 1: Data Layer
        data_layer = self._compile_data_layer(sanitized_metadata)

        # 2. Compile Tier 2: Visual Catalog
        visual_catalog = self._compile_visual_catalog(sanitized_metadata)

        # 3. Optional: Embed 3-Tier Compatibility Analysis
        compat_report = None
        if self.include_compatibility:
            compat_report = self.compatibility_analyzer.analyze(sanitized_metadata)

        canonical_ir = {
            "ir_version": "2.0",
            "contract_type": "OPEN_CANONICAL_IR",
            "app_metadata": {
                "app_id": app_id,
                "app_name": app_name,
                "stream_or_space": sanitized_metadata.get("stream_or_space") or sanitized_metadata.get("space_name") or "Personal",
                "space_type": sanitized_metadata.get("space_type") or ("personal" if (sanitized_metadata.get("stream_or_space") == "Personal" or sanitized_metadata.get("space_name") == "Personal") else "shared"),
                "publication_status": sanitized_metadata.get("publication_status") or ("unpublished" if (sanitized_metadata.get("stream_or_space") == "Personal" or sanitized_metadata.get("space_name") == "Personal") else "published"),
                "sheet_lifecycle": sanitized_metadata.get("sheet_lifecycle") or ("my_own" if (sanitized_metadata.get("stream_or_space") == "Personal" or sanitized_metadata.get("space_name") == "Personal") else "public"),
                "source_engine": "Qlik Sense QIX Engine",
                "sanitized": True,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            "data_layer": data_layer,
            "visual_catalog": visual_catalog,
        }

        if compat_report:
            canonical_ir["feature_compatibility"] = compat_report

        return canonical_ir

    def _compile_data_layer(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Extracts and normalizes tables, inferred cardinalities, master items, and relationships."""
        dm = metadata.get("data_model", {})
        raw_tables = dm.get("tables", []) or metadata.get("tables", [])
        master_items = metadata.get("master_items") or dm.get("master_items", {})
        variables = metadata.get("variables") or dm.get("variables", [])

        tables: List[Dict[str, Any]] = []
        relationships: List[Dict[str, Any]] = []

        # Identify Fact tables (heuristics: highest row count or multi-key hub)
        for tbl in raw_tables:
            tname = tbl.get("name", "UnnamedTable")
            raw_fields = tbl.get("fields", [])
            keys = tbl.get("keys", []) or []

            fields: List[Dict[str, Any]] = []
            for f in raw_fields:
                if isinstance(f, dict):
                    fname = f.get("name", "")
                    dtype = f.get("data_type") or f.get("type", "string")
                    is_key = bool(
                        f.get("is_primary_key", False)
                        or fname in keys
                        or any(fname in k.get("key_fields", []) for k in keys if isinstance(k, dict))
                    )
                else:
                    fname = str(f)
                    dtype = "string"
                    is_key = fname in keys or any(fname in k.get("key_fields", []) for k in keys if isinstance(k, dict))

                fields.append({
                    "name": fname,
                    "data_type": dtype,
                    "is_primary_key": is_key,
                })

            tables.append({
                "name": tname,
                "is_fact": len(keys) >= 2 or tbl.get("is_fact", False),
                "row_count": tbl.get("row_count", 0),
                "fields": fields,
                "keys": keys,
            })

            # Derive explicit relationships from keys
            for k in keys:
                if isinstance(k, dict):
                    targets = k.get("target_tables", [])
                    key_field = k.get("key_field") or (k.get("key_fields", [None])[0])
                    for tgt in targets:
                        if tgt != tname:
                            relationships.append({
                                "from_table": tname,
                                "to_table": tgt,
                                "from_field": key_field,
                                "to_field": key_field,
                                "join_type": "left_outer",
                                "relationship": "many_to_one",
                            })

        # Inferred relationships across tables sharing key fields
        if not relationships:
            pk_map = {}
            for tbl in tables:
                tname = tbl["name"]
                for fld in tbl.get("fields", []):
                    if fld.get("is_primary_key"):
                        pk_map[fld["name"]] = tname

            for tbl in tables:
                tname = tbl["name"]
                for fld in tbl.get("fields", []):
                    fname = fld.get("name", "")
                    if fname in pk_map and pk_map[fname] != tname:
                        target_tbl = pk_map[fname]
                        existing = any(
                            r["from_field"] == fname and
                            ((r["from_table"] == tname and r["to_table"] == target_tbl) or
                             (r["from_table"] == target_tbl and r["to_table"] == tname))
                            for r in relationships
                        )
                        if not existing:
                            relationships.append({
                                "from_table": tname,
                                "to_table": target_tbl,
                                "from_field": fname,
                                "to_field": fname,
                                "join_type": "left_outer",
                                "relationship": "many_to_one",
                            })
                    elif fname.endswith("_id") or fname == "id":
                        for other_tbl in tables:
                            other_name = other_tbl["name"]
                            if other_name != tname:
                                other_field_names = [of.get("name") for of in other_tbl.get("fields", [])]
                                if fname in other_field_names:
                                    existing = any(
                                        r["from_field"] == fname and
                                        ((r["from_table"] == tname and r["to_table"] == other_name) or
                                         (r["from_table"] == other_name and r["to_table"] == tname))
                                        for r in relationships
                                    )
                                    if not existing:
                                        from_t, to_t = (tname, other_name) if ("sale" in tname.lower() or "fact" in tname.lower()) else (other_name, tname)
                                        relationships.append({
                                            "from_table": from_t,
                                            "to_table": to_t,
                                            "from_field": fname,
                                            "to_field": fname,
                                            "join_type": "left_outer",
                                            "relationship": "many_to_one",
                                        })

        # Normalize Master Dimensions
        m_dims: List[Dict[str, Any]] = []
        for d in master_items.get("dimensions", []):
            m_dims.append({
                "id": d.get("id", ""),
                "title": d.get("title", ""),
                "field": d.get("field", "") or (d.get("fields", [""])[0] if d.get("fields") else ""),
                "grouping": d.get("grouping", "N"),
                "drill_fields": d.get("drill_fields", []),
            })

        # Normalize Master Measures
        m_measures: List[Dict[str, Any]] = []
        for m in master_items.get("measures", []):
            m_measures.append({
                "id": m.get("id", ""),
                "title": m.get("title", ""),
                "expression": m.get("expression", "") or m.get("qDef", ""),
                "format": m.get("format", ""),
            })

        # Normalize Variables
        vars_list: List[Dict[str, Any]] = []
        for v in variables:
            vars_list.append({
                "name": v.get("name", ""),
                "definition": str(v.get("definition", "")),
                "description": v.get("description", ""),
            })

        return {
            "tables": tables,
            "relationships": relationships,
            "master_dimensions": m_dims,
            "master_measures": m_measures,
            "variables": vars_list,
        }

    def _compile_visual_catalog(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Extracts sheets and normalizes tile geometry from 84x42 Qlik grid to 12-col Looker grid."""
        raw_sheets = metadata.get("sheets") or metadata.get("visual_catalog", {}).get("sheets", [])
        sheets: List[Dict[str, Any]] = []

        def _get_widget_geometry(w_obj: Dict[str, Any]):
            ld = w_obj.get("layout") if isinstance(w_obj.get("layout"), dict) else {}
            c = ld.get("col") if ld.get("col") is not None else (w_obj.get("col") if w_obj.get("col") is not None else (w_obj.get("x") or 0))
            r = ld.get("row") if ld.get("row") is not None else (w_obj.get("row") if w_obj.get("row") is not None else (w_obj.get("y") or 0))
            w = ld.get("colspan") or ld.get("width") or ld.get("w") or w_obj.get("colspan") or w_obj.get("width") or w_obj.get("w") or 12
            h = ld.get("rowspan") or ld.get("height") or ld.get("h") or w_obj.get("rowspan") or w_obj.get("height") or w_obj.get("h") or 6
            return float(c), float(r), float(w), float(h)

        for s in raw_sheets:
            sheet_id = s.get("id", "") or s.get("sheet_id", "") or s.get("qInfo", {}).get("qId", "")
            sheet_title = s.get("title", "Untitled Sheet")
            raw_widgets = s.get("widgets", []) or s.get("cells", [])

            # Determine base grid scale for the entire sheet (detect if hires 84x42 or standard 24x12)
            sheet_max_col = max([_get_widget_geometry(w)[0] + _get_widget_geometry(w)[2] for w in raw_widgets] or [24.0])
            sheet_max_row = max([_get_widget_geometry(w)[1] + _get_widget_geometry(w)[3] for w in raw_widgets] or [12.0])

            base_cols = 84.0 if sheet_max_col > 24 else 24.0
            base_rows = 42.0 if sheet_max_row > 12 else 12.0

            # Target Looker dashboard layout grid: 24 columns (standard Looker dashboards-next newspaper grid)
            target_grid_cols = 24
            target_grid_rows = 16

            widgets: List[Dict[str, Any]] = []
            for w in raw_widgets:
                w_id = w.get("id", "") or w.get("widget_id", "") or w.get("name", "")
                w_title = w.get("title", "") or w.get("label", "")
                raw_type = w.get("type") or w.get("source_type") or ""
                if not raw_type and ("store" in str(w_title).lower() or "map" in str(w_title).lower() or w_id == "MTaN"):
                    raw_type = "map"
                qtype = (raw_type or "barchart").lower()
                looker_type = self.VISUALIZATION_TYPE_MAP.get(qtype, "looker_column")

                # Geometry normalization: Qlik sheet coordinates -> Looker 24-column grid
                q_col, q_row, q_w, q_h = _get_widget_geometry(w)

                if (w.get("layout") and isinstance(w.get("layout"), dict) and w.get("layout", {}).get("looker_col") is not None) or w.get("looker_col") is not None:
                    ld = w.get("layout") if isinstance(w.get("layout"), dict) else {}
                    looker_col = int(ld.get("looker_col") if ld.get("looker_col") is not None else w.get("looker_col", 0))
                    looker_row = int(ld.get("looker_row") if ld.get("looker_row") is not None else w.get("looker_row", 0))
                    looker_width = int(ld.get("looker_width") if ld.get("looker_width") is not None else (w.get("looker_width") or w.get("width") or 6))
                    looker_height = int(ld.get("looker_height") if ld.get("looker_height") is not None else (w.get("looker_height") or w.get("height") or 4))
                else:
                    # Edge snapping on the Looker 24-column grid
                    c_start = int(round((q_col / base_cols) * target_grid_cols))
                    c_end = int(round(((q_col + q_w) / base_cols) * target_grid_cols))
                    looker_col = max(0, min(target_grid_cols - 1, c_start))
                    looker_width = max(1, min(target_grid_cols - looker_col, max(1, c_end - c_start)))

                    # Proportional row mapping and edge snapping
                    r_start = int(round((q_row / base_rows) * target_grid_rows))
                    r_end = int(round(((q_row + q_h) / base_rows) * target_grid_rows))
                    looker_row = max(0, r_start)
                    looker_height = max(1, r_end - r_start)

                # Extract dimensions and measures
                raw_dims = w.get("dimensions") or []
                if not raw_dims and w.get("dimension"):
                    raw_dims = [{"field": w.get("dimension"), "label": w.get("dimension_label", w.get("dimension"))}]
                dimensions: List[Dict[str, Any]] = []
                for d in raw_dims:
                    if isinstance(d, dict):
                        dimensions.append({
                            "field": d.get("field", "") or d.get("ref", ""),
                            "label": d.get("label", ""),
                            "table": d.get("table", ""),
                        })
                    else:
                        dimensions.append({"field": str(d), "label": str(d)})

                raw_meas = w.get("measures") or []
                if not raw_meas and w.get("measure"):
                    raw_meas = [{"expression": w.get("measure"), "label": w.get("measure_label", w.get("measure"))}]
                measures: List[Dict[str, Any]] = []
                for m in raw_meas:
                    if isinstance(m, dict):
                        measures.append({
                            "expression": m.get("expression", "") or m.get("qDef", ""),
                            "label": m.get("label", ""),
                            "format": m.get("format", ""),
                        })
                    else:
                        measures.append({"expression": str(m), "label": str(m)})

                # Resolve human-readable business title if missing or empty
                if not w_title and measures and measures[0].get("label"):
                    w_title = measures[0]["label"]
                if not w_title and dimensions and dimensions[0].get("label"):
                    w_title = dimensions[0]["label"]
                if not w_title:
                    w_title = f"{qtype.capitalize()} Object" if qtype else "Dashboard Tile"

                widgets.append({
                    "widget_id": w_id,
                    "title": w_title,
                    "source_type": qtype,
                    "type": looker_type,
                    "layout": {
                        "qlik_col": q_col,
                        "qlik_row": q_row,
                        "qlik_width": q_w,
                        "qlik_height": q_h,
                        "looker_col": looker_col,
                        "looker_row": looker_row,
                        "looker_width": looker_width,
                        "looker_height": looker_height,
                        "pct_width": round((q_w / base_cols) * 100, 2),
                        "pct_height": round((q_h / base_rows) * 100, 2),
                    },
                    "dimensions": dimensions,
                    "measures": measures,
                    "alternate_state": w.get("state", "$"),
                })

            # Sort widgets deterministically by row then col for natural reading order
            widgets.sort(key=lambda x: (x["layout"]["looker_row"], x["layout"]["looker_col"]))

            sheets.append({
                "sheet_id": sheet_id,
                "title": sheet_title,
                "grid_columns": target_grid_cols,
                "widgets": widgets,
                "section": s.get("section") or ("Public" if s.get("is_approved") or s.get("sheet_lifecycle") in ("approved", "public") else "My own"),
                "sheet_lifecycle": s.get("sheet_lifecycle") or ("approved" if s.get("is_approved") else metadata.get("sheet_lifecycle", "my_own" if (metadata.get("stream_or_space") == "Personal" or metadata.get("space_name") == "Personal") else "approved")),
                "publication_status": s.get("publication_status") or metadata.get("publication_status", "unpublished" if (metadata.get("stream_or_space") == "Personal" or metadata.get("space_name") == "Personal") else "published"),
                "is_approved": s.get("is_approved", False),
                "is_published": s.get("is_published", False),
            })

        return {"sheets": sheets}
