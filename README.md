# Qlik-Looker-OKF: Enterprise Qlik-to-Looker OKF v0.2 Fleet Migration & Consolidation Engine

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Contract](https://img.shields.io/badge/Contract-OKF_v0.2_(Open_Knowledge_Format)-00897B.svg)](docs/PRD_OKF_Architecture.md)
[![Architecture](https://img.shields.io/badge/Architecture-3--Stage_Fleet_Consolidation-emerald.svg)](docs/PRD_OKF_Architecture.md)
[![Looker](https://img.shields.io/badge/LookML-Canonical_Explore--Centric-purple.svg)]()
[![Dependencies](https://img.shields.io/badge/Dependencies-Zero_External_pip-success.svg)]()

An enterprise-grade, **Open Knowledge Format (OKF v0.2)** native migration and semantic reconciliation suite designed for Heads of Business Intelligence, Principal Data Architects, and Analytics Engineering teams migrating **500+ Qlik Sense applications** into a single, consolidated **Google Cloud Looker** semantic layer.

Rather than translating 500 Qlik apps 1-to-1 into 500 siloed, duplicated LookML projects, **Qlik-Looker-OKF** introduces a **Stage 1.5 Fleet Semantic Reconciliation & Explore Consolidation** layer built on human-readable, Git-diffable, and LLM-navigable **OKF v0.2** Markdown (`okf_catalog/`) files.

> 📄 **Full Architectural Specification & ADRs:** See [docs/PRD_OKF_Architecture.md](docs/PRD_OKF_Architecture.md) for the complete Product Requirements Document and Architectural Decision Records (ADR-01 through ADR-06).

---

## 🏛️ 3-Stage OKF v0.2 Fleet Consolidation Architecture

```
  STAGE 1: QIX EXTRACTION                 STAGE 1.5: FLEET SEMANTIC                STAGE 2: CONSOLIDATED
  & PII SANITIZATION                      RECONCILIATION (OKF v0.2)                TARGET CODE GENERATION
┌─────────────────────────┐             ┌───────────────────────────┐            ┌─────────────────────────┐
│    500+ Qlik Apps       │ ──────────> │       okf_catalog/        │ ─────────> │  Shared LookML Project  │
│  (Cloud SaaS / QSEoW)   │             │  ├── index.md & log.md    │            │  ├── 1 View / Table     │
│  • QIX Engine / QRS     │             │  ├── explores/*.md (15-25)│            │  ├── 15-25 Explores     │
│  • Regex PII Scrubber   │             │  ├── tables/*.md   (40-60)│            │  ├── 500 Dashboards     │
│  • 3-Tier Gap Auditor   │             │  ├── metrics/*.md  (50-80)│            │  └── Shared dbt Models  │
└─────────────────────────┘             │  └── apps/*.md     (500)  │            └─────────────────────────┘
                                        └─────────────┬─────────────┘
                                                      │
                                                      ▼
                                        [Zero-Drift SQLite WAL Index]
                                        • os.scandir() st_mtime_ns (<2ms)
                                        • extracted: vs governance: split
                                        • SHA-256 optimistic concurrency
```

### Key Architectural Highlights (ADR-01 through ADR-06)

1. **Coarse-Grained OKF v0.2 Concept Hierarchy (`~630 files` for 500 Apps, not 35,000):**
   - **Canonical Explores (`explores/<slug>.md`):** 15–25 consolidated Star/Snowflake join graphs across the entire 500-app fleet (`type: explore`).
   - **Canonical Tables (`tables/<slug>.md`):** 40–60 physical/dbt tables with all fields embedded as a frontmatter array (`type: table`).
   - **Shared Metrics & Gaps (`metrics/<slug>.md`):** Cross-fleet measures, parameters, and deduplicated Category 2 dbt remediations (`type: metric`).
   - **Application & Sheet Catalogs (`apps/<slug>.md`):** 1 file per Qlik application embedding all sheets, 12-column grid widgets, and per-visual 3-tier compatibility ratings (`type: application`).
2. **Zero-Dependency YAML 1.2 Serialization via JSON-Subset Scalars:**
   - Complex Qlik Set Analysis expressions (`Sum({$<Year={$(=Max(Year))}, [Region]={"North*"}>} [Sales])`) contain characters (`{`, `}`, `$`, `:`, `"`, `#`) that break naive YAML parsers.
   - Because **YAML 1.2 is a strict superset of JSON**, all scalar and inline values in OKF frontmatter are serialized using Python's built-in `json.dumps()` and parsed with `json.loads()`, guaranteeing 100% round-trip accuracy with zero external `pip` packages (`PyYAML` is never required).
3. **Zero State-Drift via `os.scandir()` Nanosecond Write-Through Index & Dual-Namespace Frontmatter:**
   - **Filesystem-First Truth:** `okf_catalog/*.md` is the canonical system of record; SQLite (`okf_concepts`) acts as a fast query and Kanban index.
   - **Sub-2ms Incremental Sync:** Before portfolio queries, `OKFCatalogManager.scan_modified_files()` checks file `st_mtime_ns` timestamps via `os.scandir()` in `<2ms` and re-indexes only files edited on disk via VS Code, `git pull`, or AI agents.
   - **Dual-Namespace Ownership:** Every OKF file separates machine-owned metadata (`extracted:`) from human/PMO-owned metadata (`governance:`) and markdown body blocks (`<!-- BEGIN CURATED NOTES -->` vs `<!-- BEGIN AUTO-GENERATED CATALOG -->`). Re-extracting a Qlik app never overwrites wave assignments, lead owners, or architect notes.
4. **Preserved Per-Visual 3-Tier Compatibility Auditing + Fleet Effort Deduplication:**
   - Reviewers still inspect every Qlik app sheet-by-sheet and visual-by-visual (`Category 1: Direct LookML`, `Category 2: Medium / dbt`, `Category 3: Architectural Pivot`).
   - When 40 Qlik apps share the same Category 2 QVS script transformation or complex Set Analysis measure, linking them to one `metrics/<slug>.md` concept computes both **Standalone Effort (e.g., 160 hrs)** and **Incremental Consolidated Effort (4 hrs — saving 156 hrs)**.

---

## 🧭 7-View Enterprise Web Studio

The Web Studio provides a 7-stage operational workspace for BI leadership and migration engineers:

1. **🏢 1. Instances (`#tab-instances`):** Manage concurrent connections across **Qlik Cloud SaaS** and **Qlik Sense Enterprise on Windows (QSEoW)**.
2. **📊 2. Executive Command Center (`#tab-executive`):** Fleet readiness velocity, space governance breakdown, and semantic consolidation ROI.
3. **🌊 3. Migration Wave Planner (`#tab-waves`):** Interactive 5-column Kanban board, Policy Simulation Wizard, Leads Roster, and CSV/JSON portfolio exports.
4. **📂 4. Fleet & Catalog (`#tab-catalog`):** Live Qlik Cloud Space / On-Prem Stream container tree, batch extraction, and app registration.
5. **🔬 5. Stage 1: App Studio (`#tab-canvas`):** Deep-dive per-app inspection of Public & Private ("My own") sheets, 12-column visual layouts, and 3-tier gap audit grouped by sheet.
6. **🧬 6. Stage 1.5: OKF Catalog & Explore Consolidation Studio (`#tab-okf`):**
   - Run **Stage 1.5 Fleet Reconciliation** to cluster apps by shared base tables into Canonical Looker Explores (`explores/*.md`).
   - Browse `explores/`, `tables/`, `metrics/`, and `apps/` OKF v0.2 Markdown documents.
   - Edit `governance:` attributes (Wave, Lead Owner, Bound Canonical Explore) and `<!-- BEGIN CURATED NOTES -->` with SHA-256 optimistic concurrency protection.
   - Trigger **Stage 2 Fleet LookML Compilation** or download the portable `okf_catalog.zip` bundle.
7. **🚀 7. Stage 2: LookML Studio (`#tab-lookml`):** Inspect and download generated shared LookML Views, Consolidated Explores, LookML Dashboards, and dbt SQL models.

---

## 💻 Quickstart & CLI Execution

### Running the Web Studio

```bash
# Option A: Convenience launcher
./run_local_studio.sh 8085

# Option B: Direct Python CLI
python3 -m enterprise_qlik.cli serve --port 8085
```

Open **`http://localhost:8085`** (or `http://localhost:8080`) in your browser.

---

### Command Line Interface (CLI)

#### 1. Stage 1: Extract Qlik App & Emit OKF v0.2 Concept Bundle
```bash
python3 -m enterprise_qlik.cli extract \
  --app-id "05bdadd9-0358-4a45-a16f-fc30a8aa16ef" \
  --output-dir ./migration_artifacts
```

#### 2. Stage 1.5: Reconcile Fleet into Consolidated OKF v0.2 Canonical Explores
```bash
python3 -m enterprise_qlik.cli reconcile-okf \
  --db-path enterprise_migration.db \
  --similarity-threshold 0.50
```

#### 3. Validate OKF v0.2 Catalog Directory (or Canonical IR JSON)
```bash
python3 -m enterprise_qlik.cli validate \
  --ir-file ./enterprise_migration_okf_catalog
```

#### 4. Stage 2: Generate Consolidated Fleet LookML & dbt Project from OKF v0.2 Catalog
*(Consumes ONLY `okf_catalog/` — zero Qlik connection or Stage 1 imports required)*
```bash
python3 -m enterprise_qlik.cli generate \
  --ir-file ./enterprise_migration_okf_catalog \
  --model-name "consolidated_enterprise_bi" \
  --output-dir ./looker_project
```

---

## 🧪 Hermetic Test Suite

```bash
python3 -m unittest discover tests -v
```

Includes dedicated unit and integration tests for OKF v0.2 frontmatter serialization, collision-free slugs, dual-namespace non-destructive re-extraction, `os.scandir()` nanosecond drift reconciliation, Stage 1.5 Explore clustering, and Stage 2 Fleet LookML synthesis (`tests/test_okf_architecture.py` and `tests/test_server.py`).

---

## 📦 Project Layout

```text
Qlik-Looker-OKF/
├── docs/
│   └── PRD_OKF_Architecture.md    # Full OKF v0.2 PRD & Architectural Decision Records (ADR 01-06)
├── enterprise_qlik/
│   ├── okf/                       # === STAGE 1.5: OKF v0.2 SEMANTIC CATALOG ENGINE ===
│   │   ├── frontmatter.py         # ADR-02 slugger, ADR-03 JSON-subset YAML 1.2 parser, ADR-05 merger
│   │   ├── validator.py           # OKF v0.2 document, index.md, log.md & link graph validator
│   │   └── catalog.py             # OKFCatalogManager, os.scandir() sync & Fleet Explore Reconciler
│   ├── stage1_extract/            # === STAGE 1: Source Extractor, Sanitizer & 3-Tier Gap Auditor ===
│   ├── stage2_lookml/             # === STAGE 2: Decoupled Consolidated LookML & dbt Generator ===
│   ├── storage/                   # === SQLITE WAL WRITE-THROUGH INDEX & MIGRATIONS ===
│   ├── web/                       # === 7-VIEW WEB STUDIO & HTTP API SERVER ===
│   └── cli.py                     # Unified Command Line Interface (extract, reconcile-okf, validate, generate)
├── tests/                         # Hermetic Unit & Integration Tests
├── run_local_studio.sh            # One-click Web Studio launcher
├── pyproject.toml
└── README.md
```

---

## 📄 License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.
