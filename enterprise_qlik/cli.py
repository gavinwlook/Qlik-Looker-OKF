"""
Unified Command Line Interface (CLI)
====================================
Modular entrypoint for Stage 1 extraction, Stage 2 code generation,
schema validation, database management, and the Web UI Studio.
"""

import argparse
import json
import os
import sys
from typing import Optional

from enterprise_qlik.stage1_extract.extractor import QIXExtractor
from enterprise_qlik.stage1_extract.ir_compiler import CanonicalIRCompiler
from enterprise_qlik.stage1_extract.compatibility import CompatibilityAnalyzer
from enterprise_qlik.stage1_extract.schema_validator import validate_canonical_ir
from enterprise_qlik.stage2_lookml.generator import LookMLGenerator
from enterprise_qlik.storage.db import DatabaseManager


def main():
    parser = argparse.ArgumentParser(
        prog="enterprise-qlik",
        description="Enterprise Qlik-to-Looker Migration Engine (Decoupled Stage Architecture)",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available migration commands")

    # --- Command: extract (Stage 1) ---
    extract_parser = subparsers.add_parser("extract", help="[Stage 1] Extract metadata, sanitize, and compile Canonical IR")
    extract_parser.add_argument("--app-id", required=True, help="Target Qlik Application ID")
    extract_parser.add_argument("--host", default="http://localhost:4848", help="Qlik Sense host URL")
    extract_parser.add_argument("--token", help="Qlik Cloud API Key or Bearer Token")
    extract_parser.add_argument("--sample", action="store_true", help="Generate and compile realistic enterprise sample app")
    extract_parser.add_argument("--input-file", help="Path to raw Qlik metadata JSON file")
    extract_parser.add_argument("--output-dir", default="./migration_artifacts", help="Output directory for Canonical IR bundle")
    extract_parser.add_argument("--db-path", default="enterprise_migration.db", help="Path to SQLite application database")

    # --- Command: discover (Fleet Discovery) ---
    disc_parser = subparsers.add_parser("discover", help="Discover Qlik applications from the active instance/tenant")
    disc_parser.add_argument("--db-path", default="enterprise_migration.db", help="Path to SQLite database")

    # --- Command: audit (Stage 1 Gap Report) ---
    audit_parser = subparsers.add_parser("audit", help="[Stage 1] Run 3-Tier Compatibility Gap Audit")
    audit_parser.add_argument("--input-file", required=True, help="Path to Qlik metadata or Canonical IR JSON")
    audit_parser.add_argument("--output-file", help="Path to write gap report JSON")

    # --- Command: validate (OKF v0.2 Catalog or IR Schema) ---
    val_parser = subparsers.add_parser("validate", help="Validate an OKF v0.2 catalog directory or IR file")
    val_parser.add_argument("--ir-file", required=True, help="Path to okf_catalog/ directory or IR file")

    # --- Command: reconcile-okf (Stage 1.5 Fleet Explore Consolidation) ---
    rec_parser = subparsers.add_parser("reconcile-okf", help="[Stage 1.5] Reconcile extracted fleet OKF catalog into minimal Canonical Looker Explores")
    rec_parser.add_argument("--db-path", default="enterprise_migration.db", help="Path to SQLite database")
    rec_parser.add_argument("--catalog-dir", default="./okf_catalog", help="Path to OKF v0.2 catalog directory")
    rec_parser.add_argument("--threshold", type=float, default=0.45, help="Table overlap Jaccard similarity threshold (default: 0.45)")

    # --- Command: generate (Stage 2) ---
    gen_parser = subparsers.add_parser("generate", help="[Stage 2] Generate deduplicated LookML Explores, Views, Dashboards & dbt models from OKF Catalog or IR")
    gen_parser.add_argument("--ir-file", required=True, help="Path to okf_catalog/ directory, OKF .md file, or canonical_ir.json (Zero Qlik dependency)")
    gen_parser.add_argument("--model-name", default="enterprise_analytics", help="LookML Model Name")
    gen_parser.add_argument("--explore-name", help="Custom Explore Name (defaults to inferred root fact view)")
    gen_parser.add_argument("--output-dir", default="./looker_project", help="Directory to save LookML files")

    # --- Command: serve (Web Studio) ---
    serve_parser = subparsers.add_parser("serve", help="Launch Enterprise Web UI Studio")
    serve_parser.add_argument("--port", type=int, default=8080, help="Web server port")
    serve_parser.add_argument("--db-path", default="enterprise_migration.db", help="Path to SQLite database")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "extract":
        run_extract(args)
    elif args.command == "discover":
        run_discover(args)
    elif args.command == "audit":
        run_audit(args)
    elif args.command == "validate":
        run_validate(args)
    elif args.command == "reconcile-okf":
        run_reconcile_okf(args)
    elif args.command == "generate":
        run_generate(args)
    elif args.command == "serve":
        run_serve(args)


def run_discover(args):
    print("[*] Discovering applications from active Qlik instance...")
    db = DatabaseManager(db_path=args.db_path)
    active = db.get_active_instance()
    if not active:
        print("[!] No active instance configured in database.")
        sys.exit(1)
    print(f"[*] Active Instance: '{active.get('name')}' ({active.get('qlik_host')})")
    from enterprise_qlik.stage1_extract.connection import QlikConnectionService
    try:
        apps = QlikConnectionService.discover_apps_for_instance(active)
        print(f"[+] Discovered {len(apps)} applications:")
        for app in apps:
            s_name = app.get("stream_or_space") or "Personal"
            s_type = app.get("space_type") or ("personal" if s_name.lower() == "personal" else "managed")
            db.upsert_app(
                app_id=app["app_id"],
                name=app["name"],
                stream_or_space=s_name,
                space_type=s_type,
                sheet_count=app.get("sheet_count", 0),
                widget_count=app.get("widget_count", 0),
                tenant_id=active["tenant_id"],
            )
            print(f"    - [{app['app_id']}] '{app['name']}' (Space: {s_name})")
    except Exception as e:
        print(f"[!] Discovery failed: {e}")
        sys.exit(1)


def run_extract(args):
    print(f"[*] Starting STAGE 1 Extraction for App: {args.app_id}")
    db = DatabaseManager(db_path=args.db_path)
    host = args.host
    token = getattr(args, "token", None)

    if not token or host == "http://localhost:4848":
        active = db.get_active_instance()
        if active:
            if host == "http://localhost:4848":
                host = active.get("qlik_host", host)
            auth_cfg = active.get("auth_config", {})
            if isinstance(auth_cfg, str):
                try:
                    auth_cfg = json.loads(auth_cfg)
                except Exception:
                    auth_cfg = {}
            token = token or auth_cfg.get("api_key") or auth_cfg.get("token", "")

    extractor = QIXExtractor(host=host, token=token)
    compiler = CanonicalIRCompiler(include_compatibility=True)

    if args.sample:
        print("[*] Generating realistic enterprise sample app metadata...")
        raw_metadata = extractor.build_sample_enterprise_app(app_name="Enterprise Retail & Banking Sales")
    elif args.input_file:
        print(f"[*] Loading raw metadata from: {args.input_file}")
        raw_metadata = extractor.load_from_json_file(args.input_file)
    else:
        print(f"[*] Connecting to QIX engine at {host}...")
        raw_metadata = extractor.extract_app_metadata(args.app_id)

    print("[*] Compiling Canonical 2-Tier Intermediate Representation (IR)...")
    canonical_ir = compiler.compile(raw_metadata)

    # Validate against open contract
    is_valid, errors = validate_canonical_ir(canonical_ir)
    if not is_valid:
        print(f"[!] Warning: Schema validation warnings: {errors}")
    else:
        print("[+] Canonical IR successfully validated against OpenAPI/JSON-Schema contract.")

    # Save to App DB
    db.save_canonical_ir(args.app_id, canonical_ir, raw_metadata)
    compat = canonical_ir.get("feature_compatibility", {})
    if compat and "findings" in compat:
        db.save_compatibility_findings(args.app_id, compat["findings"])
    print(f"[+] Persisted application state and IR cache to database: {args.db_path}")

    # Write Handoff Artifacts to disk
    os.makedirs(args.output_dir, exist_ok=True)
    ir_path = os.path.join(args.output_dir, "canonical_ir.json")
    with open(ir_path, "w", encoding="utf-8") as f:
        json.dump(canonical_ir, f, indent=2)
    print(f"[+] Canonical IR written to: {ir_path}")

    if compat:
        gap_path = os.path.join(args.output_dir, "feature_gaps.json")
        with open(gap_path, "w", encoding="utf-8") as f:
            json.dump(compat, f, indent=2)
        print(f"[+] 3-Tier Gap Report written to: {gap_path}")

    print("\n[SUCCESS] STAGE 1 Complete. The customer can now take this Canonical IR package to any tool, pipeline, or agent.")


def run_audit(args):
    print(f"[*] Running 3-Tier Compatibility Audit on: {args.input_file}")
    with open(args.input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    analyzer = CompatibilityAnalyzer()
    report = analyzer.analyze(data)

    print(f"\nAudit Summary:")
    print(f"  Total Issues: {report['summary']['total_issues']}")
    print(f"  Category 1 (Mapped Differently): {report['summary']['category_breakdown']['category_1_mapped_differently']}")
    print(f"  Category 2 (Upstream / Refactoring): {report['summary']['category_breakdown']['category_2_upstream_refactoring']}")
    print(f"  Category 3 (Target Deprecated): {report['summary']['category_breakdown']['category_3_target_deprecated']}")
    print(f"  Hard Blocker Cyclic Loops: {report['summary']['hard_blockers_count']}")
    print(f"  Estimated Remediation Time: {report['summary']['total_estimated_remediation_hours']} hours\n")

    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"[+] Report saved to: {args.output_file}")


def run_validate(args):
    if os.path.isdir(args.ir_file):
        print(f"[*] Validating OKF v0.2 Catalog directory: {args.ir_file}")
        from enterprise_qlik.okf.catalog import OKFCatalogManager
        from enterprise_qlik.okf.validator import validate_okf_catalog
        mgr = OKFCatalogManager(args.ir_file)
        is_valid, errors = validate_okf_catalog(mgr.list_all_files_map())
        if is_valid:
            print("[PASS] Directory strictly conforms to OKF v0.2 specification.")
            return
        print("[FAIL] OKF v0.2 conformance errors detected:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)

    print(f"[*] Validating Canonical IR file: {args.ir_file}")
    with open(args.ir_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    is_valid, errors = validate_canonical_ir(data)
    if is_valid:
        print("[PASS] File strictly conforms to Canonical IR Schema.")
    else:
        print("[FAIL] Schema errors detected:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)


def run_reconcile_okf(args):
    print(f"[*] Starting STAGE 1.5 Fleet Semantic Reconciliation on OKF Catalog: {args.catalog_dir}")
    db = DatabaseManager(db_path=args.db_path, okf_catalog_dir=args.catalog_dir)
    res = db.reconcile_fleet_okf(similarity_threshold=args.threshold)
    print(f"[+] Reconciled {res['total_apps_reconciled']} Qlik applications into {res['canonical_explores_count']} Canonical Looker Explores.")
    print(f"[+] Eliminated {res['duplicate_explores_eliminated']} duplicate LookML models ({res['explore_reduction_pct']}% reduction).")
    print(f"[+] Category 2 Effort Deduplication: {res['raw_cat2_effort_hours']}h raw -> {res['deduplicated_cat2_effort_hours']}h net ({res['saved_cat2_effort_hours']}h saved).")


def run_generate(args):
    print(f"[*] Starting STAGE 2 Code Generation (Explore-First LookML Modeling)")
    print(f"[*] Reading ONLY OKF / IR contract from: {args.ir_file}")
    generator = LookMLGenerator(model_name=args.model_name)
    artifacts = generator.generate(
        canonical_ir_input=args.ir_file,
        target_explore_name=args.explore_name,
        output_dir=args.output_dir,
    )
    meta = artifacts["metadata"]
    if "total_canonical_explores" in meta:
        print(f"[+] Compiled {meta['total_canonical_explores']} Canonical Looker Explores from Fleet OKF Catalog")
    else:
        print(f"[+] LookML Explore compiled: '{meta['explore_name']}' (Root view: '{meta['root_view']}')")
    print(f"[+] Generated {meta['total_views']} Shared LookML Views (.view.lkml)")
    print(f"[+] Generated {meta['total_dashboards']} LookML Dashboards (.dashboard.lookml) bound strictly to Canonical Explores")
    print(f"[+] Generated upstream dbt models: {list(artifacts['dbt_models'].keys())}")
    print(f"\n[SUCCESS] STAGE 2 Complete. All LookML artifacts written to: {args.output_dir}")


def run_serve(args):
    from enterprise_qlik.web.server import run_server
    print(f"[*] Starting Enterprise Migration Web Studio on port {args.port}...")
    run_server(port=args.port, db_path=args.db_path)


if __name__ == "__main__":
    main()
