"""
Database Schema Migrations & Provisioning
=========================================
DDL definitions and automated table initialization for SQLite and PostgreSQL.
"""

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    environment_type TEXT NOT NULL,
    qlik_host TEXT NOT NULL,
    auth_config TEXT NOT NULL,
    is_active INTEGER DEFAULT 0,
    status TEXT DEFAULT 'CONFIGURED',
    version_info TEXT,
    last_tested_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS qlik_apps (
    app_id TEXT PRIMARY KEY,
    tenant_id TEXT REFERENCES tenants(tenant_id),
    name TEXT NOT NULL,
    stream_or_space TEXT,
    space_type TEXT DEFAULT 'managed',
    sheet_count INTEGER DEFAULT 0,
    widget_count INTEGER DEFAULT 0,
    extraction_status TEXT NOT NULL,
    metadata_hash TEXT,
    migration_wave TEXT DEFAULT 'unassigned',
    assigned_lead TEXT DEFAULT 'Unassigned',
    lifecycle_stage TEXT DEFAULT 'discovered',
    is_decommissioned INTEGER DEFAULT 0,
    last_extracted_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS canonical_ir_cache (
    app_id TEXT PRIMARY KEY REFERENCES qlik_apps(app_id),
    raw_metadata TEXT,
    data_layer_ir TEXT NOT NULL,
    visual_catalog_ir TEXT NOT NULL,
    ir_version TEXT DEFAULT '2.0',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS compatibility_findings (
    finding_id TEXT PRIMARY KEY,
    app_id TEXT REFERENCES qlik_apps(app_id),
    sheet_id TEXT,
    widget_id TEXT,
    category INTEGER NOT NULL,
    severity TEXT NOT NULL,
    item_type TEXT NOT NULL,
    raw_expression TEXT,
    lookml_remediation TEXT,
    status TEXT DEFAULT 'OPEN',
    assigned_to TEXT,
    scope_type TEXT,
    location TEXT,
    sheet_title TEXT,
    widget_title TEXT,
    title TEXT,
    description TEXT,
    remediation TEXT,
    estimated_remediation_hours REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS looker_explores (
    explore_id TEXT PRIMARY KEY,
    app_id TEXT REFERENCES qlik_apps(app_id),
    model_name TEXT NOT NULL,
    explore_name TEXT NOT NULL,
    root_view_name TEXT NOT NULL,
    joins_config TEXT,
    is_pre_existing INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS generated_artifacts (
    artifact_id TEXT PRIMARY KEY,
    app_id TEXT REFERENCES qlik_apps(app_id),
    artifact_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    content TEXT NOT NULL,
    git_commit_sha TEXT,
    deployed_to_looker INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS migration_jobs (
    job_id TEXT PRIMARY KEY,
    app_id TEXT REFERENCES qlik_apps(app_id),
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    progress_pct INTEGER DEFAULT 0,
    error_message TEXT,
    worker_id TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS migration_leads (
    lead_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    email TEXT,
    role TEXT NOT NULL DEFAULT 'Migration Lead',
    specialty TEXT DEFAULT 'Full-Stack Looker & dbt',
    avatar_url TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS migration_policies (
    policy_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    priority INTEGER NOT NULL,
    conditions_json TEXT NOT NULL,
    actions_json TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS okf_concepts (
    concept_path TEXT PRIMARY KEY,
    concept_type TEXT NOT NULL,
    app_id TEXT,
    title TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    extracted_json TEXT NOT NULL,
    governance_json TEXT NOT NULL,
    curated_notes TEXT,
    auto_catalog TEXT,
    raw_markdown TEXT NOT NULL,
    mtime_ns INTEGER NOT NULL,
    content_sha256 TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

def provision_sqlite(conn):
    """Executes schema initialization on SQLite database connection."""
    cursor = conn.cursor()
    cursor.executescript(SQLITE_SCHEMA)
    for col_def in [
        "ALTER TABLE qlik_apps ADD COLUMN space_type TEXT DEFAULT 'managed'",
        "ALTER TABLE qlik_apps ADD COLUMN migration_wave TEXT DEFAULT 'unassigned'",
        "ALTER TABLE qlik_apps ADD COLUMN assigned_lead TEXT DEFAULT 'Unassigned'",
        "ALTER TABLE qlik_apps ADD COLUMN lifecycle_stage TEXT DEFAULT 'discovered'",
        "ALTER TABLE qlik_apps ADD COLUMN is_decommissioned INTEGER DEFAULT 0",
        "ALTER TABLE qlik_apps ADD COLUMN bound_explore TEXT DEFAULT ''",
        "ALTER TABLE qlik_apps ADD COLUMN okf_path TEXT DEFAULT ''",
        "ALTER TABLE compatibility_findings ADD COLUMN scope_type TEXT",
        "ALTER TABLE compatibility_findings ADD COLUMN location TEXT",
        "ALTER TABLE compatibility_findings ADD COLUMN sheet_title TEXT",
        "ALTER TABLE compatibility_findings ADD COLUMN widget_title TEXT",
        "ALTER TABLE compatibility_findings ADD COLUMN title TEXT",
        "ALTER TABLE compatibility_findings ADD COLUMN description TEXT",
        "ALTER TABLE compatibility_findings ADD COLUMN remediation TEXT",
        "ALTER TABLE compatibility_findings ADD COLUMN estimated_remediation_hours REAL",
        "ALTER TABLE compatibility_findings ADD COLUMN shared_concept_ref TEXT",
        "ALTER TABLE compatibility_findings ADD COLUMN shared_across_apps INTEGER DEFAULT 1",
        "ALTER TABLE compatibility_findings ADD COLUMN incremental_effort_hours REAL",
    ]:
        try:
            cursor.execute(col_def)
        except Exception:
            pass
    conn.commit()
