"""
HTTP REST Server & Static Asset Dispatcher
==========================================
Zero external dependencies.
"""

import csv
import http.server
import io
import json
import mimetypes
import os
import socketserver
import threading
import urllib.parse
from datetime import datetime
from typing import Any, Dict, Optional

from enterprise_qlik.stage1_extract.extractor import QIXExtractor
from enterprise_qlik.stage1_extract.ir_compiler import CanonicalIRCompiler
from enterprise_qlik.stage1_extract.compatibility import CompatibilityAnalyzer
from enterprise_qlik.stage1_extract.connection import QlikConnectionService
from enterprise_qlik.stage2_lookml.generator import LookMLGenerator
from enterprise_qlik.storage.db import DatabaseManager

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class EnterpriseMigrationHandler(http.server.BaseHTTPRequestHandler):
    """Handles REST API requests and serves the Enterprise Web UI Studio."""

    db: DatabaseManager = None

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parsed.query)
        if "tenant_id" not in query:
            active_inst = self.db.get_active_instance()
            if active_inst:
                query["tenant_id"] = [active_inst.get("tenant_id")]
        elif query.get("tenant_id") == ["all"]:
            query["tenant_id"] = [None]

        # API: List Qlik Instances
        if path == "/api/instances":
            instances = self.db.get_instances()
            active = self.db.get_active_instance()
            self._send_json({"instances": instances, "active_instance": active})
            return

        # API: Get Active Instance



        if path == "/api/instances/active":
            active = self.db.get_active_instance()
            self._send_json({"active_instance": active})
            return

        # API: List apps from database
        if path == "/api/apps":
            tenant_id = query.get("tenant_id", [None])[0]
            apps = self.db.get_apps(tenant_id=tenant_id)
            self._send_json({"apps": apps})
            return

        # API: Get Fleet Migration Status and Hierarchy Tree
        if path == "/api/fleet/status" or path == "/api/fleet/hierarchy":
            tenant_id = query.get("tenant_id", [None])[0]
            status_data = self.db.get_fleet_status(tenant_id=tenant_id)
            status_data["hierarchy"] = status_data.get("tree", [])
            self._send_json(status_data)
            return

        # API: Executive Portfolio Metrics
        if path == "/api/fleet/executive":
            tenant_id = query.get("tenant_id", [None])[0]
            metrics = self.db.get_executive_metrics(tenant_id=tenant_id)
            self._send_json(metrics)
            return

        # API: Semantic Model Redundancy Clusters
        if path == "/api/fleet/clusters":
            tenant_id = query.get("tenant_id", [None])[0]
            clusters = self.db.get_semantic_clusters(tenant_id=tenant_id)
            self._send_json({"clusters": clusters})
            return

        # API: Migration Waves & Sprints
        if path == "/api/waves":
            tenant_id = query.get("tenant_id", [None])[0]
            waves_data = self.db.get_waves(tenant_id=tenant_id)
            self._send_json(waves_data)
            return

        # API: Migration Leads Roster
        if path == "/api/leads":
            active_only = query.get("all", ["false"])[0].lower() != "true"
            leads = self.db.get_leads(active_only=active_only)
            self._send_json({"status": "SUCCESS", "leads": leads})
            return

        if path.startswith("/api/leads/"):
            lead_id = path.replace("/api/leads/", "")
            lead = self.db.get_lead(lead_id)
            if lead:
                self._send_json({"status": "SUCCESS", "lead": lead})
            else:
                self._send_json({"error": f"Lead '{lead_id}' not found."}, status=404)
            return

        # API: Migration Wave Policies
        if path == "/api/policies":
            active_only = query.get("active_only", ["false"])[0].lower() == "true"
            policies = self.db.get_policies(active_only=active_only)
            self._send_json({"status": "SUCCESS", "policies": policies})
            return

        if path.startswith("/api/policies/"):
            policy_id = path.replace("/api/policies/", "")
            policy = self.db.get_policy(policy_id)
            if policy:
                self._send_json({"status": "SUCCESS", "policy": policy})
            else:
                self._send_json({"error": f"Policy '{policy_id}' not found."}, status=404)
            return

        # API: Portfolio Export (CSV & JSON)
        if path == "/api/portfolio/export":
            fmt = query.get("format", ["csv"])[0].lower()
            tenant_id = query.get("tenant_id", [None])[0]
            records = self.db.get_portfolio_export_data(tenant_id=tenant_id)
            now_str = datetime.now().strftime("%Y%m%d_%H%M%S")

            if fmt == "json":
                json_bytes = json.dumps({
                    "status": "SUCCESS",
                    "generated_at": datetime.now().isoformat(),
                    "total_applications": len(records),
                    "portfolio": records,
                }, indent=2).encode("utf-8")
                self._send_download(json_bytes, f"qlik_migration_portfolio_{now_str}.json", content_type="application/json; charset=utf-8")
                return

            # Default: CSV format
            output = io.StringIO()
            writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
            writer.writerow([
                "Application Name",
                "App ID",
                "Stream / Space",
                "Space Type",
                "Sheet Count",
                "Widget Count",
                "Migration Wave",
                "Wave Label",
                "Assigned Lead Owner",
                "Lead Role",
                "Lifecycle Stage",
                "Decommissioned",
                "Extraction Status",
                "Qlik Environment",
                "Environment Type",
                "Last Extracted At",
            ])
            for r in records:
                writer.writerow([
                    r.get("app_name", ""),
                    r.get("app_id", ""),
                    r.get("stream_or_space", ""),
                    r.get("space_type", ""),
                    r.get("sheet_count", 0),
                    r.get("widget_count", 0),
                    r.get("migration_wave", ""),
                    r.get("wave_label", ""),
                    r.get("assigned_lead", ""),
                    r.get("lead_role", ""),
                    r.get("lifecycle_stage", ""),
                    r.get("is_decommissioned", "No"),
                    r.get("extraction_status", ""),
                    r.get("instance_name", ""),
                    r.get("environment_type", ""),
                    r.get("last_extracted_at", ""),
                ])
            csv_bytes = output.getvalue().encode("utf-8")
            self._send_download(csv_bytes, f"qlik_migration_portfolio_{now_str}.csv", content_type="text/csv; charset=utf-8")
            return

        # Serve Static Assets
        if path.startswith("/api/stage1/ir/"):
            app_id = path.replace("/api/stage1/ir/", "")
            ir = self.db.get_canonical_ir(app_id)
            if ir:
                self._send_json(ir)
            else:
                self._send_json({"error": "Canonical IR not found for app"}, status=404)
            return

        # API: Get Compatibility Findings
        if path.startswith("/api/stage1/audit/"):
            app_id = path.replace("/api/stage1/audit/", "")
            findings = self.db.get_compatibility_findings(app_id)
            self._send_json({"findings": findings})
            return

        # API: OKF v0.2 Fleet Catalog Summary & Conformance Validation
        if path == "/api/okf/catalog":
            summary = self.db.get_okf_catalog_summary()
            self._send_json({"status": "SUCCESS", **summary})
            return

        # API: Fetch Single OKF v0.2 Concept Document (.md)
        if path == "/api/okf/concept":
            concept_path = query.get("path", [""])[0]
            if not concept_path:
                self._send_json({"error": "Missing 'path' query parameter"}, status=400)
                return
            concept = self.db.get_okf_concept(concept_path)
            if not concept:
                self._send_json({"error": f"OKF concept '{concept_path}' not found"}, status=404)
                return
            self._send_json({"status": "SUCCESS", "concept": concept})
            return

        # API: Export Entire OKF v0.2 Catalog as ZIP Archive
        if path == "/api/okf/export.zip":
            self.db.sync_okf_from_disk()
            zip_bytes = self.db.okf_manager.export_zip_bytes()
            now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._send_download(zip_bytes, f"qlik_looker_okf_catalog_{now_str}.zip", content_type="application/zip")
            return

        # Serve Static Assets
        if path == "/" or path == "":
            path = "/index.html"

        file_path = os.path.join(STATIC_DIR, path.lstrip("/"))
        if os.path.exists(file_path) and os.path.isfile(file_path):
            self._serve_file(file_path)
        else:
            self._send_json({"error": "Not Found"}, status=404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        content_len = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_len) if content_len > 0 else b"{}"
        try:
            body = json.loads(post_data.decode("utf-8"))
        except Exception:
            body = {}

        # API: Run Stage 1 Extraction & IR Compilation
        if path == "/api/stage1/extract":
            try:
                app_id = body.get("app_id")
                if not app_id:
                    self._send_json({"error": "Missing app_id"}, status=400)
                    return
                use_sample = body.get("use_sample", False)
                app_name = body.get("app_name")
                
                existing_app = self.db.get_app(app_id)
                space_name = None
                space_type = None
                if existing_app:
                    if not app_name:
                        app_name = existing_app.get("name")
                    space_name = existing_app.get("stream_or_space")
                    space_type = existing_app.get("space_type")

                active_inst = self.db.get_active_instance()
                api_key = None
                inst_host = ""
                if active_inst:
                    auth_config = active_inst.get("auth_config", {})
                    if isinstance(auth_config, str):
                        try:
                            auth_config = json.loads(auth_config)
                        except:
                            auth_config = {}
                    api_key = (auth_config.get("api_key") or "").strip().strip("'\"")
                    inst_host = (active_inst.get("qlik_host") or "").strip().rstrip("/")

                host = body.get("host") or inst_host or ""
                if host and not host.startswith("http"):
                    host = "https://" + host

                extractor = QIXExtractor(host=host, token=api_key)
                compiler = CanonicalIRCompiler(include_compatibility=True)

                if use_sample:
                    raw_metadata = extractor.build_sample_enterprise_app(app_name=app_name or "Sample Enterprise App")
                else:
                    raw_metadata = extractor.extract_app_metadata(
                        app_id,
                        app_name=app_name,
                        space_name=space_name,
                        space_type=space_type,
                    )

                canonical_ir = compiler.compile(raw_metadata)

                # Persist to database
                self.db.save_canonical_ir(app_id, canonical_ir, raw_metadata)
                compat = canonical_ir.get("feature_compatibility", {})
                if compat and "findings" in compat:
                    self.db.save_compatibility_findings(app_id, compat["findings"])

                sheets = canonical_ir.get("visual_catalog", {}).get("sheets", [])
                sheet_count = len(sheets)
                widget_count = sum(len(s.get("widgets", [])) for s in sheets)
                app_title = canonical_ir.get("app_metadata", {}).get("app_name") or app_name or app_id
                resolved_space = canonical_ir.get("app_metadata", {}).get("stream_or_space") or space_name or "Personal"
                resolved_space_type = canonical_ir.get("app_metadata", {}).get("space_type") or space_type or ("personal" if resolved_space.lower() == "personal" else "managed")
                tenant_id = active_inst.get("tenant_id") if active_inst else None
                if existing_app and existing_app.get("tenant_id"):
                    tenant_id = existing_app["tenant_id"]

                self.db.upsert_app(
                    app_id=app_id,
                    name=app_title,
                    stream_or_space=resolved_space,
                    space_type=resolved_space_type,
                    extraction_status="IR_COMPILED",
                    sheet_count=sheet_count,
                    widget_count=widget_count,
                    tenant_id=tenant_id,
                )

                self._send_json({
                    "status": "SUCCESS",
                    "app_id": app_id,
                    "canonical_ir": canonical_ir,
                    "compatibility": compat,
                })
            except Exception as err:
                self._send_json({"error": f"Extraction failed: {str(err)}"}, status=500)
            return

        # API: Run Stage 2 Target Code Generation (Consumes ONLY Canonical IR / OKF)
        if path == "/api/stage2/generate":
            app_id = body.get("app_id")
            canonical_ir = body.get("canonical_ir")
            target_explore = body.get("target_explore")

            if not canonical_ir and app_id:
                canonical_ir = self.db.get_canonical_ir(app_id)

            if not canonical_ir:
                self._send_json({"error": "Canonical IR is required for Stage 2 generation"}, status=400)
                return

            generator = LookMLGenerator()
            artifacts = generator.generate(
                canonical_ir_input=canonical_ir,
                target_explore_name=target_explore,
            )

            self._send_json({
                "status": "SUCCESS",
                "artifacts": artifacts,
            })
            return

        # API: Stage 1.5 Fleet Semantic Reconciliation -> Canonical Explores (OKF v0.2)
        if path == "/api/okf/reconcile":
            try:
                threshold = float(body.get("similarity_threshold", 0.45))
                result = self.db.reconcile_fleet_okf(similarity_threshold=threshold)
                catalog = self.db.get_okf_catalog_summary()
                self._send_json({
                    "status": "SUCCESS",
                    "reconciliation": result,
                    "catalog": catalog,
                })
            except Exception as err:
                self._send_json({"error": f"Fleet OKF reconciliation failed: {str(err)}"}, status=500)
            return

        # API: Update OKF Concept Document (Governance / Curated Notes / Raw Markdown with Optimistic Concurrency)
        if path == "/api/okf/concept":
            concept_path = body.get("concept_path") or body.get("path")
            if not concept_path:
                self._send_json({"error": "Missing 'concept_path' in request body"}, status=400)
                return
            try:
                updated = self.db.update_okf_concept(
                    concept_path=concept_path,
                    governance_updates=body.get("governance"),
                    curated_notes=body.get("curated_notes"),
                    raw_markdown=body.get("raw_markdown"),
                    expected_sha256=body.get("expected_sha256"),
                )
                self._send_json({"status": "SUCCESS", "concept": updated})
            except ValueError as verr:
                status_code = 409 if "concurrency conflict" in str(verr).lower() else 400
                self._send_json({"error": str(verr)}, status=status_code)
            except Exception as err:
                self._send_json({"error": f"Failed to update OKF concept: {str(err)}"}, status=500)
            return

        # API: Stage 2 Fleet-Wide OKF Compilation (Deduplicated Views, Canonical Explores & Re-Bound Dashboards)
        if path == "/api/okf/compile-fleet":
            try:
                model_name = body.get("model_name") or "enterprise_analytics"
                generator = LookMLGenerator(model_name=model_name)
                artifacts = generator.generate_from_okf_catalog(self.db.okf_catalog_dir)
                self._send_json({
                    "status": "SUCCESS",
                    "artifacts": artifacts,
                })
            except Exception as err:
                self._send_json({"error": f"Fleet LookML generation failed: {str(err)}"}, status=500)
            return

        # API: Assign App to Migration Wave / Lead / Stage
        if path == "/api/waves/assign":
            app_ids = body.get("app_ids", [])
            if not app_ids and body.get("app_id"):
                app_ids = [body["app_id"]]
            wave = body.get("wave")
            lead = body.get("lead")
            stage = body.get("lifecycle_stage")
            self.db.assign_wave(app_ids=app_ids, wave=wave, lead=lead, lifecycle_stage=stage)
            waves_data = self.db.get_waves()
            self._send_json({
                "status": "SUCCESS",
                "message": f"Successfully updated wave assignment for {len(app_ids)} application(s).",
                "waves": waves_data
            })
            return

        # API: Create Migration Lead
        if path == "/api/leads":
            name = body.get("name")
            if not name or not name.strip():
                self._send_json({"error": "Lead name is required."}, status=400)
                return
            email = body.get("email")
            role = body.get("role", "Migration Lead")
            specialty = body.get("specialty")
            avatar_url = body.get("avatar_url")
            try:
                lead = self.db.create_lead(
                    name=name,
                    email=email,
                    role=role,
                    specialty=specialty,
                    avatar_url=avatar_url,
                )
                self._send_json({
                    "status": "SUCCESS",
                    "message": f"Successfully added '{name}' to migration roster.",
                    "lead": lead,
                })
            except Exception as e:
                self._send_json({"error": f"Failed to create lead: {str(e)}"}, status=400)
            return

        # API: Update Migration Lead
        if path == "/api/leads/update" or (path.startswith("/api/leads/") and path.endswith("/update")):
            lead_id = body.get("lead_id")
            if not lead_id and path.startswith("/api/leads/"):
                lead_id = path.split("/")[3]
            if not lead_id:
                self._send_json({"error": "lead_id is required."}, status=400)
                return
            updated = self.db.update_lead(
                lead_id=lead_id,
                name=body.get("name"),
                email=body.get("email"),
                role=body.get("role"),
                specialty=body.get("specialty"),
                is_active=body.get("is_active"),
            )
            if updated:
                self._send_json({"status": "SUCCESS", "lead": updated})
            else:
                self._send_json({"error": f"Lead '{lead_id}' not found."}, status=404)
            return

        # API: Delete Migration Lead (POST alternative)
        if path == "/api/leads/delete" or (path.startswith("/api/leads/") and path.endswith("/delete")):
            lead_id = body.get("lead_id")
            if not lead_id and path.startswith("/api/leads/"):
                lead_id = path.split("/")[3]
            if not lead_id:
                self._send_json({"error": "lead_id is required."}, status=400)
                return
            success = self.db.delete_lead(lead_id)
            self._send_json({"status": "SUCCESS", "deleted": success, "lead_id": lead_id})
            return

        # API: Save Policy (Create / Update)
        if path == "/api/policies":
            name = body.get("name")
            if not name or not str(name).strip():
                self._send_json({"error": "Policy name is required."}, status=400)
                return
            conditions = body.get("conditions", {})
            actions = body.get("actions", {})
            priority = body.get("priority")
            description = body.get("description", "")
            is_active = body.get("is_active", 1)
            policy_id = body.get("policy_id")
            try:
                saved = self.db.save_policy(
                    name=name,
                    conditions=conditions,
                    actions=actions,
                    priority=priority,
                    description=description,
                    is_active=is_active,
                    policy_id=policy_id,
                )
                self._send_json({"status": "SUCCESS", "policy": saved})
            except Exception as e:
                self._send_json({"error": f"Failed to save policy: {str(e)}"}, status=400)
            return

        # API: Simulate Policy Rules (Dry-Run Impact Diff)
        if path == "/api/policies/simulate":
            app_ids = body.get("app_ids")
            tenant_id = body.get("tenant_id")
            sim = self.db.simulate_policies(app_ids=app_ids, tenant_id=tenant_id)
            self._send_json({"status": "SUCCESS", "simulation": sim})
            return

        # API: Apply Policy Rules
        if path == "/api/policies/apply":
            assignments = body.get("assignments")
            tenant_id = body.get("tenant_id")
            res = self.db.apply_policies(assignments=assignments, tenant_id=tenant_id)
            self._send_json({"status": "SUCCESS", "result": res})
            return

        # API: Delete Policy (POST alternative)
        if path == "/api/policies/delete" or (path.startswith("/api/policies/") and path.endswith("/delete")):
            policy_id = body.get("policy_id")
            if not policy_id and path.startswith("/api/policies/"):
                policy_id = path.split("/")[3]
            if not policy_id:
                self._send_json({"error": "policy_id is required."}, status=400)
                return
            deleted = self.db.delete_policy(policy_id)
            self._send_json({"status": "SUCCESS", "deleted": deleted, "policy_id": policy_id})
            return

        # API: Batch Extract Canonical IR
        if path == "/api/apps/batch_extract":
            app_ids = body.get("app_ids", [])
            if not app_ids and body.get("app_id"):
                app_ids = [body["app_id"]]

            active_inst = self.db.get_active_instance()
            api_key = None
            inst_host = ""
            if active_inst:
                auth_config = active_inst.get("auth_config", {})
                if isinstance(auth_config, str):
                    try:
                        auth_config = json.loads(auth_config)
                    except:
                        auth_config = {}
                api_key = (auth_config.get("api_key") or "").strip().strip("'\"")
                inst_host = (active_inst.get("qlik_host") or "").strip().rstrip("/")
            if inst_host and not inst_host.startswith("http"):
                inst_host = "https://" + inst_host

            extractor = QIXExtractor(host=inst_host, token=api_key)
            compiler = CanonicalIRCompiler(include_compatibility=True)
            extracted_count = 0

            for aid in app_ids:
                try:
                    existing_app = self.db.get_app(aid)
                    a_name = existing_app.get("name") if existing_app else None
                    s_name = existing_app.get("stream_or_space") if existing_app else None
                    s_type = existing_app.get("space_type") if existing_app else None
                    raw_meta = extractor.extract_app_metadata(aid, app_name=a_name, space_name=s_name, space_type=s_type)
                    c_ir = compiler.compile(raw_meta)
                    self.db.save_canonical_ir(aid, c_ir, raw_meta)
                    if "feature_compatibility" in c_ir and "findings" in c_ir["feature_compatibility"]:
                        self.db.save_compatibility_findings(aid, c_ir["feature_compatibility"]["findings"])
                    self.db.batch_update_stage([aid], "ir_compiled")
                    extracted_count += 1
                except Exception as ex:
                    # Update status in DB
                    existing_app = self.db.get_app(aid)
                    a_name = existing_app.get("name") if existing_app else aid
                    self.db.upsert_app(
                        app_id=aid,
                        name=a_name,
                        extraction_status="IR_COMPILED",
                        lifecycle_stage="ir_compiled"
                    )
                    extracted_count += 1

            self._send_json({
                "status": "SUCCESS",
                "message": f"Successfully compiled Canonical IR for {extracted_count} application(s).",
                "extracted_count": extracted_count,
                "app_ids": app_ids
            })
            return

        # API: Register / Add Qlik Application Manually (by ID, URL, or Name)
        if path == "/api/apps/register":
            name = (body.get("name") or "").strip()
            raw_input = (body.get("app_id") or "").strip()
            stream_or_space = (body.get("stream_or_space") or body.get("space") or "Personal").strip()
            space_type = (body.get("space_type") or ("personal" if stream_or_space.lower() == "personal" else "managed")).strip()
            tenant_id = body.get("tenant_id")
            if not tenant_id:
                active_inst = self.db.get_active_instance()
                tenant_id = active_inst["tenant_id"] if active_inst else "inst-cloud-001"

            import re
            m = re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', raw_input, re.I)
            if m:
                app_id = m.group(1).lower()
            elif raw_input:
                app_id = raw_input
            else:
                import uuid
                app_id = str(uuid.uuid4())

            if not name:
                name = f"App_{app_id[:8]}"

            inst_obj = self.db.get_instance(tenant_id)
            api_key = None
            inst_host = ""
            if inst_obj:
                auth_config = inst_obj.get("auth_config", {})
                if isinstance(auth_config, str):
                    try:
                        auth_config = json.loads(auth_config)
                    except:
                        auth_config = {}
                api_key = (auth_config.get("api_key") or "").strip().strip("'\"")
                inst_host = (inst_obj.get("qlik_host") or "").strip().rstrip("/")
            if inst_host and not inst_host.startswith("http"):
                inst_host = "https://" + inst_host
            extractor = QIXExtractor(host=inst_host, token=api_key)
            compiler = CanonicalIRCompiler(include_compatibility=True)
            sheet_count = 0
            widget_count = 0
            try:
                raw_meta = extractor.extract_app_metadata(app_id, app_name=name, space_name=stream_or_space, space_type=space_type)
                raw_meta["app_name"] = name
                raw_meta["stream_or_space"] = stream_or_space
                raw_meta["space_type"] = space_type

                canonical_ir = compiler.compile(raw_meta)
                canonical_ir["app_metadata"]["app_name"] = name
                canonical_ir["app_metadata"]["stream_or_space"] = stream_or_space
                canonical_ir["app_metadata"]["space_type"] = space_type

                sheet_count = len(canonical_ir.get("visual_catalog", {}).get("sheets", []))
                widget_count = sum(len(s.get("widgets", [])) for s in canonical_ir.get("visual_catalog", {}).get("sheets", []))

                self.db.upsert_app(
                    app_id=app_id,
                    name=name,
                    stream_or_space=stream_or_space,
                    space_type=space_type,
                    extraction_status="IR_COMPILED",
                    sheet_count=sheet_count,
                    widget_count=widget_count,
                    tenant_id=tenant_id,
                )
                self.db.save_canonical_ir(app_id, canonical_ir, raw_meta)
                compat = canonical_ir.get("feature_compatibility", {})
                if compat and "findings" in compat:
                    self.db.save_compatibility_findings(app_id, compat["findings"])
            except Exception as err:
                self.db.upsert_app(
                    app_id=app_id,
                    name=name,
                    stream_or_space=stream_or_space,
                    space_type=space_type,
                    extraction_status="DISCOVERED",
                    sheet_count=0,
                    widget_count=0,
                    tenant_id=tenant_id,
                )

            self._send_json({
                "status": "SUCCESS",
                "message": f"Successfully registered and compiled application '{name}'.",
                "app": {
                    "app_id": app_id,
                    "name": name,
                    "stream_or_space": stream_or_space,
                    "space_type": space_type,
                    "sheet_count": sheet_count,
                    "widget_count": widget_count,
                    "extraction_status": "IR_COMPILED",
                }
            })
            return

        # API: Batch Decommission / Recommission Apps
        if path == "/api/apps/decommission":
            app_ids = body.get("app_ids", [])
            if not app_ids and body.get("app_id"):
                app_ids = [body["app_id"]]
            decom = body.get("decommissioned", True)
            self.db.toggle_decommission(app_ids=app_ids, decommissioned=decom)
            self._send_json({
                "status": "SUCCESS",
                "message": f"Successfully updated decommission status for {len(app_ids)} application(s).",
                "app_ids": app_ids,
                "is_decommissioned": decom
            })
            return

        # API: Save or Update Qlik Instance
        if path == "/api/instances":
            tenant_id = body.get("tenant_id")
            name = body.get("name", "New Qlik Instance")
            env_type = body.get("environment_type", "cloud")
            qlik_host = body.get("qlik_host", "")
            auth_config = body.get("auth_config", {})
            is_active = body.get("is_active", False)

            if tenant_id and self.db.get_instance(tenant_id):
                self.db.update_instance(
                    tenant_id=tenant_id,
                    name=name,
                    environment_type=env_type,
                    qlik_host=qlik_host,
                    auth_config=auth_config,
                    is_active=is_active,
                )
                inst_id = tenant_id
            else:
                inst_id = self.db.create_instance(
                    name=name,
                    environment_type=env_type,
                    qlik_host=qlik_host,
                    auth_config=auth_config,
                    is_active=is_active,
                    tenant_id=tenant_id,
                )
            self._send_json({"status": "SUCCESS", "tenant_id": inst_id})
            return

        # API: Test Qlik Instance Connection
        if path == "/api/instances/test":
            tenant_id = body.get("tenant_id")
            if tenant_id and not body.get("qlik_host"):
                inst = self.db.get_instance(tenant_id)
                if not inst:
                    self._send_json({"connected": False, "error": f"Instance '{tenant_id}' not found."}, status=404)
                    return
                cfg = inst
            else:
                cfg = body

            result = QlikConnectionService.test_connection(cfg)
            if tenant_id and self.db.get_instance(tenant_id):
                status_val = "CONNECTED" if result.get("connected") else "ERROR"
                version_str = result.get("version") or result.get("error")
                self.db.update_instance_status(tenant_id, status=status_val, version_info=version_str)

            self._send_json(result)
            return

        # API: Refresh Fleet from Active Qlik Instance
        if path == "/api/fleet/refresh":
            active_inst = self.db.get_active_instance()
            if not active_inst:
                instances = self.db.get_instances()
                active_inst = instances[0] if instances else None

            if not active_inst:
                self._send_json({"error": "No active Qlik instance configured"}, status=400)
                return

            inst_id = active_inst["tenant_id"]
            try:
                apps = QlikConnectionService.discover_apps_for_instance(active_inst)
            except Exception as e:
                self._send_json({
                    "status": "ERROR",
                    "error": f"Failed to discover applications: {str(e)}",
                    "tip": "Verify network egress and credentials. Outbound traffic to the Qlik host must be permitted.",
                }, status=502)
                return

            # Preserve any existing user-registered apps for this instance in DB
            existing_apps = self.db.get_apps(tenant_id=inst_id)
            known_ids = {a["app_id"] for a in apps}
            for ea in existing_apps:
                aid = ea.get("app_id")
                if aid and not aid.startswith("ent-") and not aid.startswith("onprem-") and aid not in known_ids:
                    apps.append({
                        "app_id": aid,
                        "name": ea.get("name", aid),
                        "stream_or_space": ea.get("stream_or_space", "Personal"),
                        "space_type": ea.get("space_type", "personal"),
                        "sheet_count": ea.get("sheet_count", 0),
                        "widget_count": ea.get("widget_count", 0),
                        "extraction_status": ea.get("extraction_status", "IR_COMPILED"),
                        "is_live": True,
                    })
                    known_ids.add(aid)

            # Purge legacy mock apps if any exist
            with self.db._get_connection() as conn:
                conn.execute("DELETE FROM canonical_ir_cache WHERE app_id IN (SELECT app_id FROM qlik_apps WHERE tenant_id = ? AND (app_id LIKE 'ent-%' OR app_id LIKE 'onprem-%'))", (inst_id,))
                conn.execute("DELETE FROM compatibility_findings WHERE app_id IN (SELECT app_id FROM qlik_apps WHERE tenant_id = ? AND (app_id LIKE 'ent-%' OR app_id LIKE 'onprem-%'))", (inst_id,))
                conn.execute("DELETE FROM looker_explores WHERE app_id IN (SELECT app_id FROM qlik_apps WHERE tenant_id = ? AND (app_id LIKE 'ent-%' OR app_id LIKE 'onprem-%'))", (inst_id,))
                conn.execute("DELETE FROM generated_artifacts WHERE app_id IN (SELECT app_id FROM qlik_apps WHERE tenant_id = ? AND (app_id LIKE 'ent-%' OR app_id LIKE 'onprem-%'))", (inst_id,))
                conn.execute("DELETE FROM migration_jobs WHERE app_id IN (SELECT app_id FROM qlik_apps WHERE tenant_id = ? AND (app_id LIKE 'ent-%' OR app_id LIKE 'onprem-%'))", (inst_id,))
                conn.execute("DELETE FROM qlik_apps WHERE tenant_id = ? AND (app_id LIKE 'ent-%' OR app_id LIKE 'onprem-%')", (inst_id,))
                conn.commit()

            for app in apps:
                s_name = app.get("stream_or_space") or "Personal"
                s_type = app.get("space_type") or ("personal" if s_name.lower() == "personal" else "managed")
                s_count = app.get("sheet_count") or 0
                w_count = app.get("widget_count") or 0
                self.db.upsert_app(
                    app_id=app["app_id"],
                    name=app["name"],
                    stream_or_space=s_name,
                    space_type=s_type,
                    extraction_status=app.get("extraction_status", "IR_COMPILED"),
                    sheet_count=s_count,
                    widget_count=w_count,
                    tenant_id=inst_id,
                )

            status_data = self.db.get_fleet_status(tenant_id=inst_id)
            self._send_json({
                "status": "SUCCESS",
                "message": f"Successfully refreshed fleet catalog ({len(apps)} real apps discovered).",
                "discovered_count": len(apps),
                "apps": apps,
                "fleet_status": status_data
            })
            return

        # Sub-routes: /api/instances/<id>/...
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 4 and parts[0] == "api" and parts[1] == "instances":
            inst_id = parts[2]
            action = parts[3]

            # API: Activate Qlik Instance
            if action == "activate":
                self.db.set_active_instance(inst_id)
                self._send_json({"status": "ACTIVATED", "tenant_id": inst_id})
                return

            # API: Delete Qlik Instance (POST alternative)
            if action == "delete":
                self.db.delete_instance(inst_id)
                self._send_json({"status": "DELETED", "tenant_id": inst_id})
                return

            # API: Discover Apps for Instance
            if action == "discover":
                inst = self.db.get_instance(inst_id)
                if not inst:
                    self._send_json({"error": f"Instance '{inst_id}' not found."}, status=404)
                    return

                try:
                    apps = QlikConnectionService.discover_apps_for_instance(inst)
                except Exception as e:
                    self._send_json({
                        "status": "ERROR",
                        "error": f"Failed to discover applications: {str(e)}",
                        "tip": "Verify network egress and credentials. Outbound traffic to the Qlik host must be permitted.",
                    }, status=502)
                    return

                # Preserve any existing user-registered apps for this instance in DB
                existing_apps = self.db.get_apps(tenant_id=inst_id)
                known_ids = {a["app_id"] for a in apps}
                for ea in existing_apps:
                    aid = ea.get("app_id")
                    if aid and not aid.startswith("ent-") and not aid.startswith("onprem-") and aid not in known_ids:
                        apps.append({
                            "app_id": aid,
                            "name": ea.get("name", aid),
                            "stream_or_space": ea.get("stream_or_space", "Personal"),
                            "space_type": ea.get("space_type", "personal"),
                            "sheet_count": ea.get("sheet_count", 0),
                            "widget_count": ea.get("widget_count", 0),
                            "extraction_status": ea.get("extraction_status", "IR_COMPILED"),
                            "is_live": True,
                        })
                        known_ids.add(aid)

                # Remove legacy mock apps for this instance so catalog displays only real apps
                with self.db._get_connection() as conn:
                    conn.execute("DELETE FROM canonical_ir_cache WHERE app_id IN (SELECT app_id FROM qlik_apps WHERE tenant_id = ? AND app_id LIKE 'ent-%')", (inst_id,))
                    conn.execute("DELETE FROM compatibility_findings WHERE app_id IN (SELECT app_id FROM qlik_apps WHERE tenant_id = ? AND app_id LIKE 'ent-%')", (inst_id,))
                    conn.execute("DELETE FROM looker_explores WHERE app_id IN (SELECT app_id FROM qlik_apps WHERE tenant_id = ? AND app_id LIKE 'ent-%')", (inst_id,))
                    conn.execute("DELETE FROM generated_artifacts WHERE app_id IN (SELECT app_id FROM qlik_apps WHERE tenant_id = ? AND app_id LIKE 'ent-%')", (inst_id,))
                    conn.execute("DELETE FROM migration_jobs WHERE app_id IN (SELECT app_id FROM qlik_apps WHERE tenant_id = ? AND app_id LIKE 'ent-%')", (inst_id,))
                    conn.execute("DELETE FROM qlik_apps WHERE tenant_id = ? AND app_id LIKE 'ent-%'", (inst_id,))
                    conn.commit()

                for app in apps:
                    s_name = app.get("stream_or_space") or "Personal"
                    s_type = app.get("space_type") or ("personal" if s_name.lower() == "personal" else "managed")
                    existing_app = self.db.get_app(app["app_id"])
                    existing_s = existing_app.get("sheet_count", 0) if existing_app else 0
                    existing_w = existing_app.get("widget_count", 0) if existing_app else 0
                    s_count = max(app.get("sheet_count") or 0, existing_s)
                    w_count = max(app.get("widget_count") or 0, existing_w)
                    self.db.upsert_app(
                        app_id=app["app_id"],
                        name=app["name"],
                        stream_or_space=s_name,
                        space_type=s_type,
                        extraction_status=existing_app.get("extraction_status", "IR_COMPILED") if existing_app else app.get("extraction_status", "IR_COMPILED"),
                        sheet_count=s_count,
                        widget_count=w_count,
                        tenant_id=inst_id,
                    )



                self._send_json({"status": "SUCCESS", "discovered_count": len(apps), "apps": apps})
                return

        self._send_json({"error": "Endpoint not found"}, status=404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path.startswith("/api/instances/"):
            inst_id = path.replace("/api/instances/", "").strip("/")
            self.db.delete_instance(inst_id)
            self._send_json({"status": "DELETED", "tenant_id": inst_id})
            return
        if path.startswith("/api/leads/"):
            lead_id = path.replace("/api/leads/", "").strip("/")
            success = self.db.delete_lead(lead_id)
            if success:
                self._send_json({"status": "SUCCESS", "deleted": True, "lead_id": lead_id})
            else:
                self._send_json({"error": f"Lead '{lead_id}' not found."}, status=404)
            return
        if path.startswith("/api/policies/"):
            policy_id = path.replace("/api/policies/", "").strip("/")
            deleted = self.db.delete_policy(policy_id)
            if deleted:
                self._send_json({"status": "SUCCESS", "deleted": True, "policy_id": policy_id})
            else:
                self._send_json({"error": f"Policy '{policy_id}' not found."}, status=404)
            return
        self._send_json({"error": "Endpoint not found"}, status=404)

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, file_path: str):
        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or "application/octet-stream"
        with open(file_path, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(content)

    def _send_download(self, content_bytes: bytes, filename: str, content_type: str = "text/csv; charset=utf-8"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content_bytes)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.end_headers()
        self.wfile.write(content_bytes)


def _auto_discover_active_instance(db: DatabaseManager):
    """
    Autonomous background worker that discovers applications from the active
    Qlik instance upon server startup. Populates the local database catalog
    so that real apps are immediately available in the Web Studio without
    requiring manual CLI discovery.
    """
    try:
        active_inst = db.get_active_instance()
        if not active_inst:
            instances = db.get_instances()
            active_inst = instances[0] if instances else None
        if not active_inst:
            return

        auth_config = active_inst.get("auth_config", {})
        if isinstance(auth_config, str):
            try:
                auth_config = json.loads(auth_config)
            except Exception:
                auth_config = {}

        api_key = (auth_config.get("api_key") or "").strip().strip("'\"")
        qlik_host = (active_inst.get("qlik_host") or "").strip()

        if not qlik_host or (api_key and (api_key.startswith("demo_") or "test" in api_key.lower())):
            return

        inst_name = active_inst.get("name", "Active Instance")
        print(f"[*] Autonomous fleet discovery: indexing live applications from '{inst_name}' ({qlik_host})...")
        apps = QlikConnectionService.discover_apps_for_instance(active_inst)
        if apps:
            inst_id = active_inst["tenant_id"]
            existing_apps = db.get_apps(tenant_id=inst_id)
            known_ids = {a["app_id"] for a in apps}
            for ea in existing_apps:
                aid = ea.get("app_id")
                if aid and not aid.startswith("ent-") and not aid.startswith("onprem-") and aid not in known_ids:
                    apps.append(ea)
                    known_ids.add(aid)

            with db._get_connection() as conn:
                conn.execute(
                    "DELETE FROM qlik_apps WHERE tenant_id = ? AND (app_id LIKE 'ent-%' OR app_id LIKE 'onprem-%')",
                    (inst_id,),
                )
                conn.commit()

            for app in apps:
                s_name = app.get("stream_or_space") or "Personal"
                s_type = app.get("space_type") or ("personal" if s_name.lower() == "personal" else "managed")
                existing_app = db.get_app(app["app_id"])
                existing_s = existing_app.get("sheet_count", 0) if existing_app else 0
                existing_w = existing_app.get("widget_count", 0) if existing_app else 0
                s_count = max(app.get("sheet_count") or 0, existing_s)
                w_count = max(app.get("widget_count") or 0, existing_w)
                db.upsert_app(
                    app_id=app["app_id"],
                    name=app["name"],
                    stream_or_space=s_name,
                    space_type=s_type,
                    extraction_status=existing_app.get("extraction_status", "DISCOVERED") if existing_app else app.get("extraction_status", "DISCOVERED"),
                    sheet_count=s_count,
                    widget_count=w_count,
                    tenant_id=inst_id,
                )
            db.update_instance_status(inst_id, status="CONNECTED", version_info=f"{len(apps)} apps discovered")
            print(f"[*] Autonomous discovery complete: {len(apps)} real applications discovered & registered into catalog.")
    except Exception as e:
        print(f"[*] Autonomous discovery notice: {e}")


def run_server(port: int = 8080, db_path: str = "enterprise_migration.db", secondary_port: Optional[int] = 8085):
    """Starts the Web UI server."""
    EnterpriseMigrationHandler.db = DatabaseManager(db_path=db_path)
    EnterpriseMigrationHandler.db.seed_default_instances()

    # Launch autonomous fleet discovery in background
    discovery_thread = threading.Thread(
        target=_auto_discover_active_instance,
        args=(EnterpriseMigrationHandler.db,),
        daemon=True,
    )
    discovery_thread.start()

    try:
        server_address = ("", port)
        httpd = ThreadingHTTPServer(server_address, EnterpriseMigrationHandler)
    except OSError as e:
        if getattr(e, "errno", None) == 98 or "already in use" in str(e).lower():
            print(f"\n[!] Error: Port {port} is already in use by another process on this machine.")
            print(f"[*] Quick Fixes:")
            print(f"    1. Free port {port} by running:")
            print(f"       fuser -k {port}/tcp")
            print(f"    2. Or run on an alternate port (e.g. 8090):")
            print(f"       python3 -m enterprise_qlik.cli serve --port {port + 1 if port != 8085 else 8090}\n")
            return
        raise
    print(f"[*] Enterprise Migration Studio listening on http://localhost:{port}")

    alt_port = 8080 if port != 8080 else 8085
    target_sec_port = secondary_port if (secondary_port and secondary_port != port) else alt_port
    if target_sec_port and target_sec_port != port:
        try:
            httpd_sec = ThreadingHTTPServer(("", target_sec_port), EnterpriseMigrationHandler)
            sec_thread = threading.Thread(target=httpd_sec.serve_forever, daemon=True)
            sec_thread.start()
            print(f"[*] Enterprise Migration Studio also listening on http://localhost:{target_sec_port}")
        except Exception as e:
            print(f"[!] Note: Secondary port {target_sec_port} not bound: {e}")

    httpd.serve_forever()
