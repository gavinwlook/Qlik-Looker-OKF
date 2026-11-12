"""
Zero-Dependency OKF v0.2 Frontmatter Serializer, Parser & Dual-Namespace Merger.

Architectural Decisions Implemented:
- ADR-02: Deterministic 32-char ASCII slug + 6-char SHA-256 suffix for collision-free file paths.
- ADR-03: YAML 1.2 frontmatter backed by Python stdlib `json.dumps()` / `json.loads()` scalar encoding
          so complex Qlik Set Analysis expressions (`Sum({$<Year={"$(=Max(Year))"}>} [Net # Sales])`)
          never corrupt YAML structure without requiring PyYAML.
- ADR-05: Dual-namespace partitioning (`extracted:` vs `governance:`) and protected Markdown zones
          (`<!-- BEGIN CURATED NOTES -->` vs `<!-- BEGIN AUTO-GENERATED CATALOG -->`) so Stage 1
          re-extraction never overwrites human/AI curation.
"""

import hashlib
import json
import re
from typing import Any, Dict, Optional, Tuple

CURATED_BEGIN_MARKER = "<!-- BEGIN CURATED NOTES -->"
CURATED_END_MARKER = "<!-- END CURATED NOTES -->"
AUTO_BEGIN_MARKER = "<!-- BEGIN AUTO-GENERATED CATALOG -->"
AUTO_END_MARKER = "<!-- END AUTO-GENERATED CATALOG -->"

_TOP_KEY_ORDER = [
    "okf_version",
    "type",
    "app_id",
    "title",
    "description",
    "status",
    "timestamp",
    "extracted",
    "governance",
]


def compute_sha256(content: str) -> str:
    """Compute hex SHA-256 digest of an OKF document string."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def concept_slug(name: str, max_len: int = 32, disambiguate_seed: Optional[str] = None) -> str:
    """
    Convert an arbitrary Qlik table, metric, explore, or app title into a deterministic,
    filesystem-safe ASCII slug capped at `max_len` characters (+ optional 6-char hash suffix).
    """
    raw = (name or "unnamed").strip()
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", raw.lower()).strip("_")
    if not cleaned:
        cleaned = "concept"

    needs_hash = (
        disambiguate_seed is not None
        or len(cleaned) > max_len
        or any(ch in raw for ch in ("%", "(", ")", "[", "]", "{", "}", "/", "\\", ":"))
    )
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip("_")

    if needs_hash:
        seed = f"{raw}::{disambiguate_seed or ''}"
        short_hash = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:6]
        return f"{cleaned}_{short_hash}"
    return cleaned


def _serialize_yaml12_frontmatter(data: Dict[str, Any]) -> str:
    """
    Emit human-readable YAML 1.2 frontmatter using stdlib `json.dumps` for all scalar and collection
    leaf values. Because YAML 1.2 is a strict superset of JSON, every `json.dumps` value is valid
    YAML 1.2 and can be parsed back deterministically via `json.loads` without third-party packages.
    """
    lines = ["---"]

    ordered_keys = [k for k in _TOP_KEY_ORDER if k in data]
    for k in data:
        if k not in ordered_keys:
            ordered_keys.append(k)

    for key in ordered_keys:
        val = data[key]
        if isinstance(val, dict) and key in ("extracted", "governance", "generated"):
            if not val:
                lines.append(f"{key}: {{}}")
            else:
                lines.append(f"{key}:")
                for sub_key, sub_val in val.items():
                    encoded = json.dumps(sub_val, ensure_ascii=False)
                    lines.append(f"  {sub_key}: {encoded}")
        else:
            encoded = json.dumps(val, ensure_ascii=False)
            lines.append(f"{key}: {encoded}")

    lines.append("---")
    return "\n".join(lines)


def _parse_yaml12_frontmatter(frontmatter_text: str) -> Dict[str, Any]:
    """
    Parse YAML 1.2 frontmatter emitted by `_serialize_yaml12_frontmatter` (or standard YAML).
    Uses stdlib `json.loads` for zero-dependency speed, with optional PyYAML fallback if installed.
    """
    result: Dict[str, Any] = {}
    current_section: Optional[str] = None

    for raw_line in frontmatter_text.splitlines():
        if not raw_line.strip() or raw_line.strip().startswith("#"):
            continue

        # Indented sub-key inside a top-level mapping (e.g. `  sheets_count: 4`)
        if raw_line.startswith("  ") and not raw_line.startswith("    ") and current_section:
            stripped = raw_line.strip()
            if ":" in stripped:
                sub_k, sub_v = stripped.split(":", 1)
                sub_k = sub_k.strip()
                sub_v_str = sub_v.strip()
                result[current_section][sub_k] = _parse_scalar_or_json(sub_v_str)
            continue

        # Top-level key
        if ":" in raw_line:
            k, v = raw_line.split(":", 1)
            k = k.strip()
            v_str = v.strip()
            if v_str == "":
                result[k] = {}
                current_section = k
            else:
                current_section = None
                result[k] = _parse_scalar_or_json(v_str)

    # Optional fallback to PyYAML if someone manually wrote multi-line block lists in YAML
    if not result and frontmatter_text.strip():
        try:
            import yaml  # type: ignore
            loaded = yaml.safe_load(frontmatter_text)
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            pass

    return result


def _parse_scalar_or_json(val_str: str) -> Any:
    """Parse a JSON-encoded YAML 1.2 value or plain unquoted YAML scalar using Python stdlib."""
    if not val_str:
        return None
    try:
        return json.loads(val_str)
    except Exception:
        # Handle single-quoted YAML strings or plain scalars edited manually by humans
        if val_str.startswith("'") and val_str.endswith("'") and len(val_str) >= 2:
            return val_str[1:-1].replace("''", "'")
        low = val_str.lower()
        if low == "true":
            return True
        if low == "false":
            return False
        if low in ("null", "none", "~"):
            return None
        try:
            if "." in val_str:
                return float(val_str)
            return int(val_str)
        except ValueError:
            return val_str


def serialize_okf_document(
    frontmatter: Dict[str, Any],
    curated_notes: str = "",
    auto_catalog: str = "",
) -> str:
    """
    Serialize an OKF v0.2 concept document with structured YAML 1.2 frontmatter,
    a protected human/agent curated Markdown region, and an auto-generated catalog region.
    """
    fm = dict(frontmatter)
    fm.setdefault("okf_version", "0.2")
    if "type" not in fm or not fm["type"]:
        raise ValueError("OKF v0.2 conformance error: 'type' field in frontmatter must be non-empty.")

    fm_block = _serialize_yaml12_frontmatter(fm)
    title = fm.get("title") or fm.get("app_id") or fm.get("type")

    curated_clean = (curated_notes or "").strip()
    if not curated_clean:
        curated_clean = (
            "## Architect & AI Agent Curation Notes\n"
            "_Add domain consolidation notes, field alias overrides, or Category 2 LookML/dbt remediation details here. "
            "This block is preserved across Stage 1 re-extractions._"
        )

    auto_clean = (auto_catalog or "").strip()

    parts = [
        fm_block,
        "",
        f"# {title}",
        "",
        CURATED_BEGIN_MARKER,
        curated_clean,
        CURATED_END_MARKER,
        "",
        AUTO_BEGIN_MARKER,
        auto_clean,
        AUTO_END_MARKER,
        "",
    ]
    return "\n".join(parts)


def _extract_region(body: str, begin_marker: str, end_marker: str) -> Optional[str]:
    start_idx = body.find(begin_marker)
    if start_idx == -1:
        return None
    start_content = start_idx + len(begin_marker)
    end_idx = body.find(end_marker, start_content)
    if end_idx == -1:
        return None
    return body[start_content:end_idx].strip()


def parse_okf_document(markdown_text: str) -> Dict[str, Any]:
    """
    Parse an OKF v0.2 Markdown document into its frontmatter dictionary, curated notes block,
    auto-generated catalog block, raw body, and SHA-256 content hash.
    """
    text = markdown_text or ""
    content_hash = compute_sha256(text)

    frontmatter: Dict[str, Any] = {}
    body = text

    if text.startswith("---\n") or text.startswith("---\r\n"):
        lines = text.splitlines()
        end_line_idx = None
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                end_line_idx = idx
                break
        if end_line_idx is not None:
            fm_text = "\n".join(lines[1:end_line_idx])
            body = "\n".join(lines[end_line_idx + 1 :]).strip()
            frontmatter = _parse_yaml12_frontmatter(fm_text)

    curated_notes = _extract_region(body, CURATED_BEGIN_MARKER, CURATED_END_MARKER) or ""
    auto_catalog = _extract_region(body, AUTO_BEGIN_MARKER, AUTO_END_MARKER) or ""

    return {
        "frontmatter": frontmatter,
        "extracted": frontmatter.get("extracted", {}),
        "governance": frontmatter.get("governance", {}),
        "curated_notes": curated_notes,
        "auto_catalog": auto_catalog,
        "body": body,
        "content_sha256": content_hash,
    }


def merge_okf_reextraction(
    existing_markdown: Optional[str],
    new_frontmatter: Dict[str, Any],
    new_auto_catalog: str,
    default_curated_notes: str = "",
) -> Tuple[str, Dict[str, Any]]:
    """
    Merge a fresh Stage 1 extraction with an existing OKF document on disk.
    Strictly preserves `governance:` frontmatter fields and the `CURATED NOTES` Markdown block
    while updating `extracted:` frontmatter and `AUTO-GENERATED CATALOG`.
    Returns `(merged_markdown, merged_frontmatter)`.
    """
    merged_fm = dict(new_frontmatter)
    merged_fm.setdefault("okf_version", "0.2")
    curated_notes = default_curated_notes

    if existing_markdown:
        parsed_old = parse_okf_document(existing_markdown)
        old_fm = parsed_old.get("frontmatter", {})
        old_gov = old_fm.get("governance", {})
        new_gov = merged_fm.get("governance", {})

        # Preserve all existing human/agent governance decisions
        combined_gov = dict(new_gov)
        for gk, gv in old_gov.items():
            if gv is not None and gv != "" and gv != "Unassigned":
                combined_gov[gk] = gv
            elif gk not in combined_gov:
                combined_gov[gk] = gv
        merged_fm["governance"] = combined_gov

        # Preserve curated status if previously approved
        if old_fm.get("status") in ("approved", "curated"):
            merged_fm["status"] = old_fm["status"]

        if parsed_old.get("curated_notes"):
            curated_notes = parsed_old["curated_notes"]

    doc_text = serialize_okf_document(
        frontmatter=merged_fm,
        curated_notes=curated_notes,
        auto_catalog=new_auto_catalog,
    )
    return doc_text, merged_fm
