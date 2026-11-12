// Enterprise Migration Studio Client Controller
let currentCanonicalIR = null;
let currentArtifacts = null;
let currentFindings = [];
let groupBySheet = true;
let currentAuditCatFilter = "all";
let currentAuditSheetFilter = "all";
let activeLookMLType = "explore";
let allInstances = [];
let activeInstance = null;
let currentExecutiveData = null;
let currentWavesData = null;
let cachedLeads = [];
let selectedAppIds = new Set();
let allWaveApps = [];
const autoDiscoveredTenants = new Set();

document.addEventListener("DOMContentLoaded", async () => {
  setupTabs();
  setupEventListeners();
  await loadInstances();
  await loadLeads();
  await loadCatalog();
  if (currentAppId) {
    runStage1(false, currentAppId); // Run initial extraction for first discovered app without blocking overlay
  }
});

function switchTab(tabId) {
  const tabBtns = document.querySelectorAll("nav.tabs-nav .tab-btn");
  tabBtns.forEach(b => b.classList.toggle("active", b.dataset.tab === tabId));
  document.querySelectorAll(".tab-pane").forEach(p => p.classList.toggle("active", p.id === tabId));
  window.location.hash = tabId;
  window.scrollTo({ top: 0, behavior: "smooth" });

  if (tabId === "tab-executive") {
    loadExecutiveMetrics();
  } else if (tabId === "tab-waves") {
    loadLeads();
    loadWavesData();
  } else if (tabId === "tab-catalog") {
    loadLeads();
    loadCatalog();
  } else if (tabId === "tab-okf") {
    loadOKFCatalog();
  } else if (tabId === "tab-canvas") {
    const isMatchingIR = currentCanonicalIR && (
      (currentCanonicalIR.app_metadata && currentCanonicalIR.app_metadata.app_id === currentAppId) ||
      (currentCanonicalIR.app_id === currentAppId)
    );
    if (isMatchingIR) {
      switchStudioView(currentStudioView || "sheet");
    } else if (!isExtractingStage1) {
      if (currentAppId) {
        runStage1(true, currentAppId);
      } else {
        resetStudioEmptyState();
      }
    }
  }
}

function selectEnvironmentType(type) {
  document.getElementById("form-env-type").value = type;
  const isCloud = type === "cloud";
  document.getElementById("btn-toggle-cloud").classList.toggle("active", isCloud);
  document.getElementById("btn-toggle-onprem").classList.toggle("active", !isCloud);
  document.getElementById("fields-cloud").style.display = isCloud ? "block" : "none";
  document.getElementById("fields-onprem").style.display = isCloud ? "none" : "block";
  document.getElementById("form-card-subtitle").textContent = isCloud
    ? "Configure connection credentials for Qlik Cloud SaaS via Bearer API keys."
    : "Configure connection credentials for Qlik Sense Enterprise on Windows (QSEoW) via mTLS certificates on port 4242.";
}

async function loadInstances() {
  try {
    const res = await fetch("/api/instances");
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: Failed to fetch instances`);
    }
    const data = await res.json();
    allInstances = data.instances || [];
    activeInstance = data.active_instance || (allInstances.length > 0 ? allInstances[0] : null);

    renderHeaderInstancePill(activeInstance);
    renderHeroInstance(activeInstance);
    renderInstanceCards(allInstances, activeInstance);
    renderCatalogTargetBanner(activeInstance);
  } catch (err) {
    console.error("Failed to load instances:", err);
    activeInstance = null;
    renderHeaderInstancePill(null);
    renderHeroInstance(null);
    renderCatalogTargetBanner(null);
  }
}

function renderHeaderInstancePill(inst) {
  const dot = document.getElementById("header-conn-dot");
  const nameEl = document.getElementById("header-instance-name");
  const typeEl = document.getElementById("header-instance-type");

  if (!inst) {
    if (dot) dot.className = "indicator-dot disconnected";
    if (nameEl) nameEl.textContent = "No Qlik Connected";
    if (typeEl) typeEl.textContent = "Click to configure";
    return;
  }

  const isConnected = inst.status === "CONNECTED";
  if (dot) dot.className = isConnected ? "indicator-dot" : (inst.status === "ERROR" ? "indicator-dot error" : "indicator-dot disconnected");
  if (nameEl) nameEl.textContent = inst.name;
  if (typeEl) typeEl.textContent = `${inst.environment_type === "cloud" ? "Qlik Cloud (SaaS)" : "QSEoW On-Prem"} · ${isConnected ? "Connected" : (inst.status || "Configured")}`;
}

function renderHeroInstance(inst) {
  const nameEl = document.getElementById("hero-instance-name");
  const hostEl = document.getElementById("hero-instance-host");
  const typeEl = document.getElementById("hero-instance-type");
  const authEl = document.getElementById("hero-instance-auth");
  const statusEl = document.getElementById("hero-instance-status");
  const testedEl = document.getElementById("hero-instance-tested");

  if (!inst) {
    if (nameEl) nameEl.textContent = "No Active Instance Selected";
    if (hostEl) hostEl.textContent = "Please add or select an instance below";
    if (typeEl) typeEl.textContent = "—";
    if (authEl) authEl.textContent = "—";
    if (statusEl) {
      statusEl.textContent = "○ DISCONNECTED";
      statusEl.style.color = "var(--text-muted)";
    }
    if (testedEl) testedEl.textContent = "No active connection";
    return;
  }

  if (nameEl) nameEl.textContent = inst.name;
  if (hostEl) hostEl.textContent = inst.qlik_host || "—";
  if (typeEl) typeEl.textContent = inst.environment_type === "cloud" ? "Qlik Cloud (SaaS)" : "QSEoW (On-Premises)";
  
  const authLabel = inst.environment_type === "cloud" ? "Bearer API Key" : `mTLS Certificates (Port ${inst.auth_config?.qrs_port || 4242})`;
  if (authEl) authEl.textContent = authLabel;

  const isConnected = inst.status === "CONNECTED";
  if (statusEl) {
    statusEl.textContent = isConnected ? "● CONNECTED" : (inst.status === "ERROR" ? "✕ ERROR" : "○ CONFIGURED");
    statusEl.style.color = isConnected ? "var(--accent-success)" : (inst.status === "ERROR" ? "var(--accent-danger)" : "var(--text-muted)");
  }
  
  if (testedEl) {
    testedEl.textContent = inst.version_info || (inst.last_tested_at ? `Tested ${new Date(inst.last_tested_at).toLocaleTimeString()}` : "Ready for connection test");
  }
}

function renderCatalogTargetBanner(inst) {
  const nameEl = document.getElementById("catalog-target-instance");
  const badgeEl = document.getElementById("catalog-target-badge");
  const statusEl = document.getElementById("catalog-target-status");

  if (!inst) {
    if (nameEl) nameEl.textContent = "None selected";
    if (badgeEl) {
      badgeEl.textContent = "—";
      badgeEl.style.background = "var(--bg-subtle)";
      badgeEl.style.color = "var(--text-muted)";
    }
    if (statusEl) {
      statusEl.textContent = "○ Disconnected";
      statusEl.style.color = "var(--text-muted)";
    }
    return;
  }

  if (nameEl) nameEl.textContent = inst.name;
  if (badgeEl) {
    badgeEl.textContent = inst.environment_type === "cloud" ? "CLOUD" : "ON-PREM";
    badgeEl.style.background = inst.environment_type === "cloud" ? "var(--primary-light)" : "#E0E7FF";
    badgeEl.style.color = inst.environment_type === "cloud" ? "var(--primary)" : "#4338CA";
  }
  if (statusEl) {
    const isConn = inst.status === "CONNECTED";
    statusEl.textContent = isConn ? "● Connected" : `○ ${inst.status || "Configured"}`;
    statusEl.style.color = isConn ? "var(--accent-success)" : "var(--text-muted)";
  }
}

function renderInstanceCards(instances, activeInst) {
  const container = document.getElementById("instance-cards-container");
  if (!container) return;
  container.innerHTML = "";

  if (!instances || instances.length === 0) {
    container.innerHTML = `
      <div style="grid-column: 1 / -1; padding: 32px; text-align: center; color: var(--text-muted); background: var(--bg-subtle); border-radius: 8px;">
        No Qlik instances configured yet. Use the form below to add your first Qlik Cloud or On-Premises environment.
      </div>
    `;
    return;
  }

  instances.forEach(inst => {
    const isActive = activeInst && inst.tenant_id === activeInst.tenant_id;
    const isCloud = inst.environment_type === "cloud";
    const isConnected = inst.status === "CONNECTED";

    const card = document.createElement("div");
    card.className = `instance-card ${isActive ? "active" : ""}`;
    card.innerHTML = `
      <div>
        <div class="instance-card-header">
          <div class="instance-card-title">
            <span>${isCloud ? "☁️" : "🖥️"}</span>
            <span>${inst.name}</span>
          </div>
          <span class="badge" style="${isActive ? 'background: #EEF2FF; color: var(--primary); border: 1px solid var(--primary-border);' : 'background: var(--bg-subtle); color: var(--text-secondary);'}">
            ${isActive ? "★ ACTIVE CONNECTION" : "STANDBY"}
          </span>
        </div>

        <div class="instance-card-body" style="margin-top: 14px;">
          <div class="instance-meta-row">
            <span class="instance-meta-label">TYPE</span>
            <span style="font-weight: 600; color: var(--text-primary);">${isCloud ? "Qlik Cloud SaaS" : "Qlik Sense Enterprise (QSEoW)"}</span>
          </div>
          <div class="instance-meta-row">
            <span class="instance-meta-label">ENDPOINT</span>
            <span style="font-family: var(--font-mono); font-size: 11.5px; color: var(--text-secondary);">${inst.qlik_host || "—"}</span>
          </div>
          <div class="instance-meta-row">
            <span class="instance-meta-label">STATUS</span>
            <span style="color: ${isConnected ? 'var(--accent-success)' : (inst.status === 'ERROR' ? 'var(--accent-danger)' : 'var(--text-muted)')}; font-weight: 600;">
              ${isConnected ? "● Connected" : (inst.status === "ERROR" ? "✕ Failed" : "○ Configured")}
            </span>
            <span style="font-size: 11px; color: var(--text-muted);">(${inst.version_info || "Ready"})</span>
          </div>
        </div>
      </div>

      <div class="instance-card-actions">
        ${!isActive ? `<button class="btn-primary" style="padding: 6px 12px; font-size: 12px;" onclick="activateInstance('${inst.tenant_id}')">✓ Set Active</button>` : ''}
        <button class="btn-secondary" style="padding: 6px 12px; font-size: 12px;" onclick="testInstance('${inst.tenant_id}')">⚡ Test</button>
        <button class="btn-secondary" style="padding: 6px 12px; font-size: 12px;" onclick="discoverAppsForInstance('${inst.tenant_id}')">🔍 Discover</button>
        <button class="btn-secondary" style="padding: 6px 10px; font-size: 12px;" onclick="editInstance('${inst.tenant_id}')" title="Edit credentials">✏️</button>
        <button class="btn-secondary" style="padding: 6px 10px; font-size: 12px; color: var(--accent-danger);" onclick="deleteInstance('${inst.tenant_id}')" title="Delete instance">🗑️</button>
      </div>
    `;
    container.appendChild(card);
  });
}

async function testInstance(tenantId) {
  showLoading("Testing Qlik Connection...", "Verifying host reachability, mTLS certificates / API key auth...");
  try {
    const res = await fetch("/api/instances/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant_id: tenantId })
    });
    const result = await res.json();
    hideLoading();
    if (result.connected) {
      showToast(`Connected successfully! Latency: ${result.latency_ms || 20}ms (${result.version || result.user || 'Active'})`);
    } else {
      showToast(`Connection error: ${result.error || "Check credentials and host"}`, "error");
    }
    await loadInstances();
  } catch (err) {
    hideLoading();
    showToast(`Test failed: ${err.message}`, "error");
  }
}

async function testActiveInstance() {
  if (!activeInstance) {
    try {
      const res = await fetch("/api/instances/active");
      if (res.ok) {
        const data = await res.json();
        if (data.active_instance) activeInstance = data.active_instance;
      }
    } catch (e) {
      console.warn("Could not fetch active instance:", e);
    }
  }
  if (!activeInstance && allInstances.length > 0) {
    activeInstance = allInstances[0];
  }
  if (!activeInstance) {
    showToast("No active instance selected. Please add or select an instance below.", "error");
    return;
  }
  await testInstance(activeInstance.tenant_id);
}

async function activateInstance(tenantId) {
  showLoading("Switching Active Qlik Environment...", "Loading instance connection profile...");
  try {
    const res = await fetch(`/api/instances/${tenantId}/activate`, { method: "POST" });
    await res.json();
    hideLoading();
    showToast("Qlik active instance updated!");
    await loadInstances();
    await loadCatalog();
  } catch (err) {
    hideLoading();
    showToast(`Failed to activate: ${err.message}`, "error");
  }
}

async function discoverAppsForInstance(tenantId) {
  showLoading("Discovering Qlik Applications...", "Connecting to instance and pulling application catalog metadata...");
  try {
    const res = await fetch(`/api/instances/${tenantId}/discover`, { method: "POST" });
    const data = await res.json();
    hideLoading();
    showToast(`Discovered ${data.discovered_count || 0} applications!`);
    await loadCatalog();
    switchTab("tab-catalog");
  } catch (err) {
    hideLoading();
    showToast(`Discovery error: ${err.message}`, "error");
  }
}

async function discoverActiveApps() {
  if (!activeInstance) {
    try {
      const res = await fetch("/api/instances/active");
      if (res.ok) {
        const data = await res.json();
        if (data.active_instance) activeInstance = data.active_instance;
      }
    } catch (e) {
      console.warn("Could not fetch active instance:", e);
    }
  }
  if (!activeInstance && allInstances.length > 0) {
    activeInstance = allInstances[0];
  }
  if (!activeInstance) {
    showToast("No active instance selected. Please add or select an instance below.", "error");
    return;
  }
  await discoverAppsForInstance(activeInstance.tenant_id);
}

async function testFormConnection() {
  const envType = document.getElementById("form-env-type").value;
  const name = document.getElementById("form-instance-name").value || "Test Instance";
  const tenantId = document.getElementById("form-tenant-id").value;
  const banner = document.getElementById("test-result-panel");
  banner.style.display = "block";
  banner.className = "test-banner";
  banner.style.background = "var(--bg-subtle)";
  banner.style.color = "var(--text-secondary)";
  banner.innerHTML = "<span>⏳ Testing connection to Qlik...</span>";

  let payload = {
    name: name,
    environment_type: envType,
  };
  if (tenantId) {
    payload.tenant_id = tenantId;
  }

  if (envType === "cloud") {
    payload.qlik_host = document.getElementById("form-cloud-url").value.trim();
    payload.auth_config = {
      api_key: document.getElementById("form-cloud-key").value.trim(),
      web_integration_id: document.getElementById("form-cloud-web-id").value.trim(),
    };
  } else {
    payload.qlik_host = document.getElementById("form-onprem-host").value.trim();
    payload.auth_config = {
      qrs_port: parseInt(document.getElementById("form-onprem-qrs-port").value) || 4242,
      engine_port: parseInt(document.getElementById("form-onprem-engine-port").value) || 4747,
      cert_path: document.getElementById("form-onprem-cert").value.trim(),
      key_path: document.getElementById("form-onprem-key").value.trim(),
      ca_path: document.getElementById("form-onprem-ca").value.trim(),
      user_directory: document.getElementById("form-onprem-userdir").value.trim() || "INTERNAL",
      user_id: document.getElementById("form-onprem-userid").value.trim() || "sa_api",
      verify_ssl: document.getElementById("form-onprem-verify-ssl").checked,
    };
  }

  try {
    const res = await fetch("/api/instances/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await res.json();
    if (result.connected) {
      banner.className = "test-banner success";
      banner.innerHTML = `
        <div style="font-weight: 700; margin-bottom: 4px;">✓ Connected Successfully (${result.latency_ms || 18}ms)</div>
        <div>${result.message || ''} Environment: <strong>${result.version || 'Qlik Active'}</strong>. Principal: <code>${result.user || 'Authenticated'}</code>.</div>
      `;
      if (tenantId) {
        await loadInstances();
      }
    } else {
      banner.className = "test-banner error";
      banner.innerHTML = `
        <div style="font-weight: 700; margin-bottom: 4px;">✕ Connection Failed (${result.latency_ms || 0}ms)</div>
        <div>${result.error || 'Check host, ports, and credentials.'}</div>
        ${result.tip ? `<div style="margin-top: 6px; font-size: 11.5px; opacity: 0.9;">💡 Tip: ${result.tip}</div>` : ''}
      `;
    }
  } catch (err) {
    banner.className = "test-banner error";
    banner.innerHTML = `<strong>Error:</strong> ${err.message}`;
  }
}

async function saveInstance() {
  const envType = document.getElementById("form-env-type").value;
  const tenantId = document.getElementById("form-tenant-id").value;
  const name = document.getElementById("form-instance-name").value.trim();

  let qlikHost = "";
  let authConfig = {};

  if (envType === "cloud") {
    qlikHost = document.getElementById("form-cloud-url").value.trim();
    authConfig = {
      api_key: document.getElementById("form-cloud-key").value.trim(),
      web_integration_id: document.getElementById("form-cloud-web-id").value.trim(),
    };
  } else {
    qlikHost = document.getElementById("form-onprem-host").value.trim();
    authConfig = {
      qrs_port: parseInt(document.getElementById("form-onprem-qrs-port").value) || 4242,
      engine_port: parseInt(document.getElementById("form-onprem-engine-port").value) || 4747,
      cert_path: document.getElementById("form-onprem-cert").value.trim(),
      key_path: document.getElementById("form-onprem-key").value.trim(),
      ca_path: document.getElementById("form-onprem-ca").value.trim(),
      user_directory: document.getElementById("form-onprem-userdir").value.trim() || "INTERNAL",
      user_id: document.getElementById("form-onprem-userid").value.trim() || "sa_api",
      verify_ssl: document.getElementById("form-onprem-verify-ssl").checked,
    };
  }

  showLoading("Saving Qlik Instance Profile...", "Writing configuration to application database...");
  try {
    const res = await fetch("/api/instances", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tenant_id: tenantId || undefined,
        name: name,
        environment_type: envType,
        qlik_host: qlikHost,
        auth_config: authConfig,
        is_active: true,
      })
    });
    const result = await res.json();
    hideLoading();
    showToast("Instance profile saved and set as active!");
    resetInstanceForm();
    await loadInstances();
    await loadCatalog();
  } catch (err) {
    hideLoading();
    showToast(`Save failed: ${err.message}`, "error");
  }
}

function editInstance(tenantId) {
  const inst = allInstances.find(i => i.tenant_id === tenantId);
  if (!inst) return;
  document.getElementById("form-tenant-id").value = inst.tenant_id;
  document.getElementById("form-instance-name").value = inst.name;
  selectEnvironmentType(inst.environment_type);

  if (inst.environment_type === "cloud") {
    document.getElementById("form-cloud-url").value = inst.qlik_host || "";
    document.getElementById("form-cloud-key").value = inst.auth_config?.api_key || "";
    document.getElementById("form-cloud-web-id").value = inst.auth_config?.web_integration_id || "";
  } else {
    document.getElementById("form-onprem-host").value = inst.qlik_host || "";
    document.getElementById("form-onprem-qrs-port").value = inst.auth_config?.qrs_port || 4242;
    document.getElementById("form-onprem-engine-port").value = inst.auth_config?.engine_port || 4747;
    document.getElementById("form-onprem-cert").value = inst.auth_config?.cert_path || "";
    document.getElementById("form-onprem-key").value = inst.auth_config?.key_path || "";
    document.getElementById("form-onprem-ca").value = inst.auth_config?.ca_path || "";
    document.getElementById("form-onprem-userdir").value = inst.auth_config?.user_directory || "INTERNAL";
    document.getElementById("form-onprem-userid").value = inst.auth_config?.user_id || "sa_api";
    document.getElementById("form-onprem-verify-ssl").checked = Boolean(inst.auth_config?.verify_ssl);
  }

  document.getElementById("form-card-title").textContent = `Edit Qlik Instance: ${inst.name}`;
  document.getElementById("btn-save-instance").textContent = "💾 Update Instance";
  scrollToInstanceForm();
}

async function deleteInstance(tenantId) {
  const inst = allInstances.find(i => i.tenant_id === tenantId);
  const name = inst ? inst.name : tenantId;
  if (!confirm(`Are you sure you want to delete the instance profile '${name}'?`)) return;

  try {
    const res = await fetch(`/api/instances/${tenantId}`, { method: "DELETE" });
    await res.json();
    showToast(`Instance profile deleted.`);
    await loadInstances();
    await loadCatalog();
  } catch (err) {
    showToast(`Delete failed: ${err.message}`, "error");
  }
}

function resetInstanceForm() {
  document.getElementById("form-tenant-id").value = "";
  document.getElementById("form-instance-name").value = "";
  document.getElementById("form-card-title").textContent = "Add or Configure Qlik Instance";
  document.getElementById("btn-save-instance").textContent = "💾 Save Instance Profile";
  document.getElementById("test-result-panel").style.display = "none";
}

function scrollToInstanceForm() {
  const el = document.getElementById("instance-form-card");
  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
}

function setupTabs() {
  const tabBtns = document.querySelectorAll("nav.tabs-nav .tab-btn");
  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      switchTab(btn.dataset.tab);
    });
  });
  if (window.location.hash) {
    const hash = window.location.hash.replace("#", "");
    if (document.getElementById(hash)) switchTab(hash);
  }

  const lookmlSubtabs = document.querySelectorAll("#lookml-subtabs .btn-secondary");
  lookmlSubtabs.forEach(btn => {
    btn.addEventListener("click", () => {
      lookmlSubtabs.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      activeLookMLType = btn.dataset.file;
      renderLookMLFile(activeLookMLType);
    });
  });

  const filterBtns = document.querySelectorAll("#audit-filter-bar button[data-cat]");
  filterBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      filterBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      renderFindings(btn.dataset.cat);
    });
  });
}

function setupEventListeners() {
  const refreshBtn = document.getElementById("btn-refresh-catalog");
  if (refreshBtn) refreshBtn.addEventListener("click", refreshFleetCatalog);
  const run1Btn = document.getElementById("btn-run-stage1");
  if (run1Btn) run1Btn.addEventListener("click", () => runStage1(true));
  const run2Btn = document.getElementById("btn-run-stage2");
  if (run2Btn) run2Btn.addEventListener("click", runStage2);
  const dlBtn = document.getElementById("btn-download-ir");
  if (dlBtn) dlBtn.addEventListener("click", downloadIRBundle);
  const copyBtn = document.getElementById("btn-copy-lookml");
  if (copyBtn) copyBtn.addEventListener("click", copyLookMLCode);
}

function showLoading(title, subtext) {
  const overlay = document.getElementById("loading-overlay");
  document.getElementById("loading-text").textContent = title;
  document.getElementById("loading-subtext").textContent = subtext;
  overlay.style.display = "flex";
}

function hideLoading() {
  const overlay = document.getElementById("loading-overlay");
  overlay.style.display = "none";
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

let currentCatalogViewMode = "tree";
let currentFleetHierarchy = [];
let currentFleetSummary = null;
let selectedTreeNodeId = null;

function setCatalogViewMode(mode) {
  currentCatalogViewMode = mode;
  const treeBtn = document.getElementById("btn-view-tree");
  const tableBtn = document.getElementById("btn-view-table");
  const treeView = document.getElementById("catalog-tree-view");
  const tableView = document.getElementById("catalog-table-view");

  if (mode === "tree") {
    if (treeBtn) treeBtn.classList.add("active");
    if (tableBtn) tableBtn.classList.remove("active");
    if (treeView) treeView.style.display = "grid";
    if (tableView) tableView.style.display = "none";
  } else {
    if (treeBtn) treeBtn.classList.remove("active");
    if (tableBtn) tableBtn.classList.add("active");
    if (treeView) treeView.style.display = "none";
    if (tableView) tableView.style.display = "block";
  }
}


async function refreshFleetCatalog() {
  const btn = document.getElementById("btn-refresh-catalog");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "🔄 Syncing Fleet...";
  }
  showLoading("Syncing Qlik Fleet Catalog...", "Connecting to active Qlik instance and pulling live applications, spaces, and sheets...");
  try {
    const targetInstId = (activeInstance && activeInstance.tenant_id) ? activeInstance.tenant_id : "";
    if (!targetInstId) { alert("Please select an active Qlik instance first."); return; }
    const res = await fetch(`/api/instances/${targetInstId}/discover`, { method: "POST" });
    if (res.ok) {
      const data = await res.json();
      await loadCatalog();
      showToast(`Fleet synced: ${data.discovered_count || 0} applications updated from Qlik.`);
    } else {
      await loadCatalog();
      showToast("Fleet catalog refreshed from database.");
    }
  } catch (err) {
    console.error("Refresh error:", err);
    await loadCatalog();
    showToast("Fleet catalog refreshed.");
  } finally {
    hideLoading();
    if (btn) {
      btn.disabled = false;
      btn.textContent = "🔄 Refresh Fleet";
    }
  }
}

async function loadCatalog() {
  try {
    const [fleetRes, appsRes] = await Promise.all([
      fetch("/api/fleet/status"),
      fetch("/api/apps")
    ]);

    let fleetData = {};
    if (fleetRes.ok) {
      fleetData = await fleetRes.json();
    }

    let appsData = { apps: [] };
    if (appsRes.ok) {
      appsData = await appsRes.json();
    }
    let apps = appsData.apps || [];

    // Autonomous Fleet Discovery: If catalog is currently empty for active instance, auto-discover immediately
    if (apps.length === 0 && activeInstance && activeInstance.tenant_id && !autoDiscoveredTenants.has(activeInstance.tenant_id)) {
      const authConfig = typeof activeInstance.auth_config === "string" ? JSON.parse(activeInstance.auth_config || "{}") : (activeInstance.auth_config || {});
      const hasKey = Boolean(authConfig.api_key || authConfig.cert_path || authConfig.token);
      const isDemo = authConfig.api_key && authConfig.api_key.startsWith("demo_");
      if (activeInstance.qlik_host && hasKey && !isDemo) {
        autoDiscoveredTenants.add(activeInstance.tenant_id);
        const tbody = document.querySelector("#apps-table tbody");
        if (tbody) {
          tbody.innerHTML = `<tr><td colspan="11" style="text-align: center; color: var(--primary); padding: 36px;">
            <div style="display: flex; align-items: center; justify-content: center; gap: 10px; font-size: 14px;">
              <span class="spinner-small" style="display:inline-block; vertical-align:middle;"></span>
              <strong>Autonomous Fleet Discovery in progress...</strong> Indexing live applications from <em>${escapeHtml(activeInstance.name)}</em>...
            </div>
          </td></tr>`;
        }
        const treeRoot = document.getElementById("fleet-tree-root");
        if (treeRoot) {
          treeRoot.innerHTML = `<div style="color: var(--primary); padding: 24px; text-align: center;">
            <span class="spinner-small" style="display:inline-block; vertical-align:middle; margin-right:8px;"></span>
            Connecting to <strong>${escapeHtml(activeInstance.name)}</strong> and indexing fleet...
          </div>`;
        }
        try {
          const discRes = await fetch(`/api/instances/${encodeURIComponent(activeInstance.tenant_id)}/discover`, { method: "POST" });
          if (discRes.ok) {
            const discData = await discRes.json();
            if (discData.discovered_count > 0) {
              showToast(`Autonomous Discovery: ${discData.discovered_count} application(s) indexed from ${activeInstance.name}!`);
            }
            await loadInstances();
            await loadCatalog();
            return;
          }
        } catch (e) {
          console.warn("Autonomous discovery notice:", e);
        }
      }
    }

    allWaveApps = apps;
    if (apps.length > 0 && !currentAppId) {
      currentAppId = apps[0].app_id;
    }

    const summary = fleetData.summary || {
      total_apps: apps.length,
      discovered_count: apps.filter(a => a.extraction_status === "DISCOVERED").length,
      ir_compiled_count: apps.filter(a => a.extraction_status === "IR_COMPILED").length,
      lookml_ready_count: apps.filter(a => a.extraction_status === "LOOKML_GENERATED").length,
      completion_pct: apps.length > 0 ? Math.round((apps.filter(a => a.extraction_status !== "DISCOVERED").length / apps.length) * 100) : 0,
      total_sheets: apps.reduce((s, a) => s + (a.sheet_count || 0), 0),
      total_widgets: apps.reduce((s, a) => s + (a.widget_count || 0), 0)
    };

    currentFleetSummary = summary;
    currentFleetHierarchy = fleetData.hierarchy || fleetData.tree || [];

    // Executive KPI stat cards
    const statTotal = document.getElementById("fleet-stat-total");
    if (statTotal) statTotal.textContent = summary.total_apps;

    const statCompiled = document.getElementById("fleet-stat-compiled");
    if (statCompiled) statCompiled.textContent = summary.ir_compiled_count;

    const progressFill = document.getElementById("fleet-progress-fill");
    if (progressFill) progressFill.style.width = `${summary.completion_pct}%`;

    const statPct = document.getElementById("fleet-stat-pct");
    if (statPct) statPct.textContent = `${summary.completion_pct}% Stage 1 Complete (${summary.ir_compiled_count}/${summary.total_apps} apps)`;

    const statLookml = document.getElementById("fleet-stat-lookml");
    if (statLookml) statLookml.textContent = summary.lookml_ready_count;

    const statAssets = document.getElementById("fleet-stat-assets");
    if (statAssets) statAssets.textContent = `${summary.total_sheets} Sheets · ${summary.total_widgets} Visual Tiles`;

    const heroAppsEl = document.getElementById("hero-instance-apps");
    if (heroAppsEl) heroAppsEl.textContent = summary.total_apps;

    // Render tree view & flat table
    renderFleetHierarchyTree(currentFleetHierarchy);
    renderAppsTable(apps);

  } catch (err) {
    console.error("Failed to load catalog & fleet status:", err);
  }
}

function renderAppsTable(apps) {
  const tbody = document.querySelector("#apps-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (apps.length === 0) {
    const instName = activeInstance ? activeInstance.name : "active instance";
    tbody.innerHTML = `<tr><td colspan="11" style="text-align: center; color: var(--text-muted); padding: 32px;">No applications found in ${escapeHtml(instName)}. If applications exist in this tenant, verify API key permissions, or click "🔄 Refresh Fleet" above.</td></tr>`;
    return;
  }

  apps.forEach(app => {
    // Container Type Badge
    let containerBadge = `<span class="badge" style="background: #FDF4FF; color: #A21CAF; border: 1px solid #F5D0FE;">👤 Personal</span>`;
    const st = (app.space_type || (app.stream_or_space && app.stream_or_space.toLowerCase() === "personal" ? "personal" : "managed")).toLowerCase();
    if (st === "managed") {
      containerBadge = `<span class="badge" style="background: #EFF6FF; color: #1D4ED8; border: 1px solid #BFDBFE;">🛡️ Managed</span>`;
    } else if (st === "shared") {
      containerBadge = `<span class="badge" style="background: #F0FDF4; color: #15803D; border: 1px solid #BBF7D0;">👥 Shared</span>`;
    } else if (st === "personal") {
      containerBadge = `<span class="badge" style="background: #FDF4FF; color: #A21CAF; border: 1px solid #F5D0FE;">👤 Personal</span>`;
    } else if (st === "stream") {
      containerBadge = `<span class="badge" style="background: #F8FAFC; color: #475569; border: 1px solid #E2E8F0;">📡 Stream</span>`;
    } else if (st === "work") {
      containerBadge = `<span class="badge" style="background: #FFFBEB; color: #B45309; border: 1px solid #FDE68A;">🔧 Work</span>`;
    }

    // Migration Wave Badge
    const wave = app.migration_wave || "unassigned";
    let waveBadge = `<span class="badge" style="background: #F1F5F9; color: #64748B;">Backlog</span>`;
    if (app.is_decommissioned || wave === "decommissioned") {
      waveBadge = `<span class="badge" style="background: #FEE2E2; color: #991B1B;">Retired</span>`;
    } else if (wave === "wave1") {
      waveBadge = `<span class="badge" style="background: #D1FAE5; color: #065F46; font-weight: 600;">Wave 1 (Quick Win)</span>`;
    } else if (wave === "wave2") {
      waveBadge = `<span class="badge" style="background: #EEF2FF; color: #3730A3; font-weight: 600;">Wave 2 (Governed)</span>`;
    } else if (wave === "wave3") {
      waveBadge = `<span class="badge" style="background: #FEF3C7; color: #92400E; font-weight: 600;">Wave 3 (Complex)</span>`;
    }

    // Lead Badge
    const lead = app.assigned_lead || "Unassigned";
    const leadObj = cachedLeads.find(l => l.name === lead);
    const isAI = lead.toLowerCase().includes("ai ") || lead.toLowerCase().includes("agent") || (leadObj && (leadObj.role || "").toLowerCase().includes("agent")) || (leadObj && (leadObj.role || "").toLowerCase().includes("runner"));
    const leadIcon = lead === "Unassigned" ? "" : (isAI ? "🤖 " : "👤 ");
    const leadRoleTitle = leadObj ? `${leadObj.role}${leadObj.specialty ? ' · ' + leadObj.specialty : ''}` : '';
    const leadBadge = `<span class="badge" title="${escapeHtml(leadRoleTitle)}" style="background: ${lead === 'Unassigned' ? '#F8FAFC' : (isAI ? '#F3E8FF' : '#EFF6FF')}; color: ${lead === 'Unassigned' ? '#64748B' : (isAI ? '#7E22CE' : '#1D4ED8')}; font-weight: 500;">${leadIcon}${escapeHtml(lead)}</span>`;

    // Extraction Status Badge
    let statusBadge = `<span class="badge" style="background: #F1F5F9; color: #475569;">DISCOVERED</span>`;
    if (app.extraction_status === "IR_COMPILED") {
      statusBadge = `<span class="badge" style="background: #EEF2FF; color: #4F46E5; border: 1px solid #C7D2FE;">● IR COMPILED</span>`;
    } else if (app.extraction_status === "LOOKML_GENERATED" || app.extraction_status === "LOOKML_READY") {
      statusBadge = `<span class="badge" style="background: #ECFDF5; color: #059669; border: 1px solid #A7F3D0;">✔ LOOKML READY</span>`;
    }

    const isChecked = selectedAppIds.has(app.app_id);

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td style="text-align: center;">
        <input type="checkbox" class="app-row-checkbox" value="${escapeHtml(app.app_id)}" ${isChecked ? "checked" : ""} onchange="toggleSelectApp('${escapeHtml(app.app_id)}', this.checked)">
      </td>
      <td style="font-weight: 600; color: var(--text-primary);">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 14px;">📊</span>
          <span>${escapeHtml(app.name)}</span>
        </div>
      </td>
      <td style="font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);">${escapeHtml(app.app_id)}</td>
      <td style="color: var(--text-secondary); font-size: 12px; font-weight: 500;">${escapeHtml(app.stream_or_space || "Personal")}</td>
      <td>${containerBadge}</td>
      <td>${waveBadge}</td>
      <td>${leadBadge}</td>
      <td style="font-weight: 600;">${app.sheet_count}</td>
      <td style="font-weight: 600;">${app.widget_count}</td>
      <td>${statusBadge}</td>
      <td>
        <button class="btn-secondary" style="padding: 6px 14px; font-size: 12px; font-weight: 600; color: var(--primary);" onclick="loadApp('${escapeHtml(app.app_id)}')">
          🔍 Select & Inspect →
        </button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function renderFleetHierarchyTree(hierarchy) {
  const root = document.getElementById("fleet-tree-root");
  if (!root) return;
  root.innerHTML = "";

  if (!hierarchy || hierarchy.length === 0) {
    root.innerHTML = `<div style="color: var(--text-muted); padding: 24px; text-align: center;">No Qlik environments configured. Configure an instance to explore the fleet hierarchy.</div>`;
    return;
  }

  let firstAppSelection = null;
  let activeAppSelection = null;

  hierarchy.forEach((inst, instIdx) => {
    const instNodeId = `node-inst-${instIdx}`;
    const isCloud = inst.environment_type === "cloud";
    const instIcon = isCloud ? "☁️" : "🏢";
    const envBadgeText = isCloud ? "Cloud SaaS" : "QSEoW On-Prem";
    const envBadgeBg = isCloud ? "#EFF6FF" : "#F8FAFC";
    const envBadgeColor = isCloud ? "#1D4ED8" : "#475569";

    const instEl = document.createElement("div");
    instEl.className = "tree-node";
    instEl.id = instNodeId;

    const instChildrenId = `children-inst-${instIdx}`;
    instEl.innerHTML = `
      <div class="tree-row" id="row-${instNodeId}" onclick="handleTreeNodeClick('${instNodeId}', 'instance', ${instIdx})">
        <span class="tree-expander" id="exp-${instNodeId}" onclick="toggleTreeExpander('${instChildrenId}', '${instNodeId}', event)">▼</span>
        <span class="node-icon">${instIcon}</span>
        <span class="node-title" style="font-weight: 600;">${escapeHtml(inst.name)}</span>
        <span class="node-badge" style="background: ${envBadgeBg}; color: ${envBadgeColor}; border: 1px solid var(--border-subtle);">${envBadgeText}</span>
        <span class="node-badge" style="background: var(--bg-subtle); color: var(--text-secondary);">${inst.total_apps} apps</span>
      </div>
      <div class="tree-children" id="${instChildrenId}"></div>
    `;
    root.appendChild(instEl);

    const instChildrenContainer = instEl.querySelector(`#${instChildrenId}`);

    // Container categories (Spaces vs Streams)
    (inst.containers || []).forEach((cat, catIdx) => {
      if (!cat || cat.app_count === 0) return;
      const catNodeId = `node-cat-${instIdx}-${catIdx}`;
      const catChildrenId = `children-cat-${instIdx}-${catIdx}`;

      let catIcon = "📁";
      if (cat.icon === "shield") catIcon = "🛡️";
      else if (cat.icon === "users") catIcon = "👥";
      else if (cat.icon === "user") catIcon = "👤";
      else if (cat.icon === "stream") catIcon = "📡";
      else if (cat.icon === "wrench") catIcon = "🔧";

      const catEl = document.createElement("div");
      catEl.className = "tree-node";
      catEl.id = catNodeId;
      catEl.innerHTML = `
        <div class="tree-row" id="row-${catNodeId}" onclick="handleTreeNodeClick('${catNodeId}', 'category', ${instIdx}, ${catIdx})">
          <span class="tree-expander" id="exp-${catNodeId}" onclick="toggleTreeExpander('${catChildrenId}', '${catNodeId}', event)">▼</span>
          <span class="node-icon">${catIcon}</span>
          <span class="node-title" style="font-weight: 500;">${escapeHtml(cat.label)}</span>
          <span class="node-badge" style="background: var(--bg-subtle); color: var(--text-muted);">${cat.app_count} apps</span>
        </div>
        <div class="tree-children" id="${catChildrenId}"></div>
      `;
      instChildrenContainer.appendChild(catEl);

      const catChildrenContainer = catEl.querySelector(`#${catChildrenId}`);

      // Spaces / Streams
      (cat.spaces || []).forEach((space, spaceIdx) => {
        const spaceNodeId = `node-space-${instIdx}-${catIdx}-${spaceIdx}`;
        const spaceChildrenId = `children-space-${instIdx}-${catIdx}-${spaceIdx}`;

        const spaceEl = document.createElement("div");
        spaceEl.className = "tree-node";
        spaceEl.id = spaceNodeId;
        spaceEl.innerHTML = `
          <div class="tree-row" id="row-${spaceNodeId}" onclick="handleTreeNodeClick('${spaceNodeId}', 'space', ${instIdx}, ${catIdx}, ${spaceIdx})">
            <span class="tree-expander" id="exp-${spaceNodeId}" onclick="toggleTreeExpander('${spaceChildrenId}', '${spaceNodeId}', event)">▼</span>
            <span class="node-icon">📂</span>
            <span class="node-title">${escapeHtml(space.name)}</span>
            <span class="node-badge" style="background: var(--bg-subtle); color: var(--text-secondary);">${space.app_count} ${space.app_count === 1 ? "app" : "apps"}</span>
          </div>
          <div class="tree-children" id="${spaceChildrenId}"></div>
        `;
        catChildrenContainer.appendChild(spaceEl);

        const spaceChildrenContainer = spaceEl.querySelector(`#${spaceChildrenId}`);

        // Leaf Apps
        (space.apps || []).forEach((app, appIdx) => {
          const appNodeId = `node-app-${instIdx}-${catIdx}-${spaceIdx}-${appIdx}`;

          if (!firstAppSelection) {
            firstAppSelection = { nodeId: appNodeId, instIdx, catIdx, spaceIdx, appIdx };
          }
          if (app.app_id === currentAppId) {
            activeAppSelection = { nodeId: appNodeId, instIdx, catIdx, spaceIdx, appIdx };
          }

          let statusBadge = `<span class="node-badge" style="background: #F1F5F9; color: #475569; font-size: 10px;">DISCOVERED</span>`;
          if (app.extraction_status === "IR_COMPILED") {
            statusBadge = `<span class="node-badge" style="background: #EEF2FF; color: #4F46E5; border: 1px solid #C7D2FE; font-size: 10px;">● IR COMPILED</span>`;
          } else if (app.extraction_status === "LOOKML_GENERATED") {
            statusBadge = `<span class="node-badge" style="background: #ECFDF5; color: #059669; border: 1px solid #A7F3D0; font-size: 10px;">✔ LOOKML READY</span>`;
          }

          const appEl = document.createElement("div");
          appEl.className = "tree-node";
          appEl.id = appNodeId;
          appEl.innerHTML = `
            <div class="tree-row app-row" id="row-${appNodeId}" data-app-id="${escapeHtml(app.app_id)}" onclick="handleTreeNodeClick('${appNodeId}', 'app', ${instIdx}, ${catIdx}, ${spaceIdx}, ${appIdx})">
              <span style="width: 16px; display: inline-flex; justify-content: center; color: var(--text-muted); font-size: 10px;">•</span>
              <span class="node-icon">📊</span>
              <span class="node-title" style="font-weight: 500;">${escapeHtml(app.name)}</span>
              ${statusBadge}
            </div>
          `;
          spaceChildrenContainer.appendChild(appEl);
        });
      });
    });
  });

  // Auto-select active app node if available, else first app
  const targetAppSelection = activeAppSelection || firstAppSelection;
  if (targetAppSelection) {
    handleTreeNodeClick(
      targetAppSelection.nodeId,
      "app",
      targetAppSelection.instIdx,
      targetAppSelection.catIdx,
      targetAppSelection.spaceIdx,
      targetAppSelection.appIdx
    );
  }
}

function toggleTreeExpander(childrenId, nodeId, event) {
  if (event) event.stopPropagation();
  const childrenEl = document.getElementById(childrenId);
  const expEl = document.getElementById(`exp-${nodeId}`);
  if (!childrenEl) return;

  const isHidden = childrenEl.style.display === "none";
  childrenEl.style.display = isHidden ? "block" : "none";
  if (expEl) {
    if (isHidden) {
      expEl.classList.remove("collapsed");
      expEl.textContent = "▼";
    } else {
      expEl.classList.add("collapsed");
      expEl.textContent = "▶";
    }
  }
}

function handleTreeNodeClick(nodeId, type, instIdx, catIdx, spaceIdx, appIdx) {
  document.querySelectorAll(".tree-row.selected").forEach(r => r.classList.remove("selected"));
  const rowEl = document.getElementById(`row-${nodeId}`);
  if (rowEl) rowEl.classList.add("selected");
  selectedTreeNodeId = nodeId;

  const inst = currentFleetHierarchy[instIdx];
  if (!inst) return;

  if (type === "instance") {
    renderTreeInspector("instance", inst, { inst });
  } else if (type === "category") {
    const cat = (inst.containers || [])[catIdx];
    renderTreeInspector("category", cat, { inst, cat });
  } else if (type === "space") {
    const cat = (inst.containers || [])[catIdx];
    const space = cat && cat.spaces ? cat.spaces[spaceIdx] : null;
    renderTreeInspector("space", space, { inst, cat, space });
  } else if (type === "app") {
    const cat = (inst.containers || [])[catIdx];
    const space = cat && cat.spaces ? cat.spaces[spaceIdx] : null;
    const app = space && space.apps ? space.apps[appIdx] : null;
    renderTreeInspector("app", app, { inst, cat, space, app });
  }
}

function renderTreeInspector(type, data, context) {
  const panel = document.getElementById("tree-inspector-panel");
  if (!panel || !data) return;

  if (type === "app") {
    const app = data;
    const inst = context.inst;
    const cat = context.cat;
    const space = context.space;

    const isCloud = inst.environment_type === "cloud";
    const envLabel = isCloud ? "Qlik Cloud SaaS" : "Customer-Hosted QSEoW";
    const envIcon = isCloud ? "☁️" : "🏢";

    let containerExplanation = "";
    const st = (app.space_type || "managed").toLowerCase();
    if (st === "managed") {
      containerExplanation = "Managed Space: Governed enterprise production workspace where published apps are accessible to consumers. Sheet edits and script changes are locked.";
    } else if (st === "shared") {
      containerExplanation = "Shared Space: Collaborative co-development workspace where members can develop sheets and data models together.";
    } else if (st === "personal") {
      containerExplanation = "Personal Space: Private developer sandbox. Content here is only visible to the owner before publication to a Managed or Shared space.";
    } else if (st === "stream") {
      containerExplanation = "Published Stream: Security boundary in Qlik Sense Enterprise on Windows (QSEoW), governed by Hub security rules.";
    } else if (st === "work") {
      containerExplanation = "Work Area: Unpublished developer sheet area in QSEoW. The developer sandbox prior to publishing to a Stream.";
    }

    let statusBadge = `<span class="badge" style="background: #F1F5F9; color: #475569;">DISCOVERED</span>`;
    if (app.extraction_status === "IR_COMPILED") {
      statusBadge = `<span class="badge" style="background: #EEF2FF; color: #4F46E5; border: 1px solid #C7D2FE;">● IR COMPILED</span>`;
    } else if (app.extraction_status === "LOOKML_GENERATED") {
      statusBadge = `<span class="badge" style="background: #ECFDF5; color: #059669; border: 1px solid #A7F3D0;">✔ LOOKML READY</span>`;
    }

    panel.innerHTML = `
      <div style="padding: 20px;">
        <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px;">
          <div>
            <div style="font-size: 11px; font-weight: 600; color: var(--primary); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;">
              Application Context
            </div>
            <h3 style="font-size: 18px; font-weight: 700; color: var(--text-primary); margin: 0; line-height: 1.3;">
              ${escapeHtml(app.name)}
            </h3>
          </div>
          ${statusBadge}
        </div>

        <div style="padding: 8px 12px; background: var(--bg-subtle); border: 1px solid var(--border-subtle); border-radius: 6px; font-size: 11px; color: var(--text-secondary); margin-bottom: 16px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
          <span>${envIcon} ${escapeHtml(inst.name)}</span>
          <span style="color: var(--text-muted);">›</span>
          <span>${escapeHtml((cat.label || "").split("(")[0].trim())}</span>
          <span style="color: var(--text-muted);">›</span>
          <strong style="color: var(--text-primary);">${escapeHtml(space ? space.name : (app.stream_or_space || ""))}</strong>
        </div>

        <div style="padding: 10px 14px; background: #F8FAFC; border-left: 3px solid var(--primary); border-radius: 0 6px 6px 0; font-size: 12px; color: var(--text-secondary); margin-bottom: 16px; line-height: 1.4;">
          ${escapeHtml(containerExplanation)}
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 20px;">
          <div style="padding: 10px; background: var(--bg-subtle); border-radius: 6px;">
            <span style="font-size: 11px; color: var(--text-muted); display: block;">App ID</span>
            <span style="font-family: var(--font-mono); font-size: 12px; font-weight: 600; color: var(--text-primary); word-break: break-all;">${escapeHtml(app.app_id)}</span>
          </div>
          <div style="padding: 10px; background: var(--bg-subtle); border-radius: 6px;">
            <span style="font-size: 11px; color: var(--text-muted); display: block;">Environment</span>
            <span style="font-size: 12px; font-weight: 600; color: var(--text-primary);">${envLabel}</span>
          </div>
          <div style="padding: 10px; background: var(--bg-subtle); border-radius: 6px;">
            <span style="font-size: 11px; color: var(--text-muted); display: block;">Sheets / Dashboards</span>
            <span style="font-size: 14px; font-weight: 700; color: var(--text-primary);">${app.sheet_count} Sheets</span>
          </div>
          <div style="padding: 10px; background: var(--bg-subtle); border-radius: 6px;">
            <span style="font-size: 11px; color: var(--text-muted); display: block;">Visual Objects</span>
            <span style="font-size: 14px; font-weight: 700; color: var(--text-primary);">${app.widget_count} Widgets</span>
          </div>
        </div>

        <div style="padding: 16px; background: #EEF2FF; border: 1px solid #C7D2FE; border-radius: 8px;">
          <div style="font-weight: 600; font-size: 13px; color: #312E81; margin-bottom: 4px;">
            Step 1: Select & Inspect in Stage 1
          </div>
          <div style="font-size: 12px; color: #4338CA; margin-bottom: 14px; line-height: 1.4;">
            Extract data model, inspect sanitized fields, audit compatibility taxonomy, and compile the Canonical IR.
          </div>
          <button class="btn-primary" style="width: 100%; padding: 10px 16px; font-weight: 600; font-size: 13px; display: flex; align-items: center; justify-content: center; gap: 8px;" onclick="loadApp('${escapeHtml(app.app_id)}')">
            🔍 Select & Inspect in Stage 1 →
          </button>
        </div>
      </div>
    `;
  } else if (type === "space") {
    const space = data;
    const inst = context.inst;
    const cat = context.cat;
    panel.innerHTML = `
      <div style="padding: 20px;">
        <div style="font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;">
          Container Scope
        </div>
        <h3 style="font-size: 18px; font-weight: 700; color: var(--text-primary); margin: 0 0 12px 0;">
          📁 ${escapeHtml(space.name)}
        </h3>
        <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 16px;">
          Belongs to: <strong>${escapeHtml(inst.name)}</strong> · ${escapeHtml(cat.label)}
        </div>
        <div style="padding: 12px; background: var(--bg-subtle); border-radius: 8px; margin-bottom: 16px;">
          <div style="display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 6px;">
            <span>Total Applications</span>
            <strong style="color: var(--text-primary);">${space.app_count}</strong>
          </div>
          <div style="display: flex; justify-content: space-between; font-size: 12px;">
            <span>Stage 1 IR Compiled</span>
            <strong style="color: var(--primary);">${space.compiled_count || 0} / ${space.app_count}</strong>
          </div>
        </div>
        <div style="font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-bottom: 8px;">
          Applications in this Container:
        </div>
        <div style="display: flex; flex-direction: column; gap: 6px;">
          ${(space.apps || []).map(a => `
            <div style="display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; background: var(--bg-card); border: 1px solid var(--border-subtle); border-radius: 6px; cursor: pointer;" onclick="loadApp('${escapeHtml(a.app_id)}')">
              <div>
                <div style="font-size: 12px; font-weight: 600; color: var(--text-primary);">📊 ${escapeHtml(a.name)}</div>
                <div style="font-size: 11px; color: var(--text-muted); font-family: var(--font-mono);">${escapeHtml(a.app_id)}</div>
              </div>
              <button class="btn-secondary" style="padding: 4px 10px; font-size: 11px;">Inspect →</button>
            </div>
          `).join("")}
        </div>
      </div>
    `;
  } else if (type === "instance") {
    const inst = data;
    const isCloud = inst.environment_type === "cloud";
    panel.innerHTML = `
      <div style="padding: 20px;">
        <div style="font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;">
          Qlik Deployment Environment
        </div>
        <h3 style="font-size: 18px; font-weight: 700; color: var(--text-primary); margin: 0 0 12px 0;">
          ${isCloud ? "☁️" : "🏢"} ${escapeHtml(inst.name)}
        </h3>
        <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 16px;">
          Type: <strong>${isCloud ? "Qlik Cloud SaaS" : "Customer-Hosted QSEoW"}</strong> · Host: <code>${escapeHtml(inst.qlik_host)}</code>
        </div>
        <div style="padding: 12px; background: var(--bg-subtle); border-radius: 8px; margin-bottom: 16px;">
          <div style="display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 6px;">
            <span>Discovered Apps</span>
            <strong style="color: var(--text-primary);">${inst.total_apps}</strong>
          </div>
          <div style="display: flex; justify-content: space-between; font-size: 12px;">
            <span>Stage 1 IR Compiled</span>
            <strong style="color: var(--primary);">${inst.compiled_apps || 0} / ${inst.total_apps}</strong>
          </div>
        </div>
        <div style="font-size: 12px; color: var(--text-muted); line-height: 1.5;">
          ${isCloud 
            ? "Qlik Cloud organizes apps into Spaces (Managed for published production, Shared for collaborative development, and Personal for private drafts)."
            : "Customer-Hosted QSEoW organizes apps into Published Streams (secured by Hub access rules) and developer Work Areas (unpublished personal authoring)."}
        </div>
      </div>
    `;
  } else if (type === "category") {
    const cat = data;
    const inst = context.inst;
    panel.innerHTML = `
      <div style="padding: 20px;">
        <div style="font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;">
          Container Tier
        </div>
        <h3 style="font-size: 18px; font-weight: 700; color: var(--text-primary); margin: 0 0 12px 0;">
          ${escapeHtml(cat.label)}
        </h3>
        <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 16px;">
          Environment: <strong>${escapeHtml(inst.name)}</strong>
        </div>
        <div style="padding: 12px; background: var(--bg-subtle); border-radius: 8px; margin-bottom: 16px;">
          <div style="display: flex; justify-content: space-between; font-size: 12px;">
            <span>Total Contained Apps</span>
            <strong style="color: var(--text-primary);">${cat.app_count}</strong>
          </div>
        </div>
      </div>
    `;
  }
}

let currentActiveSheetIndex = 0;
let currentSheetSearchQuery = "";
let currentStudioView = "sheet"; // 'sheet' | 'datamodel' | 'audit'
let currentAppId = null;
let isExtractingStage1 = false;

async function loadApp(appId) {
  currentAppId = appId;
  currentActiveSheetIndex = 0;
  currentStudioView = "sheet";
  switchTab("tab-canvas");
}

function resetStudioEmptyState() {
  currentCanonicalIR = null;
  currentFindings = [];

  const studioAppName = document.getElementById("studio-app-name");
  const studioAppId = document.getElementById("studio-app-id");
  const studioInstanceBadge = document.getElementById("studio-instance-badge");
  const studioIrStatus = document.getElementById("studio-ir-status");

  if (studioAppName) studioAppName.textContent = "None";
  if (studioAppId) studioAppId.textContent = "—";
  if (studioInstanceBadge) {
    studioInstanceBadge.textContent = (activeInstance && activeInstance.name) || "No Qlik Connected";
    studioInstanceBadge.style.background = "var(--bg-subtle)";
    studioInstanceBadge.style.color = "var(--text-muted)";
  }
  if (studioIrStatus) {
    studioIrStatus.textContent = "No App Selected";
    studioIrStatus.style.background = "var(--bg-subtle)";
    studioIrStatus.style.color = "var(--text-muted)";
    studioIrStatus.style.borderColor = "var(--border-subtle)";
  }

  const navTables = document.getElementById("nav-tables-count");
  const navJoins = document.getElementById("nav-joins-count");
  const navFindings = document.getElementById("nav-findings-count");
  const sheetCountBadge = document.getElementById("sheet-count-badge");
  const sheetList = document.getElementById("sheet-list-container");

  if (navTables) navTables.textContent = "0 Tables";
  if (navJoins) navJoins.textContent = "0 Relationships";
  if (navFindings) navFindings.textContent = "0 Rules";
  if (sheetCountBadge) sheetCountBadge.textContent = "0 Sheets";
  if (sheetList) sheetList.innerHTML = "";

  const activeSheetTitle = document.getElementById("active-sheet-title");
  const activeSheetIdBadge = document.getElementById("active-sheet-id-badge");
  const activeSheetTargetFile = document.getElementById("active-sheet-target-file");
  const activeSheetCatSummary = document.getElementById("active-sheet-cat-summary");

  if (activeSheetTitle) activeSheetTitle.textContent = "Select an Application";
  if (activeSheetIdBadge) activeSheetIdBadge.textContent = "—";
  if (activeSheetTargetFile) activeSheetTargetFile.textContent = "Select an application from the Fleet Catalog to inspect its data model and sheets.";
  if (activeSheetCatSummary) activeSheetCatSummary.innerHTML = "";

  const canvasGrid = document.getElementById("canvas-grid");
  if (canvasGrid) {
    canvasGrid.innerHTML = `
      <div style="grid-column: 1 / -1; padding: 60px 20px; text-align: center; color: var(--text-muted);">
        <div style="font-size: 36px; margin-bottom: 12px;">📊</div>
        <div style="font-size: 15px; font-weight: 600; color: var(--text-primary); margin-bottom: 6px;">No Application Selected</div>
        <div style="font-size: 13px; max-width: 480px; margin: 0 auto 16px auto;">Select an application from the Fleet Catalog or connect a Qlik instance to inspect its data model and dashboards.</div>
        <button class="btn-primary" onclick="switchTab('tab-catalog')">Go to Fleet Catalog →</button>
      </div>
    `;
  }

  const appIdEl = document.getElementById("ir-card-app-id");
  const tablesEl = document.getElementById("ir-card-tables-count");
  const sheetsEl = document.getElementById("ir-card-sheets-count");
  if (appIdEl) appIdEl.textContent = "—";
  if (tablesEl) tablesEl.textContent = "0 Tables · 0 Relationships";
  if (sheetsEl) sheetsEl.textContent = "0 Sheets · 0 Widgets";
}

function reExtractCurrentApp() {
  if (!currentAppId) {
    showToast("No application currently selected to re-extract.", "warning");
    return;
  }
  runStage1(true, currentAppId);
}

async function runStage1(showLoader = true, targetAppId = null) {
  if (isExtractingStage1) return;
  
  const appId = targetAppId || currentAppId || (allWaveApps.length > 0 ? allWaveApps[0].app_id : null);
  if (!appId) {
    resetStudioEmptyState();
    if (showLoader) {
      showToast("Please select an application from the Fleet Catalog to inspect first.", "info");
    }
    return;
  }
  
  isExtractingStage1 = true;
  currentAppId = appId;

  if (showLoader) {
    showLoading("Extracting Qlik Architecture...", "Sanitizing PII and compiling Canonical 2-Tier Intermediate Representation");
  }

  try {
    const res = await fetch("/api/stage1/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app_id: appId, use_sample: false }),
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || `HTTP ${res.status}: Failed to extract app architecture`);
    }
    const data = await res.json();
    if (!data.canonical_ir) {
      throw new Error(data.error || "No Canonical IR returned from server.");
    }
    currentCanonicalIR = data.canonical_ir;
    currentFindings = (data.compatibility && data.compatibility.findings) || [];

    const tablesCount = currentCanonicalIR.data_layer?.tables?.length || 0;
    const relationshipsCount = currentCanonicalIR.data_layer?.relationships?.length || 0;
    const sheets = currentCanonicalIR.visual_catalog?.sheets || [];
    const sheetsCount = sheets.length;
    const totalWidgets = sheets.reduce((acc, s) => acc + (s.widgets?.length || 0), 0);

    // Update Top App Context Strip
    const studioAppName = document.getElementById("studio-app-name");
    const studioAppId = document.getElementById("studio-app-id");
    const studioInstanceBadge = document.getElementById("studio-instance-badge");
    const studioIrStatus = document.getElementById("studio-ir-status");

    if (studioAppName) studioAppName.textContent = currentCanonicalIR.app_metadata?.app_name || appId;
    if (studioAppId) studioAppId.textContent = appId;
    const isUnpublished = currentCanonicalIR.app_metadata?.publication_status === "unpublished" || currentCanonicalIR.app_metadata?.space_type === "personal" || currentCanonicalIR.app_metadata?.stream_or_space === "Personal";
    if (studioInstanceBadge) {
      const instName = (activeInstance && activeInstance.name) || "Qlik Cloud SaaS (Trial Tenant)";
      studioInstanceBadge.textContent = isUnpublished ? `${instName} · Personal Space (Unpublished)` : instName;
      studioInstanceBadge.style.background = "#EEF2FF";
      studioInstanceBadge.style.color = "var(--primary)";
    }
    if (studioIrStatus) {
      studioIrStatus.textContent = isUnpublished ? `● Canonical IR Compiled (${sheetsCount} Unpublished Sheets)` : "● Canonical IR Compiled";
      studioIrStatus.style.background = "#ECFDF5";
      studioIrStatus.style.color = "#059669";
      studioIrStatus.style.borderColor = "#A7F3D0";
    }

    // Update Left Navigation Architecture Counts
    const navTables = document.getElementById("nav-tables-count");
    const navJoins = document.getElementById("nav-joins-count");
    const navFindings = document.getElementById("nav-findings-count");
    const sheetCountBadge = document.getElementById("sheet-count-badge");

    if (navTables) navTables.textContent = `${tablesCount} Tables`;
    if (navJoins) navJoins.textContent = `${relationshipsCount} Relationships · Star Schema`;
    if (navFindings) navFindings.textContent = `${currentFindings.length} Rules`;
    if (sheetCountBadge) sheetCountBadge.textContent = `${sheetsCount} Sheets`;

    // Update Stage 1 Canonical IR Handoff Milestone Card at Footer
    const appIdEl = document.getElementById("ir-card-app-id");
    const tablesEl = document.getElementById("ir-card-tables-count");
    const sheetsEl = document.getElementById("ir-card-sheets-count");

    if (appIdEl) appIdEl.textContent = appId;
    if (tablesEl) tablesEl.textContent = `${tablesCount} Tables · ${relationshipsCount} Relationships`;
    if (sheetsEl) sheetsEl.textContent = `${sheetsCount} Sheet${sheetsCount === 1 ? "" : "s"} · ${totalWidgets} Widgets`;

    const hasSheets = Boolean(currentCanonicalIR?.visual_catalog?.sheets?.length);
    switchStudioView(currentStudioView || (hasSheets ? "sheet" : "datamodel"));
    loadCatalog();
  } catch (err) {
    console.error("Stage 1 extraction failed:", err);
    showToast(`Stage 1 extraction failed: ${err.message}`, "error");
    const studioAppName = document.getElementById("studio-app-name");
    const studioAppId = document.getElementById("studio-app-id");
    const studioIrStatus = document.getElementById("studio-ir-status");
    if (studioAppName) studioAppName.textContent = `Extraction Error (${appId})`;
    if (studioAppId) studioAppId.textContent = appId;
    if (studioIrStatus) studioIrStatus.textContent = "❌ Extraction Failed";
  } finally {
    isExtractingStage1 = false;
    if (showLoader) {
      setTimeout(hideLoading, 400);
    }
  }
}
function animateValue(id, start, end, duration) {
  const el = document.getElementById(id);
  if (!el) return;
  let startTimestamp = null;
  const step = (timestamp) => {
    if (!startTimestamp) startTimestamp = timestamp;
    const progress = Math.min((timestamp - startTimestamp) / duration, 1);
    el.textContent = Math.floor(progress * (end - start) + start);
    if (progress < 1) {
      window.requestAnimationFrame(step);
    } else {
      el.textContent = end;
    }
  };
  window.requestAnimationFrame(step);
}

function filterSheetList(query) {
  currentSheetSearchQuery = (query || "").toLowerCase().trim();
  renderSheetList();
}

function selectCanvasSheet(index) {
  currentActiveSheetIndex = index;
  switchStudioView("sheet");
}

function switchStudioView(viewType) {
  currentStudioView = viewType;

  // 1. Toggle visibility of right-hand view containers
  const sheetContainer = document.getElementById("view-sheet-container");
  const dmContainer = document.getElementById("view-datamodel-container");
  const auditContainer = document.getElementById("view-audit-container");

  if (sheetContainer) sheetContainer.style.display = viewType === "sheet" ? "block" : "none";
  if (dmContainer) dmContainer.style.display = viewType === "datamodel" ? "block" : "none";
  if (auditContainer) auditContainer.style.display = viewType === "audit" ? "block" : "none";

  // 2. Toggle active selection highlight on left nav items
  const navDm = document.getElementById("nav-item-datamodel");
  const navAudit = document.getElementById("nav-item-audit");
  if (navDm) navDm.classList.toggle("selected", viewType === "datamodel");
  if (navAudit) navAudit.classList.toggle("selected", viewType === "audit");

  const sheetItems = document.querySelectorAll("#sheet-list-container .sheet-item");
  sheetItems.forEach((item, idx) => {
    if (viewType === "sheet") {
      item.classList.toggle("selected", idx === currentActiveSheetIndex);
    } else {
      item.classList.remove("selected");
    }
  });

  // 3. Render content for the active view
  if (viewType === "datamodel") {
    renderDataModelView();
  } else if (viewType === "audit") {
    renderFindings("all");
  } else {
    renderCanvas(currentActiveSheetIndex);
  }
}

function renderDataModelView() {
  if (!currentCanonicalIR || !currentCanonicalIR.data_layer) return;

  const tables = currentCanonicalIR.data_layer.tables || [];
  const relationships = currentCanonicalIR.data_layer.relationships || [];
  const totalFields = tables.reduce((acc, t) => acc + (t.fields?.length || 0), 0);

  // Update KPI counters
  const statTables = document.getElementById("dm-stat-tables");
  const statJoins = document.getElementById("dm-stat-joins");
  const statFields = document.getElementById("dm-stat-fields");
  const statPii = document.getElementById("dm-stat-pii");

  if (statTables) statTables.textContent = tables.length;
  if (statJoins) statJoins.textContent = relationships.length;
  if (statFields) statFields.textContent = totalFields;
  const sensitiveNames = ["ssn", "socialsecurity", "creditcard", "cardnumber", "cvv", "cvc", "pin", "password", "secret", "privatekey", "taxid", "nationalid"];
  let piiCount = 0;
  tables.forEach(t => {
    (t.fields || []).forEach(f => {
      const fn = (typeof f === "string" ? f : f.name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
      if (sensitiveNames.some(s => fn.includes(s))) {
        piiCount++;
      }
    });
  });
  if (statPii) statPii.textContent = `${piiCount} Field${piiCount === 1 ? "" : "s"} (Sanitized)`;

  // Render Tables Grid
  const tablesGrid = document.getElementById("datamodel-tables-grid");
  if (tablesGrid) {
    tablesGrid.innerHTML = "";
    tables.forEach(table => {
      const card = document.createElement("div");
      card.className = "dm-table-card";
      const isFact = table.is_fact || (table.name && (table.name.toLowerCase().includes("sales") || table.name.toLowerCase().includes("detail") || table.name.toLowerCase().includes("fact")));
      const fields = table.fields || [];

      card.innerHTML = `
        <div class="dm-table-header">
          <div>
            <span style="font-weight: 700; font-size: 13px; color: var(--text-primary); font-family: var(--font-mono);">${escapeHtml(table.name)}</span>
            <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">${(table.row_count || 0).toLocaleString()} rows</div>
          </div>
          <span class="badge ${isFact ? "badge-cat1" : "badge-cat2"}" style="font-size: 10px;">
            ${isFact ? "Fact Table" : "Dimension Table"}
          </span>
        </div>
        <div class="dm-field-list">
          ${fields.map(f => `
            <div class="dm-field-row">
              <span style="display: flex; align-items: center; gap: 4px;">
                ${f.is_primary_key ? "🔑" : "▪"} <span>${escapeHtml(f.name)}</span>
              </span>
              <span style="color: var(--text-muted); font-size: 10px;">${escapeHtml(f.data_type || "string")}</span>
            </div>
          `).join("")}
        </div>
      `;
      tablesGrid.appendChild(card);
    });
  }

  // Render Joins List
  const joinsList = document.getElementById("datamodel-joins-list");
  if (joinsList) {
    joinsList.innerHTML = "";
    if (relationships.length === 0) {
      joinsList.innerHTML = `<div style="color: var(--text-muted); font-size: 12px; padding: 12px;">No relationships defined.</div>`;
    } else {
      relationships.forEach(rel => {
        const row = document.createElement("div");
        row.className = "dm-join-row";
        row.innerHTML = `
          <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
            <span class="badge" style="background: #EEF2FF; color: var(--primary); font-family: var(--font-mono); font-size: 11px;">
              ${escapeHtml(rel.from_table)}
            </span>
            <span style="color: var(--text-muted); font-weight: 600;">.${escapeHtml(rel.from_field)}</span>
            <span style="color: var(--text-muted); font-size: 14px;">⇄</span>
            <span class="badge" style="background: var(--bg-subtle); font-family: var(--font-mono); font-size: 11px;">
              ${escapeHtml(rel.to_table)}
            </span>
            <span style="color: var(--text-muted); font-weight: 600;">.${escapeHtml(rel.to_field)}</span>
          </div>
          <div style="display: flex; align-items: center; gap: 12px;">
            <span class="badge" style="background: #F3F4F6; color: var(--text-secondary); font-size: 10px;">
              ${escapeHtml(rel.join_type || "left_outer")}
            </span>
            <code style="font-size: 11px; color: var(--primary);">relationship: ${escapeHtml(rel.relationship || "many_to_one")}</code>
          </div>
        `;
        joinsList.appendChild(row);
      });
    }
  }
}

function getWidgetCategory(w) {
  if (w.source_type === "filterpane" || (w.type || "").includes("filter")) {
    return { cat: 3, badgeClass: "badge-cat3", badgeText: "Cat 3 · Deprecated", miniClass: "cat3" };
  }
  const title = (w.title || "").toLowerCase();
  if (title.includes("retention") || title.includes("vip") || title.includes("churn") || title.includes("risk") || title.includes("set") || title.includes("variance")) {
    return { cat: 2, badgeClass: "badge-cat2", badgeText: "Cat 2 · Refactor", miniClass: "cat2" };
  }
  return { cat: 1, badgeClass: "badge-cat1", badgeText: "Cat 1 · Native", miniClass: "cat1" };
}

function renderSheetList() {
  const container = document.getElementById("sheet-list-container");
  const countBadge = document.getElementById("sheet-count-badge");
  if (!container) return;
  container.innerHTML = "";

  if (!currentCanonicalIR || !currentCanonicalIR.visual_catalog || !currentCanonicalIR.visual_catalog.sheets || !currentCanonicalIR.visual_catalog.sheets.length) {
    container.innerHTML = `<div style="color: var(--text-muted); font-size: 12px; padding: 16px; text-align: center;">No sheets found in inspected application.</div>`;
    if (countBadge) countBadge.textContent = "0 Sheets";
    return;
  }

  const sheets = currentCanonicalIR.visual_catalog.sheets;
  if (countBadge) countBadge.textContent = `${sheets.length} ${sheets.length === 1 ? "Sheet" : "Sheets"}`;

  // Check if app has mixed sheet scopes (Public approved sheets vs My Own unpublished sheets)
  const hasPublic = sheets.some(s => s.section === "Public" || s.sheet_lifecycle === "approved" || s.is_approved);
  const hasMyOwn = sheets.some(s => s.section === "My own" || s.sheet_lifecycle === "my_own" || (!s.is_approved && s.section !== "Public"));

  let lastSection = null;
  sheets.forEach((sheet, idx) => {
    const title = sheet.title || `Sheet ${idx + 1}`;
    if (currentSheetSearchQuery && !title.toLowerCase().includes(currentSheetSearchQuery) && !sheet.sheet_id.toLowerCase().includes(currentSheetSearchQuery)) {
      return;
    }

    const section = sheet.section || (sheet.sheet_lifecycle === "approved" || sheet.is_approved ? "Public" : "My own");
    if (hasPublic && hasMyOwn && section !== lastSection) {
      lastSection = section;
      const secHeader = document.createElement("div");
      secHeader.style.cssText = "font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); padding: 12px 8px 4px 8px; display: flex; align-items: center; justify-content: space-between;";
      const secCount = sheets.filter(s => (s.section || (s.sheet_lifecycle === "approved" || s.is_approved ? "Public" : "My own")) === section).length;
      secHeader.innerHTML = `<span>${section === "Public" ? "🌐 Public" : "👤 My own"}</span><span style="font-size: 10px; background: var(--bg-hover); padding: 2px 6px; border-radius: 10px; font-weight: 600;">${secCount}</span>`;
      container.appendChild(secHeader);
    }

    const widgets = sheet.widgets || [];
    let c1 = 0, c2 = 0, c3 = 0;
    widgets.forEach(w => {
      const catInfo = getWidgetCategory(w);
      if (catInfo.cat === 1) c1++;
      else if (catInfo.cat === 2) c2++;
      else c3++;
    });

    const isSelected = currentStudioView === "sheet" && idx === currentActiveSheetIndex;
    const isUnpublished = section === "My own" || sheet.sheet_lifecycle === "my_own" || currentCanonicalIR.app_metadata?.publication_status === "unpublished";
    const item = document.createElement("div");
    item.className = `sheet-item ${isSelected ? "selected" : ""}`;
    item.onclick = () => selectCanvasSheet(idx);

    item.innerHTML = `
      <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 8px;">
        <span class="sheet-item-title">${escapeHtml(title)}</span>
        <span style="font-size: 11px; color: ${isSelected ? "var(--primary)" : "var(--text-muted)"}; font-weight: 500;">${widgets.length} ${widgets.length === 1 ? "tile" : "tiles"}</span>
      </div>
      <div class="sheet-item-meta">
        <span style="font-family: var(--font-mono); font-size: 10px; color: var(--text-muted);">${escapeHtml(sheet.sheet_id)}</span>
        <div class="sheet-mini-badges">
          ${isUnpublished ? `<span class="mini-pill" style="background: #FDF4FF; color: #A21CAF; border-color: #F5D0FE;" title="Unpublished sheet in personal workspace ('My own')">👤 My own</span>` : `<span class="mini-pill" style="background: #F0FDF4; color: #166534; border-color: #BBF7D0;" title="Approved public sheet">🌐 Public</span>`}
          ${c1 > 0 ? `<span class="mini-pill cat1" title="${c1} Native Mapped (Cat 1)">● ${c1}</span>` : ""}
          ${c2 > 0 ? `<span class="mini-pill cat2" title="${c2} Upstream Refactor (Cat 2)">● ${c2}</span>` : ""}
          ${c3 > 0 ? `<span class="mini-pill cat3" title="${c3} Target Deprecated (Cat 3)">● ${c3}</span>` : ""}
        </div>
      </div>
    `;
    container.appendChild(item);
  });
}

function renderCanvas(sheetIndex = 0) {
  if (sheetIndex !== undefined && sheetIndex !== null) {
    currentActiveSheetIndex = sheetIndex;
  }

  // 1. Populate/Update the Left Navigation Sheet List
  renderSheetList();

  const grid = document.getElementById("canvas-grid");
  if (!grid) return;
  grid.innerHTML = "";

  if (!currentCanonicalIR || !currentCanonicalIR.visual_catalog || !currentCanonicalIR.visual_catalog.sheets || !currentCanonicalIR.visual_catalog.sheets.length) {
    const dmTables = currentCanonicalIR?.data_layer?.tables || [];
    const tCount = dmTables.length;
    grid.innerHTML = `
      <div style="grid-column: 1 / span 12; padding: 48px 24px; text-align: center; background: var(--bg-card); border: 1px solid var(--border-subtle); border-radius: 12px; margin-top: 12px;">
        <div style="font-size: 40px; margin-bottom: 12px;">🗄️</div>
        <div style="font-weight: 700; font-size: 16px; color: var(--text-primary);">Data Model Extracted &amp; Compiled (${tCount} Tables)</div>
        <div style="font-size: 13px; color: var(--text-secondary); margin-top: 8px; max-width: 540px; margin-left: auto; margin-right: auto; line-height: 1.5;">
          This Qlik application currently has no published visual dashboard sheets. Its data model (<strong>${tCount} tables</strong>) has been fully compiled into the Canonical Intermediate Representation (IR) and is ready for exploration and LookML generation.
        </div>
        <div style="margin-top: 24px; display: flex; gap: 12px; justify-content: center; flex-wrap: wrap;">
          <button type="button" class="btn-primary" onclick="switchStudioView('datamodel')">🔍 Inspect Data Model (${tCount} Tables)</button>
          <button type="button" class="btn-secondary" onclick="switchStudioView('audit')">📋 View Compatibility Audit</button>
          <button type="button" class="btn-primary" style="background: var(--accent-success); border-color: var(--accent-success);" onclick="switchTab('tab-lookml')">🚀 Proceed to Stage 2: Generate LookML →</button>
        </div>
      </div>
    `;
    const titleEl = document.getElementById("active-sheet-title");
    const idBadgeEl = document.getElementById("active-sheet-id-badge");
    const targetFileEl = document.getElementById("active-sheet-target-file");
    const catSummaryEl = document.getElementById("active-sheet-cat-summary");
    if (titleEl) titleEl.textContent = "Data Model Only (0 Dashboard Sheets)";
    if (idBadgeEl) idBadgeEl.textContent = `${tCount} Tables`;
    if (targetFileEl) targetFileEl.textContent = "Application contains data tables and schema without visual dashboard sheets.";
    if (catSummaryEl) catSummaryEl.innerHTML = "";
    return;
  }

  const sheets = currentCanonicalIR.visual_catalog.sheets;
  if (currentActiveSheetIndex >= sheets.length) {
    currentActiveSheetIndex = 0;
  }
  const sheet = sheets[currentActiveSheetIndex];
  const widgets = sheet.widgets || [];

  // 2. Update Active Sheet Header Strip
  const titleEl = document.getElementById("active-sheet-title");
  const idBadgeEl = document.getElementById("active-sheet-id-badge");
  const targetFileEl = document.getElementById("active-sheet-target-file");
  const catSummaryEl = document.getElementById("active-sheet-cat-summary");

  if (titleEl) titleEl.textContent = sheet.title || `Sheet ${currentActiveSheetIndex + 1}`;
  if (idBadgeEl) {
    const isUnpublished = sheet.sheet_lifecycle === "my_own" || currentCanonicalIR.app_metadata?.publication_status === "unpublished";
    idBadgeEl.innerHTML = `${escapeHtml(sheet.sheet_id)} ${isUnpublished ? '<span class="badge" style="background: #FDF4FF; color: #A21CAF; border: 1px solid #F5D0FE; font-size: 10px; margin-left: 6px;">👤 My Own (Unpublished)</span>' : ''}`;
  }
  if (targetFileEl) {
    targetFileEl.innerHTML = `Target File: <code>dashboards/${escapeHtml(sheet.sheet_id)}.dashboard.lookml</code> · Explores: <code>order_details</code>, <code>customers</code>`;
  }

  let cat1Count = 0, cat2Count = 0, cat3Count = 0;
  widgets.forEach(w => {
    const cat = getWidgetCategory(w).cat;
    if (cat === 1) cat1Count++;
    else if (cat === 2) cat2Count++;
    else cat3Count++;
  });

  if (catSummaryEl) {
    catSummaryEl.innerHTML = `
      <span class="badge badge-cat1" title="Native Mapped">${cat1Count} Cat 1</span>
      <span class="badge badge-cat2" title="Upstream Refactor">${cat2Count} Cat 2</span>
      <span class="badge badge-cat3" title="Target Deprecated">${cat3Count} Cat 3</span>
    `;
  }

  // 3. Render 24-Column Normalized Looker Tiles for Selected Sheet
  if (widgets.length === 0) {
    grid.innerHTML = `<div style="grid-column: 1 / -1; color: var(--text-muted); padding: 48px; text-align: center;">This sheet contains no visual objects.</div>`;
    return;
  }

  // Sort widgets by row then col for deterministic and natural DOM flow
  const sortedWidgets = [...widgets].sort((a, b) => {
    const aRow = a.layout?.looker_row ?? 0;
    const bRow = b.layout?.looker_row ?? 0;
    if (aRow !== bRow) return aRow - bRow;
    const aCol = a.layout?.looker_col ?? 0;
    const bCol = b.layout?.looker_col ?? 0;
    return aCol - bCol;
  });

  const gridCols = sheet.grid_columns || 24;
  grid.style.gridTemplateColumns = `repeat(${gridCols}, minmax(0, 1fr))`;

  sortedWidgets.forEach(w => {
    const tile = document.createElement("div");
    tile.className = "canvas-tile";
    const sourceType = (w.source_type || "").toLowerCase();
    if (sourceType === "filterpane") {
      tile.classList.add("tile-filterpane");
    } else if (sourceType === "kpi") {
      tile.classList.add("tile-kpi");
    }

    const layout = w.layout || { looker_col: 0, looker_width: 6, looker_row: 0, looker_height: 4 };
    const colStart = Math.min(gridCols, Math.max(1, (layout.looker_col || 0) + 1));
    const colSpan = Math.min(gridCols - colStart + 1, Math.max(1, layout.looker_width || 4));
    const rowStart = Math.max(1, (layout.looker_row || 0) + 1);
    const rowSpan = Math.max(1, layout.looker_height || 3);

    tile.style.gridColumn = `${colStart} / span ${colSpan}`;
    tile.style.gridRow = `${rowStart} / span ${rowSpan}`;

    const catInfo = getWidgetCategory(w);
    let boundExplore = "order_details";
    const titleLower = (w.title || "").toLowerCase();
    if (titleLower.includes("customer") || titleLower.includes("cohort") || titleLower.includes("clv") || titleLower.includes("retention")) {
      boundExplore = "customers";
    } else if (titleLower.includes("store") || titleLower.includes("dispatch") || titleLower.includes("fulfillment")) {
      boundExplore = "store_operations";
    } else if (titleLower.includes("margin") || titleLower.includes("cogs") || titleLower.includes("sku")) {
      boundExplore = "product_profitability";
    }

    const isCompact = colSpan <= 3;
    tile.innerHTML = `
      <div>
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px; gap: 4px; flex-wrap: ${isCompact ? 'wrap' : 'nowrap'};">
          <span class="tile-title" style="font-size: ${isCompact ? '11px' : '13px'}; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(w.title)}">${escapeHtml(w.title)}</span>
          <span class="badge ${catInfo.badgeClass}" style="white-space: nowrap; font-size: ${isCompact ? '9px' : '10px'}; padding: 1px 6px;">${catInfo.badgeText}</span>
        </div>
        <div class="tile-body" style="font-size: ${isCompact ? '10px' : '12px'};">
          Type: <strong>${escapeHtml(w.type)}</strong>${isCompact ? '' : ` (${escapeHtml(w.source_type)})`}<br>
          ${gridCols}-Col Bounds: col ${layout.looker_col}, w ${layout.looker_width}
        </div>
      </div>
      <div style="font-family: var(--font-mono); font-size: ${isCompact ? '9px' : '11px'}; color: var(--primary); margin-top: 8px; font-weight: 500; display: flex; align-items: center; justify-content: space-between;">
        <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${isCompact ? boundExplore : `explore: ${boundExplore}`}</span>
        <span style="color: var(--text-muted); font-size: 9px; margin-left: 4px;">r${layout.looker_row}</span>
      </div>
    `;
    grid.appendChild(tile);
  });
}

function toggleGroupBySheet() {
  groupBySheet = !groupBySheet;
  const btn = document.getElementById("btn-group-by-sheet");
  if (btn) {
    btn.classList.toggle("active", groupBySheet);
    btn.innerHTML = groupBySheet ? "🗂️ Grouped by Sheet" : "📋 Flat List View";
  }
  renderFindings(currentAuditCatFilter);
}

function filterFindingsBySheet(val) {
  currentAuditSheetFilter = val;
  renderFindings(currentAuditCatFilter);
}

function renderFindings(catFilter) {
  if (catFilter !== undefined && catFilter !== null) {
    currentAuditCatFilter = catFilter;
  }

  // Populate sheet dropdown options dynamically if needed
  const sheetSelect = document.getElementById("audit-sheet-filter");
  if (sheetSelect && currentFindings && currentFindings.length > 0) {
    const prevSelected = currentAuditSheetFilter;
    const locCounts = {};
    currentFindings.forEach(f => {
      const loc = f.location || f.sheet_title || "Shared Data Model & Script";
      locCounts[loc] = (locCounts[loc] || 0) + 1;
    });

    let selectHtml = `<option value="all">📂 All Sheets & Scopes (${currentFindings.length})</option>`;
    const locKeys = Object.keys(locCounts).sort((a, b) => {
      const isSheetA = a !== "Shared Data Model & Script" && a !== "Global Master Items & Parameters";
      const isSheetB = b !== "Shared Data Model & Script" && b !== "Global Master Items & Parameters";
      if (isSheetA && !isSheetB) return -1;
      if (!isSheetA && isSheetB) return 1;
      return a.localeCompare(b);
    });

    locKeys.forEach(loc => {
      const isSheet = loc !== "Shared Data Model & Script" && loc !== "Global Master Items & Parameters";
      const icon = isSheet ? "📊" : (loc === "Shared Data Model & Script" ? "🗄️" : "⚙️");
      const selectedAttr = loc === prevSelected ? "selected" : "";
      selectHtml += `<option value="${escapeHtml(loc)}" ${selectedAttr}>${icon} ${escapeHtml(loc)} (${locCounts[loc]})</option>`;
    });
    sheetSelect.innerHTML = selectHtml;
    sheetSelect.value = prevSelected;
  }

  const tbody = document.querySelector("#findings-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";

  const filtered = currentFindings.filter(f => {
    const loc = f.location || f.sheet_title || "Shared Data Model & Script";
    const matchesCat = (currentAuditCatFilter === "all") || (f.category.toString() === currentAuditCatFilter.toString());
    const matchesSheet = (currentAuditSheetFilter === "all") || (loc === currentAuditSheetFilter);
    return matchesCat && matchesSheet;
  });

  if (filtered.length === 0) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td colspan="7" style="text-align: center; padding: 32px; color: var(--text-muted); font-size: 13px;">
        No migration gap findings match the selected filter criteria.
      </td>
    `;
    tbody.appendChild(tr);
    return;
  }

  const renderRow = (f) => {
    const tr = document.createElement("tr");
    const badgeClass = f.category === 1 ? "badge-cat1" : (f.category === 2 ? "badge-cat2" : "badge-cat3");
    const loc = f.location || f.sheet_title || "Shared Data Model & Script";
    const isSheet = f.scope_type === "sheet" || (f.sheet_title && loc === f.sheet_title);
    const isModel = loc === "Shared Data Model & Script" || f.scope_type === "data_model";

    let locBadge = "";
    if (isSheet) {
      locBadge = `<span class="badge-sheet-loc" title="${escapeHtml(loc)}">📊 ${escapeHtml(loc)}</span>`;
    } else if (isModel) {
      locBadge = `<span class="badge-model-loc" title="${escapeHtml(loc)}">🗄️ ${escapeHtml(loc)}</span>`;
    } else {
      locBadge = `<span class="badge-global-loc" title="${escapeHtml(loc)}">⚙️ ${escapeHtml(loc)}</span>`;
    }

    const widgetSnippet = f.widget_title ? `<div style="font-size: 11px; color: var(--text-muted); margin-top: 3px;">Tile: <strong>${escapeHtml(f.widget_title)}</strong></div>` : "";

    tr.innerHTML = `
      <td><span class="badge ${badgeClass}">Category ${f.category}</span></td>
      <td><span style="font-weight: 600; font-size: 11px; color: ${f.severity === 'CRITICAL' ? 'var(--cat3-color)' : (f.severity === 'HIGH' ? '#EA580C' : 'var(--text-primary)')};">${f.severity}</span></td>
      <td>
        ${locBadge}
        ${widgetSnippet}
      </td>
      <td style="font-family: var(--font-mono); font-size: 11px; color: var(--text-secondary);">${f.item_type}</td>
      <td>
        <strong style="color: var(--text-primary);">${escapeHtml(f.title || f.raw_expression || f.item_type)}</strong><br>
        <span style="font-size: 12px; color: var(--text-muted);">${escapeHtml(f.description || '')}</span>
      </td>
      <td><pre style="font-family: var(--font-mono); font-size: 11px; background: var(--bg-subtle); padding: 8px; border-radius: 6px; color: var(--primary); border: 1px solid var(--border-subtle); white-space: pre-wrap; margin: 0;">${escapeHtml(f.remediation || f.lookml_remediation || '')}</pre></td>
      <td style="font-weight: 700; color: var(--text-primary);">${f.estimated_remediation_hours || 1}h</td>
    `;
    return tr;
  };

  if (groupBySheet) {
    const groups = {};
    filtered.forEach(f => {
      const loc = f.location || f.sheet_title || "Shared Data Model & Script";
      if (!groups[loc]) groups[loc] = [];
      groups[loc].push(f);
    });

    const sortedGroupKeys = Object.keys(groups).sort((a, b) => {
      const isSheetA = a !== "Shared Data Model & Script" && a !== "Global Master Items & Parameters";
      const isSheetB = b !== "Shared Data Model & Script" && b !== "Global Master Items & Parameters";
      if (isSheetA && !isSheetB) return -1;
      if (!isSheetA && isSheetB) return 1;
      return a.localeCompare(b);
    });

    sortedGroupKeys.forEach(loc => {
      const items = groups[loc];
      const totalHours = items.reduce((sum, item) => sum + (parseFloat(item.estimated_remediation_hours) || 1), 0);
      const isSheet = loc !== "Shared Data Model & Script" && loc !== "Global Master Items & Parameters";
      const icon = isSheet ? "📊" : (loc === "Shared Data Model & Script" ? "🗄️" : "⚙️");
      const groupPrefix = isSheet ? "Sheet / Dashboard" : (loc === "Shared Data Model & Script" ? "Architecture Layer" : "Global Scope");

      const headerTr = document.createElement("tr");
      headerTr.className = "audit-group-header";
      headerTr.innerHTML = `
        <td colspan="7">
          <div class="audit-group-summary">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 15px;">${icon}</span>
              <span style="font-size: 13px; font-weight: 700; color: var(--text-primary);">
                ${groupPrefix}: <span style="color: var(--primary);">${escapeHtml(loc)}</span>
              </span>
            </div>
            <div style="display: flex; align-items: center; gap: 8px;">
              <span class="badge" style="background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border-subtle); font-weight: 600; font-size: 11px;">
                ${items.length} ${items.length === 1 ? 'Issue' : 'Issues'}
              </span>
              <span class="badge" style="background: #EFF6FF; color: #1D4ED8; border: 1px solid #BFDBFE; font-weight: 600; font-size: 11px;">
                ⏱️ ${totalHours.toFixed(1)}h Total Remediation
              </span>
            </div>
          </div>
        </td>
      `;
      tbody.appendChild(headerTr);

      items.forEach(f => {
        tbody.appendChild(renderRow(f));
      });
    });
  } else {
    filtered.forEach(f => {
      tbody.appendChild(renderRow(f));
    });
  }
}

async function runStage2() {
  if (!currentCanonicalIR && currentAppId) {
    try {
      const irRes = await fetch(`/api/stage1/ir/${currentAppId}`);
      if (irRes.ok) {
        const irData = await irRes.json();
        if (irData) {
          currentCanonicalIR = irData.canonical_ir || (irData.visual_catalog ? irData : null);
        }
      }
    } catch (e) {
      console.warn("Could not fetch cached IR:", e);
    }
  }

  if (!currentCanonicalIR) {
    alert("Please run Stage 1 first to compile the Canonical IR!");
    return;
  }

  showLoading("Synthesizing Explore-Centric LookML...", "Compiling Star/Snowflake Joins, Dashboard LookML, and upstream dbt models");

  const targetExplore = document.getElementById("target-explore-input").value || "order_details";
  const targetModel = document.getElementById("target-model-input").value || "enterprise_analytics";

  try {
    const res = await fetch("/api/stage2/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        app_id: currentAppId,
        canonical_ir: currentCanonicalIR,
        target_explore: targetExplore,
      }),
    });
    const data = await res.json();
    currentArtifacts = data.artifacts;
    renderLookMLFile(activeLookMLType);

    // Update header progress pill
    const s2Badge = document.getElementById("stage2-badge");
    s2Badge.classList.add("active");
    s2Badge.innerHTML = '<span style="color: var(--accent-success);">●</span> STAGE 2: EXPLORE-FIRST CODE GENERATION (READY)';
  } catch (err) {
    document.getElementById("lookml-code-preview").textContent = `[ERROR] Stage 2 generation failed: ${err.message}`;
  } finally {
    setTimeout(hideLoading, 400);
  }
}

function renderLookMLFile(fileType) {
  const preview = document.getElementById("lookml-code-preview");
  if (!currentArtifacts) {
    preview.textContent = "// Click 'Generate LookML Suite' to compile...";
    return;
  }
  if (fileType === "explore") {
    const key = Object.keys(currentArtifacts.explores)[0];
    preview.textContent = currentArtifacts.explores[key];
  } else if (fileType === "dashboard") {
    const key = Object.keys(currentArtifacts.dashboards)[0];
    preview.textContent = currentArtifacts.dashboards[key];
  } else if (fileType === "view") {
    const key = Object.keys(currentArtifacts.views)[0];
    preview.textContent = currentArtifacts.views[key];
  } else if (fileType === "dbt") {
    const key = Object.keys(currentArtifacts.dbt_models)[0];
    preview.textContent = currentArtifacts.dbt_models[key];
  }
}

function copyLookMLCode() {
  const preview = document.getElementById("lookml-code-preview");
  const btn = document.getElementById("btn-copy-lookml");
  navigator.clipboard.writeText(preview.textContent).then(() => {
    btn.textContent = "✓ Copied to Clipboard!";
    btn.style.background = "var(--accent-success)";
    btn.style.color = "#FFFFFF";
    setTimeout(() => {
      btn.textContent = "📋 Copy Code";
      btn.style.background = "rgba(255, 255, 255, 0.1)";
      btn.style.color = "#E2E8F0";
    }, 2000);
  });
}

function downloadIRBundle() {
  if (!currentCanonicalIR) {
    showToast("No Canonical IR generated yet. Run Stage 1 first!", "error");
    return;
  }
  const appId = currentCanonicalIR.app_metadata?.app_id || "bundle";
  const str = JSON.stringify(currentCanonicalIR, null, 2);
  const blob = new Blob([str], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `canonical_ir_${appId}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showToast(`Downloaded Canonical IR for ${appId}`, "info");
}

async function downloadAppIR(appId) {
  try {
    showLoading("Fetching Canonical IR...", `Retrieving Canonical IR bundle for ${appId}`);
    let ir = null;
    if (currentCanonicalIR && currentCanonicalIR.app_metadata && currentCanonicalIR.app_metadata.app_id === appId) {
      ir = currentCanonicalIR;
    } else {
      const res = await fetch(`/api/stage1/ir/${encodeURIComponent(appId)}`);
      if (res.ok) {
        ir = await res.json();
      } else {
        const extractRes = await fetch("/api/stage1/extract", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ app_id: appId, use_sample: false }),
        });
        if (extractRes.ok) {
          const extractData = await extractRes.json();
          ir = extractData.canonical_ir;
        }
      }
    }
    hideLoading();
    if (!ir) {
      showToast(`Unable to generate Canonical IR for ${appId}`, "error");
      return;
    }
    const str = JSON.stringify(ir, null, 2);
    const blob = new Blob([str], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `canonical_ir_${appId}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast(`Downloaded Canonical IR bundle for ${appId}`, "info");
  } catch (err) {
    hideLoading();
    showToast(`Failed to download IR: ${err.message}`, "error");
  }
}

function copyCanonicalIRJSON() {
  if (!currentCanonicalIR) {
    showToast("No Canonical IR generated yet", "error");
    return;
  }
  const str = JSON.stringify(currentCanonicalIR, null, 2);
  navigator.clipboard.writeText(str).then(() => {
    showToast("Canonical IR JSON copied to clipboard!", "info");
  }).catch(() => {
    showToast("Failed to copy to clipboard", "error");
  });
}

function showToast(message, type = "info") {
  let toastContainer = document.getElementById("toast-container");
  if (!toastContainer) {
    toastContainer = document.createElement("div");
    toastContainer.id = "toast-container";
    toastContainer.style.cssText = "position: fixed; bottom: 24px; right: 24px; z-index: 9999; display: flex; flex-direction: column; gap: 8px;";
    document.body.appendChild(toastContainer);
  }
  const toast = document.createElement("div");
  const isError = type === "error";
  toast.style.cssText = `
    background: ${isError ? "#EF4444" : "#1F2937"};
    color: #FFFFFF;
    padding: 12px 20px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 500;
    box-shadow: 0 4px 14px rgba(0,0,0,0.15);
    display: flex;
    align-items: center;
    gap: 8px;
    transition: opacity 0.3s ease;
  `;
  toast.textContent = message;
  toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

/* ==========================================================================
   Executive Command Center Controller
   ========================================================================== */
async function loadExecutiveMetrics() {
  try {
    const [execRes, clustersRes] = await Promise.all([
      fetch("/api/fleet/executive"),
      fetch("/api/fleet/clusters")
    ]);

    if (execRes.ok) {
      currentExecutiveData = await execRes.json();
      renderExecutiveMetrics(currentExecutiveData);
    }

    if (clustersRes.ok) {
      const cData = await clustersRes.json();
      renderExecutiveClusters(cData.clusters || []);
    }
  } catch (err) {
    console.error("Failed to load executive metrics:", err);
  }
}

function renderExecutiveMetrics(data) {
  if (!data) return;
  const summary = data.summary || {};
  const waveDist = data.wave_distribution || {};
  const savings = data.semantic_savings || {};

  const statTotal = document.getElementById("exec-stat-total");
  if (statTotal) statTotal.textContent = `${summary.total_apps || 0} Apps`;

  const statSubAssets = document.getElementById("exec-stat-sub-assets");
  if (statSubAssets) statSubAssets.textContent = `${summary.total_sheets || 0} Sheets · ${summary.total_widgets || 0} Visual Elements`;

  const statReadiness = document.getElementById("exec-stat-readiness");
  if (statReadiness) statReadiness.textContent = `${summary.portfolio_readiness_pct || 0}%`;

  const fillReadiness = document.getElementById("exec-readiness-fill");
  if (fillReadiness) fillReadiness.style.width = `${summary.portfolio_readiness_pct || 0}%`;

  const statSubReadiness = document.getElementById("exec-stat-sub-readiness");
  if (statSubReadiness) statSubReadiness.textContent = `${summary.active_apps || 0} Active · ${summary.decommissioned_apps || 0} Sunsetting`;

  const statWaves = document.getElementById("exec-stat-waves");
  if (statWaves) statWaves.textContent = `${waveDist.wave1 || 0} in Wave 1`;

  const statSubWaves = document.getElementById("exec-stat-sub-waves");
  if (statSubWaves) statSubWaves.textContent = `${waveDist.wave2 || 0} Wave 2 · ${waveDist.wave3 || 0} Wave 3 · ${waveDist.decommissioned || 0} Sunsetting`;

  const statSavings = document.getElementById("exec-stat-savings");
  const count = savings.models_consolidated || 0;
  const noun = count === 1 ? "Model" : "Models";
  if (statSavings) statSavings.textContent = `${count} ${noun} Consolidated`;

  const statSubSavings = document.getElementById("exec-stat-sub-savings");
  const hours = savings.estimated_hours_saved || 0;
  if (statSubSavings) {
    statSubSavings.textContent = hours > 0
      ? `Est. ~${hours} hrs developer time saved`
      : "0 hrs developer time saved";
  }

  // Render Space breakdown
  const spaceContainer = document.getElementById("exec-space-breakdown-container");
  if (spaceContainer) {
    spaceContainer.innerHTML = "";
    (data.space_breakdown || []).forEach(sb => {
      const card = document.createElement("div");
      card.className = "space-risk-card";
      let icon = "🛡️";
      if (sb.type === "shared") icon = "👥";
      else if (sb.type === "personal") icon = "👤";
      else if (sb.type === "stream") icon = "📡";
      else if (sb.type === "work") icon = "🔧";

      card.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 16px;">${icon}</span>
            <strong style="font-size: 13px; color: var(--text-primary);">${escapeHtml(sb.label)}</strong>
          </div>
          <span class="badge" style="background: var(--bg-subtle); color: var(--text-primary); font-size: 11px;">
            ${sb.total_apps} Apps (${sb.sheets} Sheets)
          </span>
        </div>
        <div class="space-risk-bar-container">
          <div class="space-risk-bar-fill" style="width: ${sb.readiness_pct}%;"></div>
        </div>
        <div style="display: flex; justify-content: space-between; font-size: 11px; color: var(--text-muted);">
          <span>${sb.compiled_apps} / ${sb.total_apps} IR Compiled</span>
          <span style="font-weight: 600; color: var(--primary);">${sb.readiness_pct}% Ready</span>
        </div>
      `;
      spaceContainer.appendChild(card);
    });
  }
}

function renderExecutiveClusters(clusters) {
  const container = document.getElementById("exec-clusters-container");
  if (!container) return;
  container.innerHTML = "";

  if (clusters.length === 0) {
    container.innerHTML = `<div style="color: var(--text-muted); padding: 24px; text-align: center;">No semantic redundancy clusters identified yet. Extract apps in Stage 1 to analyze data models.</div>`;
    return;
  }

  clusters.forEach(cluster => {
    const card = document.createElement("div");
    card.className = "cluster-card";

    const tablesHtml = (cluster.shared_tables || []).slice(0, 6).map(t => `<span class="cluster-table-pill">${escapeHtml(t)}</span>`).join(" ");
    const appsHtml = (cluster.apps || []).map(a => `<span class="badge" style="background: #EEF2FF; color: var(--primary); font-size: 11px;">📊 ${escapeHtml(a.name)}</span>`).join(" ");

    card.innerHTML = `
      <div class="cluster-header">
        <div>
          <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 2px;">
            Unified Data Domain
          </div>
          <h4 style="font-size: 15px; font-weight: 700; color: var(--text-primary); margin: 0;">
            ${escapeHtml(cluster.domain_name)}
          </h4>
        </div>
        <span class="cluster-tag">${escapeHtml(cluster.status || "CONSOLIDATE")}</span>
      </div>

      <p style="font-size: 12px; color: var(--text-secondary); margin: 0; line-height: 1.4;">
        ${escapeHtml(cluster.description)}
      </p>

      <div style="display: flex; flex-direction: column; gap: 6px;">
        <span style="font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase;">Shared Schema Entities:</span>
        <div style="display: flex; flex-wrap: wrap; gap: 6px;">
          ${tablesHtml}
        </div>
      </div>

      <div style="display: flex; flex-direction: column; gap: 6px;">
        <span style="font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase;">Clustered Applications:</span>
        <div style="display: flex; flex-wrap: wrap; gap: 6px;">
          ${appsHtml}
        </div>
      </div>

      <div style="padding: 10px 14px; background: #F8FAFC; border: 1px dashed var(--border-subtle); border-radius: 6px; font-size: 12px; display: flex; justify-content: space-between; align-items: center;">
        <span>Recommended Explore: <code style="color: var(--primary); font-weight: 600;">${escapeHtml(cluster.recommended_explore)}</code></span>
        <span style="color: #059669; font-weight: 600; font-size: 11px;">${escapeHtml(cluster.savings_label)}</span>
      </div>

      <div style="display: flex; gap: 8px; justify-content: flex-end; margin-top: 4px;">
        <button class="btn-secondary" style="font-size: 12px; padding: 6px 12px;" onclick="batchAssignWaveForCluster(${JSON.stringify(cluster.apps.map(a => a.app_id)).replace(/"/g, '&quot;')}, 'wave1')">
          🌊 Assign Cluster to Wave 1
        </button>
        <button class="btn-primary" style="font-size: 12px; padding: 6px 12px;" onclick="loadApp('${escapeHtml(cluster.apps[0].app_id)}')">
          🔬 Inspect Primary App →
        </button>
      </div>
    `;
    container.appendChild(card);
  });
}

function exportExecutiveSummaryJSON() {
  const exportData = {
    export_timestamp: new Date().toISOString(),
    executive_summary: currentExecutiveData,
    fleet_summary: currentFleetSummary,
  };
  const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "executive_migration_portfolio_summary.json";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showToast("Executive Portfolio Summary exported successfully!");
}

/* ==========================================================================
   Migration Waves & Sprint Planner Controller
   ========================================================================== */
async function loadWavesData() {
  try {
    const res = await fetch("/api/waves");
    if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to fetch waves`);
    currentWavesData = await res.json();
    allWaveApps = [];
    Object.values(currentWavesData.waves || {}).forEach(arr => {
      allWaveApps = allWaveApps.concat(arr);
    });
    renderWavesKanban(currentWavesData);
  } catch (err) {
    console.error("Failed to load waves:", err);
  }
}

function renderWavesKanban(data) {
  if (!data || !data.waves) return;
  const waves = data.waves;

  const waveKeys = ["unassigned", "wave1", "wave2", "wave3", "decommissioned"];
  waveKeys.forEach(k => {
    const countEl = document.getElementById(`count-${k}`);
    if (countEl) countEl.textContent = (waves[k] || []).length;
    const cardsEl = document.getElementById(`cards-${k}`);
    if (cardsEl) {
      cardsEl.innerHTML = "";
      (waves[k] || []).forEach(app => {
        const card = createKanbanCard(app, k);
        cardsEl.appendChild(card);
      });
    }
  });

  filterWaveCards();
}

function createKanbanCard(app, currentWave) {
  const card = document.createElement("div");
  card.className = "kanban-card";
  card.dataset.appId = app.app_id;
  card.dataset.appName = (app.name || "").toLowerCase();
  card.dataset.lead = app.assigned_lead || "Unassigned";
  card.dataset.spaceType = (app.space_type || "managed").toLowerCase();

  // Space badge
  let spaceBadge = `<span class="badge" style="background: #EEF2FF; color: var(--primary); font-size: 10px;">${escapeHtml(app.stream_or_space || "Space")}</span>`;
  if (app.space_type === "personal") {
    spaceBadge = `<span class="badge" style="background: #FDF4FF; color: #A21CAF; font-size: 10px;">👤 Personal</span>`;
  }

  // Lifecycle stage pill
  const stage = (app.lifecycle_stage || app.extraction_status || "discovered").toLowerCase();
  let stageLabel = "Discovered";
  let stageBg = "#F1F5F9";
  let stageColor = "#475569";
  if (stage.includes("lookml")) {
    stageLabel = "LookML Ready";
    stageBg = "#ECFDF5";
    stageColor = "#059669";
  } else if (stage.includes("compiled") || stage.includes("ir")) {
    stageLabel = "IR Compiled";
    stageBg = "#EEF2FF";
    stageColor = "#4F46E5";
  } else if (stage.includes("extract")) {
    stageLabel = "Extracted";
    stageBg = "#FEF3C7";
    stageColor = "#92400E";
  } else if (stage.includes("deploy")) {
    stageLabel = "Deployed";
    stageBg = "#D1FAE5";
    stageColor = "#065F46";
  }

  const leadNames = ["Unassigned"];
  cachedLeads.forEach(l => {
    if (!leadNames.includes(l.name)) leadNames.push(l.name);
  });
  if (app.assigned_lead && !leadNames.includes(app.assigned_lead)) {
    leadNames.push(app.assigned_lead);
  }

  const stages = [
    { val: "discovered", lbl: "Discovered" },
    { val: "extracted", lbl: "Extracted" },
    { val: "ir_compiled", lbl: "IR Compiled" },
    { val: "lookml_ready", lbl: "LookML Ready" },
    { val: "deployed", lbl: "Deployed" }
  ];
  const waveOptions = [
    { val: "unassigned", lbl: "Backlog" },
    { val: "wave1", lbl: "Wave 1 (Quick Win)" },
    { val: "wave2", lbl: "Wave 2 (Governed)" },
    { val: "wave3", lbl: "Wave 3 (Complex)" },
    { val: "decommissioned", lbl: "Decommissioned" }
  ];

  const waveSelectOpts = waveOptions.map(w => `<option value="${w.val}" ${currentWave === w.val ? "selected" : ""}>${w.lbl}</option>`).join("");
  const leadSelectOpts = leadNames.map(l => {
    const leadObj = cachedLeads.find(c => c.name === l);
    const isAI = l.toLowerCase().includes("ai ") || l.toLowerCase().includes("agent") || (leadObj && (leadObj.role || "").toLowerCase().includes("agent")) || (leadObj && (leadObj.role || "").toLowerCase().includes("runner"));
    const icon = l === "Unassigned" ? "" : (isAI ? "🤖 " : "👤 ");
    const roleAbbr = leadObj ? ` · ${leadObj.role}` : "";
    return `<option value="${escapeHtml(l)}" ${(app.assigned_lead || "Unassigned") === l ? "selected" : ""}>${icon}${escapeHtml(l)}${escapeHtml(roleAbbr)}</option>`;
  }).join("");
  const stageSelectOpts = stages.map(s => `<option value="${s.val}" ${stage.includes(s.val) ? "selected" : ""}>${s.lbl}</option>`).join("");

  card.innerHTML = `
    <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;">
      <span class="kanban-card-title">${escapeHtml(app.name)}</span>
      <span class="badge" style="background: ${stageBg}; color: ${stageColor}; font-size: 10px; font-weight: 600;">${stageLabel}</span>
    </div>

    <div class="kanban-card-meta">
      ${spaceBadge}
      <span>·</span>
      <span>${app.sheet_count} Sheets</span>
      <span>·</span>
      <span>${app.widget_count} Tiles</span>
    </div>

    <div class="kanban-card-controls">
      <div>
        <label style="display: block; font-size: 10px; font-weight: 600; color: var(--text-muted); text-transform: uppercase;">Wave</label>
        <select class="kanban-select" style="width: 100%;" onchange="updateAppWave('${escapeHtml(app.app_id)}', this.value)">
          ${waveSelectOpts}
        </select>
      </div>
      <div>
        <label style="display: block; font-size: 10px; font-weight: 600; color: var(--text-muted); text-transform: uppercase;">Lead</label>
        <select class="kanban-select" style="width: 100%;" onchange="updateAppLead('${escapeHtml(app.app_id)}', this.value)">
          ${leadSelectOpts}
        </select>
      </div>
    </div>

    <div style="margin-top: 4px;">
      <label style="display: block; font-size: 10px; font-weight: 600; color: var(--text-muted); text-transform: uppercase;">Lifecycle Stage</label>
      <select class="kanban-select" style="width: 100%;" onchange="updateAppStage('${escapeHtml(app.app_id)}', this.value)">
        ${stageSelectOpts}
      </select>
    </div>

    <div class="kanban-card-footer">
      <span style="font-family: var(--font-mono); font-size: 10px; color: var(--text-muted);">${escapeHtml(app.app_id.slice(0, 8))}...</span>
      <button class="btn-secondary" style="font-size: 11px; padding: 4px 8px; color: var(--primary); font-weight: 600;" onclick="inspectFromWave('${escapeHtml(app.app_id)}')">
        🔍 Inspect in Stage 1 →
      </button>
    </div>
  `;
  return card;
}

async function updateAppWave(appId, wave) {
  try {
    const res = await fetch("/api/waves/assign", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app_ids: [appId], wave: wave })
    });
    if (res.ok) {
      showToast(`Application moved to ${wave.toUpperCase()}`);
      loadWavesData();
      loadExecutiveMetrics();
    }
  } catch (err) {
    console.error("Failed to update app wave:", err);
  }
}

async function updateAppLead(appId, lead) {
  try {
    const res = await fetch("/api/waves/assign", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app_ids: [appId], lead: lead })
    });
    if (res.ok) {
      showToast(`Assigned lead: ${lead}`);
      loadWavesData();
    }
  } catch (err) {
    console.error("Failed to update app lead:", err);
  }
}

async function updateAppStage(appId, stage) {
  try {
    const res = await fetch("/api/waves/assign", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app_ids: [appId], lifecycle_stage: stage })
    });
    if (res.ok) {
      showToast(`Updated stage: ${stage.toUpperCase()}`);
      loadWavesData();
      loadExecutiveMetrics();
    }
  } catch (err) {
    console.error("Failed to update app stage:", err);
  }
}

function inspectFromWave(appId) {
  switchTab("tab-canvas");
  loadApp(appId);
}

function filterWaveCards() {
  const query = (document.getElementById("wave-filter-search")?.value || "").toLowerCase().trim();
  const lead = document.getElementById("wave-filter-lead")?.value || "all";
  const space = document.getElementById("wave-filter-space")?.value || "all";

  let visibleCount = 0;
  const cards = document.querySelectorAll(".kanban-card");
  cards.forEach(card => {
    const nameMatch = !query || card.dataset.appName.includes(query) || card.dataset.appId.toLowerCase().includes(query);
    const leadMatch = lead === "all" || card.dataset.lead === lead;
    const spaceMatch = space === "all" || card.dataset.spaceType === space;

    const visible = nameMatch && leadMatch && spaceMatch;
    card.style.display = visible ? "flex" : "none";
    if (visible) visibleCount++;
  });

  const countEl = document.getElementById("wave-filter-count");
  if (countEl) {
    countEl.textContent = `Showing ${visibleCount} of ${cards.length} applications`;
  }
}

/* ==========================================================================
   Portfolio Export & Download Controller (CSV & JSON)
   ========================================================================== */
function toggleExportMenu(e) {
  if (e) e.stopPropagation();
  const menu = document.getElementById("export-dropdown-menu");
  if (!menu) return;
  menu.style.display = menu.style.display === "block" ? "none" : "block";
}

document.addEventListener("click", () => {
  const menu = document.getElementById("export-dropdown-menu");
  if (menu) menu.style.display = "none";
});

function exportPortfolioCSV() {
  const menu = document.getElementById("export-dropdown-menu");
  if (menu) menu.style.display = "none";
  showToast("Exporting portfolio details to CSV...");
  window.location.href = "/api/portfolio/export?format=csv";
}

function exportPortfolioJSON() {
  const menu = document.getElementById("export-dropdown-menu");
  if (menu) menu.style.display = "none";
  showToast("Exporting portfolio details to JSON...");
  window.location.href = "/api/portfolio/export?format=json";
}

/* ==========================================================================
   Migration Wave Policy Builder & Assignment Wizard Controller
   ========================================================================== */
let cachedPolicies = [];
let currentSimulationDiff = null;
let activeWizardStep = "rules";

async function openPolicyWizardModal(step = "rules") {
  const modal = document.getElementById("modal-policy-wizard");
  if (!modal) return;
  modal.style.display = "flex";
  await loadPolicyLeadDropdown();
  await loadPolicyRules();
  switchWizardTab(step);
}

function closePolicyWizardModal() {
  const modal = document.getElementById("modal-policy-wizard");
  if (modal) modal.style.display = "none";
  togglePolicyForm(false);
}

async function autoAssignWavesByPolicy() {
  // Directly opens the Policy Wizard on the simulation step
  openPolicyWizardModal("simulate");
}

function switchWizardTab(step) {
  activeWizardStep = step;
  const tabs = ["rules", "simulate", "apply"];
  tabs.forEach(t => {
    const btn = document.getElementById(`btn-step-${t}`);
    const pane = document.getElementById(`wizard-pane-${t}`);
    if (btn) {
      if (t === step) {
        btn.classList.add("active");
        btn.style.color = "var(--primary)";
        btn.style.borderBottomColor = "var(--primary)";
        const numSpan = btn.querySelector("span:first-child");
        if (numSpan) {
          numSpan.style.background = "var(--primary)";
          numSpan.style.color = "white";
        }
      } else {
        btn.classList.remove("active");
        btn.style.color = "var(--text-muted)";
        btn.style.borderBottomColor = "transparent";
        const numSpan = btn.querySelector("span:first-child");
        if (numSpan) {
          numSpan.style.background = "var(--border-subtle)";
          numSpan.style.color = "var(--text-muted)";
        }
      }
    }
    if (pane) {
      pane.style.display = t === step ? "block" : "none";
    }
  });

  if (step === "simulate" && !currentSimulationDiff) {
    runPolicySimulation();
  } else if (step === "apply") {
    updateApplyCount();
  }
}

async function loadPolicyLeadDropdown() {
  const select = document.getElementById("form-policy-lead");
  if (!select) return;
  try {
    const res = await fetch("/api/leads");
    if (!res.ok) return;
    const data = await res.json();
    const leads = data.leads || [];
    let html = "";
    leads.forEach(lead => {
      const isAI = lead.name.toLowerCase().includes("ai ") || lead.name.toLowerCase().includes("agent") || (lead.role || "").toLowerCase().includes("agent") || (lead.role || "").toLowerCase().includes("runner");
      const icon = isAI ? "🤖" : "👤";
      html += `<option value="${escapeHtml(lead.name)}">${icon} ${escapeHtml(lead.name)} (${escapeHtml(lead.role)})</option>`;
    });
    html += `<option value="Unassigned">👤 Unassigned</option>`;
    select.innerHTML = html;
  } catch (err) {
    console.error("Failed to load leads for policy select:", err);
  }
}

async function loadPolicyRules() {
  const container = document.getElementById("policy-rules-list-container");
  if (!container) return;
  try {
    const res = await fetch("/api/policies");
    if (!res.ok) throw new Error("Failed to load policy rules");
    const data = await res.json();
    cachedPolicies = data.policies || [];
    renderPolicyRulesList(cachedPolicies);
  } catch (err) {
    container.innerHTML = `<div style="color: #EF4444; padding: 16px; text-align: center;">Failed to load policies: ${escapeHtml(err.message)}</div>`;
  }
}

function renderPolicyRulesList(policies) {
  const container = document.getElementById("policy-rules-list-container");
  if (!container) return;

  if (policies.length === 0) {
    container.innerHTML = `
      <div style="padding: 24px; text-align: center; color: var(--text-muted); background: var(--bg-card); border: 1px dashed var(--border-subtle); border-radius: 8px;">
        <div style="font-size: 28px; margin-bottom: 6px;">📋</div>
        <div style="font-weight: 600;">No policy rules defined yet</div>
        <div style="font-size: 12px; margin-top: 4px;">Click "Create New Policy Rule" above to define automated wave assignment rules.</div>
      </div>
    `;
    return;
  }

  const waveColors = {
    wave1: { bg: "#D1FAE5", text: "#065F46", label: "Wave 1: Quick Wins" },
    wave2: { bg: "#EEF2FF", text: "#3730A3", label: "Wave 2: Core Governed" },
    wave3: { bg: "#FEF3C7", text: "#92400E", label: "Wave 3: Complex Multi-Fact" },
    decommissioned: { bg: "#FEE2E2", text: "#991B1B", label: "Decommissioned" },
    unassigned: { bg: "#F1F5F9", text: "#475569", label: "Backlog" }
  };

  container.innerHTML = policies.map((policy, idx) => {
    const conds = policy.conditions || {};
    const acts = policy.actions || {};
    const wInfo = waveColors[acts.target_wave] || { bg: "#EEF2FF", text: "#4F46E5", label: acts.target_wave || "None" };

    const condChips = [];
    if (conds.match_mode) {
      condChips.push(`<span class="badge" style="background: #F1F5F9; color: #475569; font-size: 10px;">${escapeHtml(conds.match_mode)}</span>`);
    }
    if (conds.space_types && conds.space_types.length) {
      condChips.push(`<span class="badge" style="background: #E0E7FF; color: #3730A3; font-size: 10px;">Spaces: ${escapeHtml(conds.space_types.join(", "))}</span>`);
    }
    if (conds.name_keywords && conds.name_keywords.length) {
      condChips.push(`<span class="badge" style="background: #FEF3C7; color: #92400E; font-size: 10px;">Keywords: ${escapeHtml(conds.name_keywords.join(", "))}</span>`);
    }
    if (conds.min_sheets !== undefined && conds.min_sheets !== null) {
      condChips.push(`<span class="badge" style="background: #F3E8FF; color: #6B21A8; font-size: 10px;">Sheets &ge; ${conds.min_sheets}</span>`);
    }
    if (conds.max_sheets !== undefined && conds.max_sheets !== null) {
      condChips.push(`<span class="badge" style="background: #F3E8FF; color: #6B21A8; font-size: 10px;">Sheets &le; ${conds.max_sheets}</span>`);
    }
    if (conds.min_widgets !== undefined && conds.min_widgets !== null) {
      condChips.push(`<span class="badge" style="background: #F3E8FF; color: #6B21A8; font-size: 10px;">Widgets &ge; ${conds.min_widgets}</span>`);
    }
    if (conds.finding_categories && conds.finding_categories.length) {
      condChips.push(`<span class="badge" style="background: #FEE2E2; color: #991B1B; font-size: 10px;">Cat ${conds.finding_categories.join("/")} Findings</span>`);
    }
    if (condChips.length === 0) {
      condChips.push(`<span class="badge" style="background: #F1F5F9; color: #64748B; font-size: 10px;">Catch-All (Any App)</span>`);
    }

    const leadDisplay = acts.target_lead || "Retain Current";
    const isActive = policy.is_active !== 0;

    return `
      <div style="background: var(--bg-card); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 12px 16px; display: flex; align-items: center; justify-content: space-between; gap: 14px; opacity: ${isActive ? '1' : '0.55'};">
        <div style="display: flex; align-items: center; gap: 12px; min-width: 0; flex: 1;">
          <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; width: 34px; height: 34px; border-radius: 8px; background: rgba(79, 70, 229, 0.1); color: var(--primary); font-weight: 700; font-size: 13px; flex-shrink: 0;">
            #${policy.priority || (idx + 1)}
          </div>
          <div style="min-width: 0; flex: 1;">
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <span style="font-weight: 700; font-size: 13px; color: var(--text-primary);">${escapeHtml(policy.name)}</span>
              ${!isActive ? '<span class="badge" style="background: #F1F5F9; color: #64748B; font-size: 10px;">Disabled</span>' : ''}
            </div>
            ${policy.description ? `<div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">${escapeHtml(policy.description)}</div>` : ''}
            <div style="display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; align-items: center;">
              <span style="font-size: 10px; color: var(--text-secondary); font-weight: 600; text-transform: uppercase;">IF:</span>
              ${condChips.join(" ")}
              <span style="font-size: 10px; color: var(--text-secondary); font-weight: 600; text-transform: uppercase; margin-left: 4px;">THEN:</span>
              <span class="badge" style="background: ${wInfo.bg}; color: ${wInfo.text}; font-size: 10px; font-weight: 600;">→ ${escapeHtml(wInfo.label)}</span>
              <span class="badge" style="background: #EFF6FF; color: #1D4ED8; font-size: 10px; font-weight: 600;">👤 ${escapeHtml(leadDisplay)}</span>
            </div>
          </div>
        </div>
        <div style="display: flex; gap: 8px; align-items: center; flex-shrink: 0;">
          <button type="button" class="btn-secondary" style="font-size: 11px; padding: 5px 10px;" onclick="editPolicyRule('${escapeHtml(policy.policy_id)}')">✏️ Edit</button>
          <button type="button" class="btn-secondary" style="font-size: 11px; padding: 5px 8px; color: #EF4444; border-color: rgba(239,68,68,0.3); cursor: pointer;" onclick="deletePolicyRule('${escapeHtml(policy.policy_id)}')">🗑</button>
        </div>
      </div>
    `;
  }).join("");
}

function togglePolicyForm(show, policy = null) {
  const panel = document.getElementById("policy-editor-form-panel");
  const form = document.getElementById("policy-rule-form");
  const titleEl = document.getElementById("policy-form-title");
  if (!panel || !form) return;

  if (show) {
    panel.style.display = "block";
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    if (policy) {
      if (titleEl) titleEl.textContent = "✏️ Edit Policy Rule: " + policy.name;
      document.getElementById("form-policy-id").value = policy.policy_id || "";
      document.getElementById("form-policy-name").value = policy.name || "";
      document.getElementById("form-policy-priority").value = policy.priority || 1;
      document.getElementById("form-policy-desc").value = policy.description || "";
      const conds = policy.conditions || {};
      document.getElementById("form-policy-match-mode").value = conds.match_mode || "ALL";
      document.getElementById("form-policy-keywords").value = (conds.name_keywords || []).join(", ");
      document.getElementById("form-policy-min-sheets").value = conds.min_sheets !== undefined && conds.min_sheets !== null ? conds.min_sheets : "";
      document.getElementById("form-policy-max-sheets").value = conds.max_sheets !== undefined && conds.max_sheets !== null ? conds.max_sheets : "";
      document.getElementById("form-policy-min-widgets").value = conds.min_widgets !== undefined && conds.min_widgets !== null ? conds.min_widgets : "";
      document.getElementById("form-policy-finding-cat").value = (conds.finding_categories && conds.finding_categories.length) ? conds.finding_categories[0] : "";

      const spaceCheckboxes = document.querySelectorAll('input[name="policy-space-type"]');
      const targetSpaces = (conds.space_types || []).map(s => s.toLowerCase());
      spaceCheckboxes.forEach(cb => {
        cb.checked = targetSpaces.includes(cb.value.toLowerCase());
      });

      const acts = policy.actions || {};
      if (acts.target_wave) document.getElementById("form-policy-wave").value = acts.target_wave;
      if (acts.target_lead) document.getElementById("form-policy-lead").value = acts.target_lead;
    } else {
      if (titleEl) titleEl.textContent = "➕ Define Policy Rule";
      form.reset();
      document.getElementById("form-policy-id").value = "";
      document.getElementById("form-policy-priority").value = cachedPolicies.length + 1;
    }
  } else {
    panel.style.display = "none";
    form.reset();
    document.getElementById("form-policy-id").value = "";
  }
}

function editPolicyRule(policyId) {
  const policy = cachedPolicies.find(p => p.policy_id === policyId);
  if (policy) {
    togglePolicyForm(true, policy);
  }
}

async function submitSavePolicyRule() {
  const name = document.getElementById("form-policy-name")?.value?.trim();
  if (!name) {
    showToast("Policy name is required", "error");
    return;
  }
  const policyId = document.getElementById("form-policy-id")?.value || null;
  const priority = parseInt(document.getElementById("form-policy-priority")?.value || "1", 10);
  const matchMode = document.getElementById("form-policy-match-mode")?.value || "ALL";
  const desc = document.getElementById("form-policy-desc")?.value?.trim() || "";

  const spaceCheckboxes = document.querySelectorAll('input[name="policy-space-type"]:checked');
  const spaceTypes = Array.from(spaceCheckboxes).map(cb => cb.value);

  const keywordsRaw = document.getElementById("form-policy-keywords")?.value || "";
  const nameKeywords = keywordsRaw.split(",").map(k => k.trim()).filter(Boolean);

  const minSheetsVal = document.getElementById("form-policy-min-sheets")?.value;
  const maxSheetsVal = document.getElementById("form-policy-max-sheets")?.value;
  const minWidgetsVal = document.getElementById("form-policy-min-widgets")?.value;
  const findingCatVal = document.getElementById("form-policy-finding-cat")?.value;

  const conditions = {
    match_mode: matchMode
  };
  if (spaceTypes.length > 0) conditions.space_types = spaceTypes;
  if (nameKeywords.length > 0) conditions.name_keywords = nameKeywords;
  if (minSheetsVal !== "" && !isNaN(parseInt(minSheetsVal, 10))) conditions.min_sheets = parseInt(minSheetsVal, 10);
  if (maxSheetsVal !== "" && !isNaN(parseInt(maxSheetsVal, 10))) conditions.max_sheets = parseInt(maxSheetsVal, 10);
  if (minWidgetsVal !== "" && !isNaN(parseInt(minWidgetsVal, 10))) conditions.min_widgets = parseInt(minWidgetsVal, 10);
  if (findingCatVal !== "" && !isNaN(parseInt(findingCatVal, 10))) conditions.finding_categories = [parseInt(findingCatVal, 10)];

  const targetWave = document.getElementById("form-policy-wave")?.value || "wave1";
  const targetLead = document.getElementById("form-policy-lead")?.value || "Unassigned";

  const actions = {
    target_wave: targetWave,
    target_lead: targetLead
  };

  showLoading("Saving Policy Rule...", `Configuring rule ${name}...`);
  try {
    const res = await fetch("/api/policies", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        policy_id: policyId,
        name: name,
        priority: priority,
        description: desc,
        conditions: conditions,
        actions: actions,
        is_active: 1
      })
    });
    hideLoading();
    if (!res.ok) {
      const errData = await res.json();
      throw new Error(errData.error || "Failed to save policy rule");
    }
    showToast(`Policy rule '${name}' saved successfully`);
    togglePolicyForm(false);
    await loadPolicyRules();
    currentSimulationDiff = null;
  } catch (err) {
    hideLoading();
    showToast("Error saving policy: " + err.message, "error");
  }
}

async function deletePolicyRule(policyId) {
  if (!confirm("Are you sure you want to delete this policy rule?")) return;
  showLoading("Deleting Policy Rule...", "Removing rule from database...");
  try {
    const res = await fetch(`/api/policies/${encodeURIComponent(policyId)}`, {
      method: "DELETE"
    });
    hideLoading();
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || "Failed to delete policy rule");
    }
    showToast("Policy rule removed");
    await loadPolicyRules();
    currentSimulationDiff = null;
  } catch (err) {
    hideLoading();
    showToast("Error deleting rule: " + err.message, "error");
  }
}

async function runPolicySimulation() {
  const tbody = document.getElementById("sim-diff-tbody");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="6" style="padding: 24px; text-align: center; color: var(--text-muted);">Evaluating portfolio against prioritized policy rules...</td></tr>`;

  try {
    const res = await fetch("/api/policies/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    });
    if (!res.ok) throw new Error("Simulation request failed");
    const data = await res.json();
    currentSimulationDiff = data.simulation || { results: [], summary: {} };

    const summary = currentSimulationDiff.summary || {};
    document.getElementById("sim-stat-total").textContent = summary.total_apps || 0;
    document.getElementById("sim-stat-matched").textContent = summary.matched_apps || 0;
    document.getElementById("sim-stat-changed").textContent = summary.changed_apps || 0;

    renderSimulationDiffTable(currentSimulationDiff.results || []);
    updateApplyCount();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="padding: 24px; text-align: center; color: #EF4444;">Simulation error: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function renderSimulationDiffTable(results) {
  const tbody = document.getElementById("sim-diff-tbody");
  if (!tbody) return;

  if (results.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="padding: 24px; text-align: center; color: var(--text-muted);">No applications found in active inventory.</td></tr>`;
    return;
  }

  const waveColors = {
    wave1: { bg: "#D1FAE5", text: "#065F46", label: "Wave 1: Quick Wins" },
    wave2: { bg: "#EEF2FF", text: "#3730A3", label: "Wave 2: Core Governed" },
    wave3: { bg: "#FEF3C7", text: "#92400E", label: "Wave 3: Complex Multi-Fact" },
    decommissioned: { bg: "#FEE2E2", text: "#991B1B", label: "Decommissioned" },
    unassigned: { bg: "#F1F5F9", text: "#475569", label: "Backlog" }
  };

  tbody.innerHTML = results.map(r => {
    const isWaveChanged = r.proposed_wave !== r.current_wave;
    const isLeadChanged = r.proposed_lead !== r.current_lead;
    const hasAnyChange = r.has_changes;

    const currWaveInfo = waveColors[r.current_wave] || { bg: "#F1F5F9", text: "#475569", label: r.current_wave };
    const propWaveInfo = waveColors[r.proposed_wave] || { bg: "#F1F5F9", text: "#475569", label: r.proposed_wave };

    const waveDiffHtml = isWaveChanged
      ? `<div style="display: flex; align-items: center; gap: 6px;">
           <span class="badge" style="background: ${currWaveInfo.bg}; color: ${currWaveInfo.text}; font-size: 10px;">${escapeHtml(currWaveInfo.label)}</span>
           <span style="font-weight: bold; color: #10B981;">→</span>
           <span class="badge" style="background: ${propWaveInfo.bg}; color: ${propWaveInfo.text}; font-size: 10px; font-weight: 700; border: 1px solid ${propWaveInfo.text};">${escapeHtml(propWaveInfo.label)}</span>
         </div>`
      : `<span class="badge" style="background: ${currWaveInfo.bg}; color: ${currWaveInfo.text}; font-size: 10px;">${escapeHtml(currWaveInfo.label)} (Unchanged)</span>`;

    const leadDiffHtml = isLeadChanged
      ? `<div style="display: flex; align-items: center; gap: 6px;">
           <span style="color: var(--text-muted); font-size: 11px;">${escapeHtml(r.current_lead)}</span>
           <span style="font-weight: bold; color: #10B981;">→</span>
           <span style="color: var(--primary); font-weight: 700; font-size: 11px;">${escapeHtml(r.proposed_lead)}</span>
         </div>`
      : `<span style="color: var(--text-muted); font-size: 11px;">${escapeHtml(r.current_lead)}</span>`;

    return `
      <tr style="border-bottom: 1px solid var(--border-subtle); background: ${hasAnyChange ? 'rgba(79, 70, 229, 0.02)' : 'transparent'};">
        <td style="padding: 10px 12px; text-align: center;">
          <input type="checkbox" class="sim-app-checkbox" data-appid="${escapeHtml(r.app_id)}" data-wave="${escapeHtml(r.proposed_wave)}" data-lead="${escapeHtml(r.proposed_lead)}" ${hasAnyChange ? 'checked' : ''} onchange="updateApplyCount()">
        </td>
        <td style="padding: 10px 12px;">
          <div style="font-weight: 600; color: var(--text-primary);">${escapeHtml(r.app_name)}</div>
          <div style="font-size: 11px; color: var(--text-muted);">${r.sheet_count} sheets · ${r.widget_count} widgets</div>
        </td>
        <td style="padding: 10px 12px;">
          <span class="badge" style="background: var(--bg-subtle); color: var(--text-secondary); font-size: 10px;">${escapeHtml(r.stream_or_space)}</span>
        </td>
        <td style="padding: 10px 12px;">${waveDiffHtml}</td>
        <td style="padding: 10px 12px;">${leadDiffHtml}</td>
        <td style="padding: 10px 12px;">
          <span style="font-size: 11px; color: var(--text-secondary); font-weight: 500;">${escapeHtml(r.matched_policy_name)}</span>
        </td>
      </tr>
    `;
  }).join("");
}

function toggleSelectAllSimulation(isChecked) {
  const checkboxes = document.querySelectorAll(".sim-app-checkbox");
  checkboxes.forEach(cb => cb.checked = isChecked);
  updateApplyCount();
}

function updateApplyCount() {
  const checkboxes = document.querySelectorAll(".sim-app-checkbox:checked");
  const countEl = document.getElementById("apply-selected-count");
  if (countEl) countEl.textContent = checkboxes.length;
}

async function commitPolicyAssignments() {
  const checkboxes = document.querySelectorAll(".sim-app-checkbox:checked");
  if (checkboxes.length === 0) {
    showToast("No applications selected for assignment", "error");
    return;
  }

  const assignments = Array.from(checkboxes).map(cb => ({
    app_id: cb.dataset.appid,
    wave: cb.dataset.wave,
    lead: cb.dataset.lead
  }));

  showLoading("Committing Policy Assignments...", `Updating wave & lead assignments for ${assignments.length} applications...`);
  try {
    const res = await fetch("/api/policies/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ assignments: assignments })
    });
    hideLoading();
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || "Failed to apply policy assignments");
    }

    showToast(`Successfully applied wave & lead policy to ${assignments.length} application(s)!`);
    closePolicyWizardModal();

    // Refresh all views
    loadWavesData();
    loadExecutiveMetrics();
    loadCatalog();
  } catch (err) {
    hideLoading();
    showToast("Error applying policy assignments: " + err.message, "error");
  }
}

async function batchAssignWaveForCluster(appIds, wave) {
  try {
    const res = await fetch("/api/waves/assign", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app_ids: appIds, wave: wave })
    });
    if (res.ok) {
      showToast(`Assigned ${appIds.length} cluster apps to ${wave.toUpperCase()}`);
      loadExecutiveMetrics();
      loadWavesData();
      loadCatalog();
    }
  } catch (err) {
    console.error("Failed to assign cluster wave:", err);
  }
}

/* ==========================================================================
   Batch Operations & Multi-Select Controller
   ========================================================================== */
function toggleSelectApp(appId, isChecked) {
  if (isChecked) {
    selectedAppIds.add(appId);
  } else {
    selectedAppIds.delete(appId);
  }
  updateBatchBar();
}

function toggleSelectAllApps(isChecked) {
  const checkboxes = document.querySelectorAll(".app-row-checkbox");
  checkboxes.forEach(cb => {
    cb.checked = isChecked;
    if (isChecked) {
      selectedAppIds.add(cb.value);
    } else {
      selectedAppIds.delete(cb.value);
    }
  });
  updateBatchBar();
}

function deselectAllApps() {
  selectedAppIds.clear();
  const checkboxes = document.querySelectorAll(".app-row-checkbox");
  checkboxes.forEach(cb => { cb.checked = false; });
  const selectAllCb = document.getElementById("catalog-select-all");
  if (selectAllCb) selectAllCb.checked = false;
  updateBatchBar();
}

function updateBatchBar() {
  const bar = document.getElementById("batch-actions-bar");
  const countEl = document.getElementById("batch-selected-count");
  const count = selectedAppIds.size;

  if (countEl) countEl.textContent = count;
  if (bar) {
    if (count > 0) {
      bar.classList.add("active");
    } else {
      bar.classList.remove("active");
    }
  }
}

async function batchExtractSelectedApps() {
  const appIds = Array.from(selectedAppIds);
  if (appIds.length === 0) return;

  showLoading(`Extracting ${appIds.length} Applications...`, "Compiling Canonical IR and auditing 3-tier compatibility in parallel...");
  try {
    const res = await fetch("/api/apps/batch_extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app_ids: appIds })
    });
    hideLoading();
    if (res.ok) {
      const data = await res.json();
      showToast(`Compiled Canonical IR for ${data.extracted_count} applications`);
      deselectAllApps();
      loadCatalog();
      loadExecutiveMetrics();
      loadWavesData();
    } else {
      throw new Error("Batch extract failed");
    }
  } catch (err) {
    hideLoading();
    console.error("Batch extract failed:", err);
    showToast("Batch extract failed: " + err.message, "error");
  }
}

async function batchAssignWave(wave) {
  const appIds = Array.from(selectedAppIds);
  if (appIds.length === 0) return;

  try {
    const res = await fetch("/api/waves/assign", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app_ids: appIds, wave: wave })
    });
    if (res.ok) {
      showToast(`Assigned ${appIds.length} application(s) to ${wave.toUpperCase()}`);
      deselectAllApps();
      loadCatalog();
      loadWavesData();
      loadExecutiveMetrics();
    }
  } catch (err) {
    console.error("Batch assign wave failed:", err);
  }
}

async function batchDecommissionSelected(decommissioned) {
  const appIds = Array.from(selectedAppIds);
  if (appIds.length === 0) return;

  try {
    const res = await fetch("/api/apps/decommission", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app_ids: appIds, decommissioned: decommissioned })
    });
    if (res.ok) {
      showToast(`Updated decommission status for ${appIds.length} application(s)`);
      deselectAllApps();
      loadCatalog();
      loadWavesData();
      loadExecutiveMetrics();
    }
  } catch (err) {
    console.error("Batch decommission failed:", err);
  }
}

// --- Register / Add Qlik Application Handlers ---

function openRegisterAppModal(defaultName = "", defaultId = "") {
  const modal = document.getElementById("modal-register-app");
  if (!modal) return;
  const nameInput = document.getElementById("reg-app-name");
  const idInput = document.getElementById("reg-app-id");
  if (nameInput) nameInput.value = defaultName;
  if (idInput) idInput.value = defaultId;
  modal.style.display = "flex";
}

function closeRegisterAppModal() {
  const modal = document.getElementById("modal-register-app");
  if (modal) modal.style.display = "none";
}

async function submitRegisterApp() {
  const nameInput = document.getElementById("reg-app-name");
  const idInput = document.getElementById("reg-app-id");
  const spaceInput = document.getElementById("reg-app-space");
  const spaceTypeSelect = document.getElementById("reg-app-space-type");
  const btn = document.getElementById("btn-submit-register-app");

  const name = (nameInput?.value || "").trim();
  const rawId = (idInput?.value || "").trim();
  const space = (spaceInput?.value || "Personal").trim();
  const spaceType = spaceTypeSelect?.value || "personal";

  if (!name) {
    showToast("Please enter an application name.", "error");
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.textContent = "⏳ Registering & Compiling...";
  }
  showLoading(`Registering '${name}'...`, "Synthesizing and compiling Canonical Intermediate Representation...");

  try {
    const targetInstId = (activeInstance && activeInstance.tenant_id) ? activeInstance.tenant_id : "";
    if (!targetInstId) { alert("Please select an active Qlik instance first."); return; }
    const res = await fetch("/api/apps/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name,
        app_id: rawId,
        stream_or_space: space,
        space_type: spaceType,
        tenant_id: targetInstId
      })
    });

    const data = await res.json();
    if (res.ok && data.status === "SUCCESS") {
      closeRegisterAppModal();
      await loadCatalog();
      await loadWavesData();
      await loadExecutiveMetrics();
      showToast(`App '${name}' registered and compiled successfully!`);
      const registeredAppId = (data.app && data.app.app_id) || rawId;
      if (registeredAppId) {
        loadApp(registeredAppId);
      }
    } else {
      showToast(data.error || "Failed to register application.", "error");
    }
  } catch (err) {
    console.error("Registration error:", err);
    showToast(`Registration error: ${err.message}`, "error");
  } finally {
    hideLoading();
    if (btn) {
      btn.disabled = false;
      btn.textContent = "🚀 Register & Compile IR";
    }
  }
}

/* ==========================================================================
   Migration Leads & Engineering Roster Controller
   ========================================================================== */

async function loadLeads() {
  try {
    const res = await fetch("/api/leads");
    if (!res.ok) return;
    const data = await res.json();
    cachedLeads = data.leads || [];
    updateLeadFilterDropdown();
    updateBatchLeadDropdown();
  } catch (err) {
    console.error("Failed to load leads roster:", err);
  }
}

function updateLeadFilterDropdown() {
  const select = document.getElementById("wave-filter-lead");
  if (!select) return;
  const currentVal = select.value || "all";
  let html = `<option value="all">All Migration Leads</option>`;
  cachedLeads.forEach(l => {
    const isSel = currentVal === l.name ? "selected" : "";
    const isAI = l.name.toLowerCase().includes("ai ") || l.name.toLowerCase().includes("agent") || (l.role || "").toLowerCase().includes("agent") || (l.role || "").toLowerCase().includes("runner");
    const icon = isAI ? "🤖 " : "👤 ";
    html += `<option value="${escapeHtml(l.name)}" ${isSel}>${icon}${escapeHtml(l.name)} (${escapeHtml(l.role)})</option>`;
  });
  html += `<option value="Unassigned" ${currentVal === "Unassigned" ? "selected" : ""}>Unassigned</option>`;
  select.innerHTML = html;
}

function updateBatchLeadDropdown() {
  const select = document.getElementById("batch-assign-lead-select");
  if (!select) return;
  let html = `<option value="" style="color: #1F2937; background: #FFF;">👤 Assign Lead...</option>`;
  cachedLeads.forEach(l => {
    const isAI = l.name.toLowerCase().includes("ai ") || l.name.toLowerCase().includes("agent") || (l.role || "").toLowerCase().includes("agent") || (l.role || "").toLowerCase().includes("runner");
    const icon = isAI ? "🤖 " : "👤 ";
    html += `<option value="${escapeHtml(l.name)}" style="color: #1F2937; background: #FFF;">${icon}${escapeHtml(l.name)}</option>`;
  });
  html += `<option value="Unassigned" style="color: #1F2937; background: #FFF;">Unassigned</option>`;
  select.innerHTML = html;
}

async function openManageLeadsModal() {
  const modal = document.getElementById("modal-manage-leads");
  if (!modal) return;
  modal.style.display = "flex";
  await renderLeadsRosterTable();
}

function closeManageLeadsModal() {
  const modal = document.getElementById("modal-manage-leads");
  if (modal) modal.style.display = "none";
}

async function renderLeadsRosterTable() {
  const tbody = document.getElementById("leads-roster-tbody");
  const totalEl = document.getElementById("roster-total-count");
  if (!tbody) return;

  try {
    const res = await fetch("/api/leads");
    if (!res.ok) throw new Error("Failed to fetch leads");
    const data = await res.json();
    cachedLeads = data.leads || [];
    if (totalEl) totalEl.textContent = `${cachedLeads.length} team members`;

    if (cachedLeads.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" style="padding: 16px; text-align: center; color: var(--text-muted);">No team members in roster yet. Add one below!</td></tr>`;
      return;
    }

    tbody.innerHTML = cachedLeads.map(lead => {
      const isAI = lead.name.toLowerCase().includes("ai ") || lead.name.toLowerCase().includes("agent") || (lead.role || "").toLowerCase().includes("agent") || (lead.role || "").toLowerCase().includes("runner");
      const avatarIcon = isAI ? "🤖" : "👤";
      const roleBadgeBg = isAI ? "#F3E8FF" : "#EFF6FF";
      const roleBadgeColor = isAI ? "#7E22CE" : "#1D4ED8";
      const activeApps = lead.active_apps_count || 0;
      const emailDisplay = lead.email ? `<a href="mailto:${escapeHtml(lead.email)}" style="color: var(--primary); text-decoration: none;">${escapeHtml(lead.email)}</a>` : '<span style="color: var(--text-muted);">—</span>';

      return `
        <tr style="border-bottom: 1px solid var(--border-subtle);">
          <td style="padding: 10px 14px; font-weight: 600; color: var(--text-primary);">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 16px;">${avatarIcon}</span>
              <span>${escapeHtml(lead.name)}</span>
            </div>
          </td>
          <td style="padding: 10px 14px;">
            <span class="badge" style="background: ${roleBadgeBg}; color: ${roleBadgeColor}; font-size: 11px; font-weight: 600; margin-bottom: 2px;">${escapeHtml(lead.role)}</span>
            ${lead.specialty ? `<div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">${escapeHtml(lead.specialty)}</div>` : ''}
          </td>
          <td style="padding: 10px 14px; font-size: 12px;">${emailDisplay}</td>
          <td style="padding: 10px 14px; text-align: center;">
            <span class="badge" style="background: ${activeApps > 0 ? '#ECFDF5' : '#F8FAFC'}; color: ${activeApps > 0 ? '#065F46' : '#64748B'}; font-weight: 600;">
              ${activeApps} apps
            </span>
          </td>
          <td style="padding: 10px 14px; text-align: right;">
            <button class="btn-secondary" style="font-size: 11px; padding: 4px 8px; color: #EF4444; border-color: rgba(239,68,68,0.3); cursor: pointer;" onclick="deleteLead('${escapeHtml(lead.lead_id)}', '${escapeHtml(lead.name)}')">
              🗑 Remove
            </button>
          </td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" style="padding: 16px; text-align: center; color: #EF4444;">Failed to load leads: ${escapeHtml(err.message)}</td></tr>`;
  }
}

async function submitCreateLead() {
  const nameInput = document.getElementById("new-lead-name");
  const roleInput = document.getElementById("new-lead-role");
  const specialtyInput = document.getElementById("new-lead-specialty");
  const emailInput = document.getElementById("new-lead-email");

  const name = nameInput?.value?.trim();
  if (!name) {
    showToast("Please enter a name for the lead", "error");
    return;
  }

  showLoading("Adding to Roster...", `Registering ${name}...`);
  try {
    const res = await fetch("/api/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name,
        role: roleInput?.value || "Migration Lead",
        specialty: specialtyInput?.value?.trim() || null,
        email: emailInput?.value?.trim() || null
      })
    });

    hideLoading();
    if (!res.ok) {
      const errData = await res.json();
      throw new Error(errData.error || "Failed to add lead");
    }

    showToast(`Added ${name} to migration roster`);
    if (nameInput) nameInput.value = "";
    if (specialtyInput) specialtyInput.value = "";
    if (emailInput) emailInput.value = "";

    await loadLeads();
    await renderLeadsRosterTable();
    loadWavesData();
    loadCatalog();
  } catch (err) {
    hideLoading();
    showToast("Error creating lead: " + err.message, "error");
  }
}

async function deleteLead(leadId, leadName) {
  if (!confirm(`Are you sure you want to remove ${leadName} from the roster? Any applications assigned to them will be marked as Unassigned.`)) {
    return;
  }

  showLoading("Removing Lead...", `Removing ${leadName} and updating assigned apps...`);
  try {
    const res = await fetch(`/api/leads/${encodeURIComponent(leadId)}`, {
      method: "DELETE"
    });

    hideLoading();
    if (!res.ok) {
      const errData = await res.json();
      throw new Error(errData.error || "Failed to delete lead");
    }

    showToast(`Removed ${leadName} from roster`);
    await loadLeads();
    await renderLeadsRosterTable();
    loadWavesData();
    loadCatalog();
  } catch (err) {
    hideLoading();
    showToast("Error deleting lead: " + err.message, "error");
  }
}

async function batchAssignLeadFromDropdown(leadName) {
  if (!leadName) return;
  const appIds = Array.from(selectedAppIds);
  if (appIds.length === 0) {
    showToast("No applications selected in catalog", "error");
    return;
  }

  try {
    const res = await fetch("/api/waves/assign", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app_ids: appIds, lead: leadName })
    });
    if (res.ok) {
      showToast(`Assigned ${appIds.length} app(s) to ${leadName}`);
      const sel = document.getElementById("batch-assign-lead-select");
      if (sel) sel.value = "";
      deselectAllApps();
      loadCatalog();
      loadWavesData();
      loadExecutiveMetrics();
    }
  } catch (err) {
    console.error("Failed to batch assign lead:", err);
    showToast("Failed to assign lead: " + err.message, "error");
  }
}

// ============================================================================
// Stage 1.5: OKF v0.2 Semantic Catalog & Explore Consolidation Controller
// ============================================================================
let currentOKFCatalog = null;
let selectedOKFConceptPath = null;
let selectedOKFConceptSha256 = null;

async function loadOKFCatalog() {
  try {
    const res = await fetch("/api/okf/catalog");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    currentOKFCatalog = data;

    const counts = data.counts || {};
    const expEl = document.getElementById("okf-stat-explores");
    const tblEl = document.getElementById("okf-stat-tables");
    const metEl = document.getElementById("okf-stat-metrics");
    const appEl = document.getElementById("okf-stat-apps");
    const pillEl = document.getElementById("okf-total-files-pill");
    const badgeEl = document.getElementById("okf-conformance-badge");

    if (expEl) expEl.textContent = counts.explores || 0;
    if (tblEl) tblEl.textContent = counts.tables || 0;
    if (metEl) metEl.textContent = counts.metrics || 0;
    if (appEl) appEl.textContent = counts.apps || 0;
    if (pillEl) pillEl.textContent = `${counts.total_files || 0} files`;

    if (badgeEl) {
      if (data.is_valid) {
        badgeEl.textContent = "✔ OKF v0.2 VALID (Zero-Drift Synced)";
        badgeEl.style.background = "#ECFDF5";
        badgeEl.style.color = "#059669";
      } else {
        badgeEl.textContent = `⚠ ${data.validation_errors?.length || 1} Conformance Warning(s)`;
        badgeEl.style.background = "#FEF3C7";
        badgeEl.style.color = "#D97706";
      }
    }

    renderOKFConceptTree(data.concepts || {});

    if (!selectedOKFConceptPath) {
      const firstExplore = data.concepts?.explores?.[0]?.concept_path;
      const firstTable = data.concepts?.tables?.[0]?.concept_path;
      const firstApp = data.concepts?.apps?.[0]?.concept_path;
      selectOKFConcept(firstExplore || firstTable || firstApp || "index.md");
    } else {
      selectOKFConcept(selectedOKFConceptPath);
    }
  } catch (err) {
    console.error("Failed to load OKF catalog:", err);
  }
}

function renderOKFConceptTree(concepts, filterText = "") {
  const container = document.getElementById("okf-concept-tree-list");
  if (!container) return;

  const q = (filterText || "").toLowerCase().trim();
  const sections = [
    { key: "explores", label: "🧭 Canonical Explores (explores/)", icon: "🧭", badgeColor: "#7E22CE", badgeBg: "#F3E8FF" },
    { key: "tables", label: "🗄️ Deduplicated Tables (tables/)", icon: "🗄️", badgeColor: "#1D4ED8", badgeBg: "#EFF6FF" },
    { key: "metrics", label: "📐 Shared Metrics (metrics/)", icon: "📐", badgeColor: "#0284C7", badgeBg: "#E0F2FE" },
    { key: "apps", label: "📊 Qlik App Catalogs (apps/)", icon: "📊", badgeColor: "#059669", badgeBg: "#ECFDF5" },
    { key: "system", label: "📑 Bundle Root & Audit Log", icon: "📑", badgeColor: "#475569", badgeBg: "#F1F5F9" },
  ];

  let html = "";
  sections.forEach(sec => {
    const items = (concepts[sec.key] || []).filter(item => {
      if (!q) return true;
      return (item.concept_path || "").toLowerCase().includes(q) || (item.title || "").toLowerCase().includes(q);
    });

    html += `
      <div style="border-bottom: 1px solid var(--border-subtle); padding-bottom: 8px;">
        <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; font-weight: 700; color: var(--text-secondary); text-transform: uppercase; margin-bottom: 6px;">
          <span>${sec.label}</span>
          <span class="badge" style="background: ${sec.badgeBg}; color: ${sec.badgeColor}; font-size: 10px;">${items.length}</span>
        </div>
    `;

    if (items.length === 0) {
      html += `<div style="font-size: 11px; color: var(--text-muted); padding: 4px 8px;">No files</div>`;
    } else {
      items.forEach(item => {
        const isSel = item.concept_path === selectedOKFConceptPath;
        const refCount = item.extracted?.referenced_by_apps?.length || item.extracted?.source_app_count || "";
        const refPill = refCount ? `<span class="mini-pill cat1" title="Referenced across ${refCount} app(s)">${refCount} apps</span>` : "";
        html += `
          <button type="button" class="sheet-item ${isSel ? 'selected' : ''}" onclick="selectOKFConcept('${escapeHtml(item.concept_path)}')" style="width: 100%; margin-bottom: 4px; padding: 8px 10px;">
            <div style="display: flex; justify-content: space-between; align-items: center; gap: 6px; width: 100%;">
              <span class="sheet-item-title" style="font-size: 12px;">${sec.icon} ${escapeHtml(item.title || item.concept_path)}</span>
              ${refPill}
            </div>
            <div style="font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); margin-top: 2px;">
              ${escapeHtml(item.concept_path)}
            </div>
          </button>
        `;
      });
    }
    html += `</div>`;
  });

  container.innerHTML = html;
}

function filterOKFTree(val) {
  if (!currentOKFCatalog) return;
  renderOKFConceptTree(currentOKFCatalog.concepts || {}, val);
}

async function selectOKFConcept(conceptPath) {
  selectedOKFConceptPath = conceptPath;
  if (currentOKFCatalog) {
    const searchVal = document.getElementById("okf-tree-search")?.value || "";
    renderOKFConceptTree(currentOKFCatalog.concepts || {}, searchVal);
  }

  try {
    const res = await fetch(`/api/okf/concept?path=${encodeURIComponent(conceptPath)}`);
    if (!res.ok) return;
    const data = await res.json();
    const c = data.concept;
    if (!c) return;

    selectedOKFConceptSha256 = c.content_sha256;
    const pathEl = document.getElementById("okf-doc-path");
    const typeEl = document.getElementById("okf-doc-type-badge");
    const shaEl = document.getElementById("okf-doc-sha");
    const extEl = document.getElementById("okf-extracted-json-view");
    const govEl = document.getElementById("okf-governance-json-editor");
    const notesEl = document.getElementById("okf-curated-notes-editor");
    const rawEl = document.getElementById("okf-raw-markdown-preview");

    if (pathEl) pathEl.textContent = `okf_catalog/${c.concept_path}`;
    if (typeEl) typeEl.textContent = `type: ${c.concept_type}`;
    if (shaEl) shaEl.textContent = `SHA-256 Lock: ${c.content_sha256} · Updated: ${c.updated_at || "just now"}`;
    if (extEl) extEl.textContent = JSON.stringify(c.extracted || {}, null, 2);
    if (govEl) govEl.value = JSON.stringify(c.governance || {}, null, 2);
    if (notesEl) notesEl.value = c.curated_notes || "";
    if (rawEl) rawEl.textContent = c.raw_markdown || "";
  } catch (err) {
    console.error("Failed to fetch OKF concept:", err);
  }
}

async function saveCurrentOKFConcept() {
  if (!selectedOKFConceptPath) return;
  const govEl = document.getElementById("okf-governance-json-editor");
  const notesEl = document.getElementById("okf-curated-notes-editor");

  let parsedGov = {};
  try {
    parsedGov = JSON.parse(govEl.value || "{}");
  } catch (e) {
    showToast("Invalid JSON in governance: namespace editor", "error");
    return;
  }

  try {
    const res = await fetch("/api/okf/concept", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        concept_path: selectedOKFConceptPath,
        governance: parsedGov,
        curated_notes: notesEl.value,
        expected_sha256: selectedOKFConceptSha256,
      })
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || "Failed to save OKF concept");
    }
    showToast(`Saved & write-through indexed okf_catalog/${selectedOKFConceptPath}`);
    await loadOKFCatalog();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function runStage15FleetReconciliation() {
  showLoading("Running Stage 1.5 Fleet Reconciliation...", "Deduplicating tables, synthesizing Canonical Looker Explores (explores/*.md), and calculating Category 2 effort savings...");
  try {
    const res = await fetch("/api/okf/reconcile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ similarity_threshold: 0.45 })
    });
    const data = await res.json();
    hideLoading();
    if (!res.ok) {
      throw new Error(data.error || "Reconciliation failed");
    }

    const rec = data.reconciliation || {};
    const savEl = document.getElementById("okf-stat-savings");
    const savSubEl = document.getElementById("okf-stat-savings-sub");
    if (savEl) savEl.textContent = `${rec.saved_cat2_effort_hours || 0} hrs saved`;
    if (savSubEl) savSubEl.textContent = `${rec.raw_cat2_effort_hours || 0}h raw → ${rec.deduplicated_cat2_effort_hours || 0}h net`;

    const banner = document.getElementById("okf-reconcile-banner");
    if (banner) {
      banner.style.display = "block";
      banner.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
          <div>
            <div style="font-weight: 700; font-size: 14px; color: #581C87;">
              ✔ Stage 1.5 Fleet Reconciliation Complete: ${rec.total_apps_reconciled || 0} Qlik App(s) Consolidated into ${rec.canonical_explores_count || 0} Canonical Looker Explore(s)
            </div>
            <div style="font-size: 12px; color: #6B21A8; margin-top: 2px;">
              Eliminated <strong>${rec.duplicate_explores_eliminated || 0}</strong> duplicate LookML Explore(s) (<strong>${rec.explore_reduction_pct || 0}%</strong> model reduction) · Deduplicated Category 2 modeling effort by <strong>${rec.saved_cat2_effort_hours || 0} hours</strong>.
            </div>
          </div>
          <span class="badge" style="background: #7E22CE; color: #FFFFFF; font-weight: 700; padding: 6px 12px;">OKF v0.2 Written to Disk</span>
        </div>
      `;
    }

    showToast(`Synthesized ${rec.canonical_explores_count || 0} Canonical Looker Explores in okf_catalog/explores/`);
    selectedOKFConceptPath = rec.canonical_explores?.[0]?.explore_path || null;
    await loadOKFCatalog();
  } catch (err) {
    hideLoading();
    showToast(err.message, "error");
  }
}

async function compileEntireOKFFleetToLookML() {
  showLoading("Compiling Fleet OKF Catalog to LookML...", "Synthesizing shared Views, Canonical Explores, re-bound Dashboards, and dbt models from okf_catalog/...");
  try {
    const modelName = document.getElementById("target-model-input")?.value || "enterprise_analytics";
    const res = await fetch("/api/okf/compile-fleet", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_name: modelName })
    });
    const data = await res.json();
    hideLoading();
    if (!res.ok) {
      throw new Error(data.error || "Fleet LookML compilation failed");
    }
    currentArtifacts = data.artifacts;
    switchTab("tab-lookml");
    renderLookMLPreview(activeLookMLType);
    showToast(`Compiled ${data.artifacts?.metadata?.total_canonical_explores || 0} Canonical Explore(s) and ${data.artifacts?.metadata?.total_views || 0} Shared View(s)`);
  } catch (err) {
    hideLoading();
    showToast(err.message, "error");
  }
}



