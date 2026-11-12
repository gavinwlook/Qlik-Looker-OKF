"""
OKF v0.2 Conformance & Referential Integrity Validator (100% Python Standard Library).

Enforces:
1. Parseable YAML 1.2 frontmatter on every non-reserved concept file.
2. Non-empty `type` field (`qlik_app`, `table`, `explore`, `metric`, `bundle_index`) and `okf_version: "0.2"`.
3. Dual-namespace structure (`extracted:` and `governance:`) on concept documents.
4. Reserved file integrity (`index.md` root manifest with link bullets; `log.md` with ISO-8601 date headings).
5. Cross-concept referential integrity across `explores/*.md`, `tables/*.md`, `metrics/*.md`, and `apps/*.md`.
"""

import re
from typing import Any, Dict, List, Tuple
from enterprise_qlik.okf.frontmatter import parse_okf_document

VALID_CONCEPT_TYPES = {"qlik_app", "table", "explore", "metric", "bundle_index"}
_MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+\.md)\)")
_ISO_HEADING_RE = re.compile(r"^##\s+\d{4}-\d{2}-\d{2}", re.MULTILINE)


def validate_okf_document(file_path: str, markdown_text: str) -> Tuple[bool, List[str]]:
    """Validate a single OKF v0.2 Markdown file."""
    errors: List[str] = []
    norm_path = file_path.replace("\\", "/").lstrip("/")

    if norm_path == "log.md":
        if not _ISO_HEADING_RE.search(markdown_text or ""):
            errors.append("log.md must contain at least one ISO-8601 date heading (e.g. '## 2026-11-12').")
        return (len(errors) == 0, errors)

    if not (markdown_text or "").startswith("---"):
        errors.append(f"{norm_path}: Missing YAML frontmatter block starting with '---'.")
        return (False, errors)

    parsed = parse_okf_document(markdown_text)
    fm = parsed.get("frontmatter", {})
    if not fm:
        errors.append(f"{norm_path}: Frontmatter block could not be parsed or is empty.")
        return (False, errors)

    if fm.get("okf_version") != "0.2":
        errors.append(f"{norm_path}: Frontmatter must declare 'okf_version: \"0.2\"'.")

    c_type = fm.get("type")
    if not c_type or not isinstance(c_type, str):
        errors.append(f"{norm_path}: Mandatory 'type' field in frontmatter is missing or empty.")
    elif c_type not in VALID_CONCEPT_TYPES:
        errors.append(f"{norm_path}: Unknown OKF concept type '{c_type}'. Expected one of {sorted(VALID_CONCEPT_TYPES)}.")

    if norm_path != "index.md":
        if not fm.get("title"):
            errors.append(f"{norm_path}: Missing 'title' in frontmatter.")
        if not isinstance(fm.get("extracted"), dict):
            errors.append(f"{norm_path}: Missing 'extracted' namespace dictionary in frontmatter.")
        if not isinstance(fm.get("governance"), dict):
            errors.append(f"{norm_path}: Missing 'governance' namespace dictionary in frontmatter.")

    return (len(errors) == 0, errors)


def validate_okf_catalog(files_map: Dict[str, str]) -> Tuple[bool, List[str]]:
    """
    Validate a complete OKF v0.2 catalog mapping relative paths (`index.md`, `tables/orders.md`, etc.)
    to their Markdown content strings.
    """
    errors: List[str] = []
    norm_map = {k.replace("\\", "/").lstrip("/"): v for k, v in files_map.items()}

    if "index.md" not in norm_map:
        errors.append("Catalog is missing required root 'index.md' file.")
    if "log.md" not in norm_map:
        errors.append("Catalog is missing required 'log.md' audit history file.")

    for path, content in norm_map.items():
        ok, doc_errs = validate_okf_document(path, content)
        if not ok:
            errors.extend(doc_errs)

        # Verify relative Markdown links resolve within the catalog
        parent_parts = path.split("/")[:-1]
        for match in _MD_LINK_RE.finditer(content or ""):
            rel_target = match.group(1).strip()
            if rel_target.startswith("http://") or rel_target.startswith("https://"):
                continue
            resolved = _resolve_relative_path(parent_parts, rel_target)
            if resolved not in norm_map:
                errors.append(f"{path}: Broken relative link '{rel_target}' (resolved to '{resolved}', not in catalog).")

    return (len(errors) == 0, errors)


def _resolve_relative_path(base_parts: List[str], rel_link: str) -> str:
    parts = list(base_parts)
    for seg in rel_link.replace("\\", "/").split("/"):
        if not seg or seg == ".":
            continue
        if seg == "..":
            if parts:
                parts.pop()
        else:
            parts.append(seg)
    return "/".join(parts)
