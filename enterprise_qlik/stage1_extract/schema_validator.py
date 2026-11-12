"""
Canonical IR Schema Validator
=============================
Validates Canonical Intermediate Representation (IR) structures against the
formal Canonical IR specification (Draft 2020-12 compatible validator).
Zero external dependencies (pure standard library).
"""

import json
import os
from typing import Any, Dict, List, Tuple


def get_canonical_schema() -> Dict[str, Any]:
    """Loads the canonical schema JSON definition."""
    schema_path = os.path.join(os.path.dirname(__file__), "canonical_schema.json")
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_canonical_ir(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validates that a dictionary conforms to the Canonical IR contract.
    Returns (is_valid, list_of_errors).
    """
    errors: List[str] = []

    # 1. Check Root Fields
    required_root = ["ir_version", "contract_type", "app_metadata", "data_layer", "visual_catalog"]
    for field in required_root:
        if field not in data:
            errors.append(f"Missing mandatory root field: '{field}'")

    if data.get("ir_version") != "2.0":
        errors.append(f"Unsupported ir_version: '{data.get('ir_version')}'. Expected '2.0'.")

    if data.get("contract_type") != "OPEN_CANONICAL_IR":
        errors.append(f"Invalid contract_type: '{data.get('contract_type')}'. Expected 'OPEN_CANONICAL_IR'.")

    # 2. Check app_metadata
    meta = data.get("app_metadata", {})
    if not isinstance(meta, dict):
        errors.append("'app_metadata' must be an object.")
    else:
        for f in ["app_id", "app_name"]:
            if f not in meta:
                errors.append(f"Missing mandatory field in app_metadata: '{f}'")

    # 3. Check data_layer
    dl = data.get("data_layer", {})
    if not isinstance(dl, dict):
        errors.append("'data_layer' must be an object.")
    else:
        tables = dl.get("tables", [])
        if not isinstance(tables, list):
            errors.append("'data_layer.tables' must be a list.")
        else:
            for i, tbl in enumerate(tables):
                if not isinstance(tbl, dict) or "name" not in tbl or "fields" not in tbl:
                    errors.append(f"Table index {i} missing 'name' or 'fields'.")

    # 4. Check visual_catalog
    vc = data.get("visual_catalog", {})
    if not isinstance(vc, dict):
        errors.append("'visual_catalog' must be an object.")
    else:
        sheets = vc.get("sheets", [])
        if not isinstance(sheets, list):
            errors.append("'visual_catalog.sheets' must be a list.")
        else:
            for s_idx, s in enumerate(sheets):
                if not isinstance(s, dict) or "sheet_id" not in s or "widgets" not in s:
                    errors.append(f"Sheet index {s_idx} missing 'sheet_id' or 'widgets'.")
                else:
                    for w_idx, w in enumerate(s.get("widgets", [])):
                        if not isinstance(w, dict) or "widget_id" not in w or "layout" not in w:
                            errors.append(f"Widget {w_idx} in sheet {s.get('sheet_id')} missing 'widget_id' or 'layout'.")

    return (len(errors) == 0, errors)
