"""
LookML Dashboard Compiler (Explore-Centric Dashboard Generation)
==============================================================
Compiles Canonical IR Visual Catalog into production LookML Dashboards (.dashboard.lookml):
- Binds EVERY tile explicitly to `model:` and `explore:` (never isolated raw views)
- Uses qualified field identifiers: `${view_name.field_name}`
- Positions tiles using Looker's 12-column newspaper layout (col, row, width, height)
- Translates Qlik chart types into native Looker visualization definitions

Consumes ONLY the Canonical IR dictionary.
"""

import re
from typing import Any, Dict, List, Optional


class DashboardCompiler:
    """Compiles Visual Catalog sheets into LookML dashboard files."""

    def __init__(self, model_name: str = "enterprise_analytics"):
        self.model_name = model_name

    def compile_dashboards(
        self,
        canonical_ir: Dict[str, Any],
        explore_name: str,
        root_view_name: str,
    ) -> Dict[str, str]:
        """
        Compiles each sheet in the visual catalog into a .dashboard.lookml file.
        Returns: { filename: lookml_content }
        """
        visual_catalog = canonical_ir.get("visual_catalog", {})
        sheets = visual_catalog.get("sheets", [])
        app_name = canonical_ir.get("app_metadata", {}).get("app_name", "Analytics Dashboard")

        dashboards: Dict[str, str] = {}

        for s in sheets:
            sheet_title = s.get("title", "Dashboard")
            sheet_id = s.get("sheet_id", "sheet_01")
            dash_id = self._clean_id(sheet_title)

            content = self._compile_single_dashboard(
                sheet=s,
                dash_id=dash_id,
                app_name=app_name,
                explore_name=explore_name,
                root_view_name=root_view_name,
            )
            dashboards[f"{dash_id}.dashboard.lookml"] = content

        return dashboards

    def _compile_single_dashboard(
        self,
        sheet: Dict[str, Any],
        dash_id: str,
        app_name: str,
        explore_name: str,
        root_view_name: str,
    ) -> str:
        sheet_title = sheet.get("title", "Dashboard")
        widgets = sheet.get("widgets", [])

        lines = [
            f"- dashboard: {dash_id}",
            f'  title: "{sheet_title}"',
            f'  layout: newspaper',
            f'  preferred_viewer: dashboards-next',
            f'  description: "Migrated from Qlik App: {app_name} - Sheet: {sheet_title}"',
            f"  elements:",
        ]

        for w in widgets:
            w_id = self._clean_id(w.get("title", w.get("widget_id", "tile")))
            w_title = w.get("title", "Untitled Tile")
            w_type = w.get("type", "looker_column")
            layout = w.get("layout", {})

            col = layout.get("looker_col", 0)
            row = layout.get("looker_row", 0)
            width = layout.get("looker_width", 6)
            height = layout.get("looker_height", 6)

            # Skip filterpanes or action buttons from visualization tiles (they become dashboard filters)
            if w.get("source_type") in ("filterpane", "action-button"):
                continue

            lines.append(f"  - title: \"{w_title}\"")
            lines.append(f"    name: {w_id}")
            lines.append(f"    model: {self.model_name}")
            # EXPLORE BINDING: Critical Looker semantic requirement
            lines.append(f"    explore: {explore_name}")
            lines.append(f"    type: {w_type}")

            # Collect dimensions and measures
            dims = [f"{root_view_name}.{self._clean_id(d.get('field', 'dim'))}" for d in w.get("dimensions", [])]
            meas = [f"{root_view_name}.{self._clean_id(m.get('label', 'total_sales'))}" for m in w.get("measures", [])]

            if dims:
                lines.append(f"    dimensions: [{', '.join(dims)}]")
            if meas:
                lines.append(f"    measures: [{', '.join(meas)}]")
            elif not dims and not meas:
                lines.append(f"    measures: [{root_view_name}.count]")

            if meas:
                lines.append(f"    sorts: [{meas[0]} desc]")
            lines.append(f"    limit: 500")

            # Positioning in 12-column grid
            lines.append(f"    row: {row}")
            lines.append(f"    col: {col}")
            lines.append(f"    width: {width}")
            lines.append(f"    height: {height}")
            lines.append("")

        return "\n".join(lines)

    def _clean_id(self, text: str) -> str:
        s = re.sub(r"[^a-zA-Z0-9_]", "_", text.strip().lower())
        return re.sub(r"_+", "_", s).strip("_")
