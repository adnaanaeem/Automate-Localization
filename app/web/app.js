let scanResult = null;
let selectedKeys = new Set();
let langDisplayToCode = {};
let newLangOptions = [];
let selectedNewLangs = new Set();

function api() {
  return window.pywebview.api;
}

function showScreen(name) {
  document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
  document.getElementById("screen-" + name).classList.add("active");
  document.querySelectorAll(".step").forEach(s => {
    s.classList.remove("active", "done");
    const order = ["setup", "review", "progress", "results"];
    const idx = order.indexOf(name);
    const sIdx = order.indexOf(s.dataset.step);
    if (sIdx === idx) s.classList.add("active");
    else if (sIdx < idx) s.classList.add("done");
  });
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

// --- Setup screen ------------------------------------------------------

async function loadSettings() {
  const s = await api().get_settings();

  const recentDiv = document.getElementById("recent-paths");
  recentDiv.innerHTML = "";
  (s.recent_paths || []).forEach(p => {
    const chip = document.createElement("span");
    chip.className = "recent-path-chip";
    chip.textContent = p;
    chip.onclick = () => { document.getElementById("path-input").value = p; };
    recentDiv.appendChild(chip);
  });

  document.querySelector(`input[name="provider"][value="${s.last_provider}"]`).checked = true;
  updateProviderVisibility();

  setKeyStatus("gemini", s.has_gemini_key);
  setKeyStatus("openai", s.has_openai_key);

  document.getElementById("sheet-sync-toggle").checked = !!s.sheet_sync_enabled;
  document.getElementById("sheet-id-input").value = s.google_sheet_id || "";
  document.getElementById("service-account-input").value = s.service_account_path || "";
  updateSheetFieldsVisibility();

  document.getElementById("batch-size-input").value = s.batch_size || 25;
  document.getElementById("max-retries-input").value = s.max_retries != null ? s.max_retries : 10;
}

async function loadLanguagePicker() {
  newLangOptions = await api().get_language_options();
  selectedNewLangs = new Set(newLangOptions.filter(o => o.legacy_default).map(o => o.code));
  renderLangPicker("");
}

function setLangSelected(code, isSelected) {
  if (isSelected) selectedNewLangs.add(code);
  else selectedNewLangs.delete(code);
  renderSelectedLangChips();
  const cb = document.querySelector(`#lang-picker input[data-code="${CSS.escape(code)}"]`);
  if (cb) cb.checked = isSelected;
}

function renderLangPicker(filterText) {
  const container = document.getElementById("lang-picker");
  const q = filterText.trim().toLowerCase();
  container.innerHTML = "";
  newLangOptions.forEach(opt => {
    const matches = !q || opt.display_name.toLowerCase().includes(q) || opt.code.toLowerCase().includes(q);
    if (!matches) return;
    const label = document.createElement("label");
    label.className = "lang-chip";
    label.innerHTML = `
      <input type="checkbox" data-code="${escapeHtml(opt.code)}" ${selectedNewLangs.has(opt.code) ? "checked" : ""} />
      <span class="lang-flag">${opt.flag}</span>
      <span>${escapeHtml(opt.display_name)}</span>
      <span class="lang-code">${escapeHtml(opt.code)}</span>
    `;
    label.querySelector("input").addEventListener("change", (e) => {
      setLangSelected(opt.code, e.target.checked);
    });
    container.appendChild(label);
  });
  renderSelectedLangChips();
}

function renderSelectedLangChips() {
  const el = document.getElementById("lang-selected-list");
  if (!el) return;
  el.innerHTML = "";
  if (selectedNewLangs.size === 0) {
    el.innerHTML = `<span class="lang-selected-empty">None selected.</span>`;
    return;
  }
  Array.from(selectedNewLangs).forEach(code => {
    const opt = newLangOptions.find(o => o.code === code);
    const chip = document.createElement("span");
    chip.className = "selected-lang-chip";
    chip.innerHTML = `
      <span class="lang-flag">${opt ? opt.flag : "🌐"}</span>
      <span>${escapeHtml(opt ? opt.display_name : code)}</span>
      <span class="remove-x" title="Remove">×</span>
    `;
    chip.querySelector(".remove-x").addEventListener("click", () => setLangSelected(code, false));
    el.appendChild(chip);
  });
}

function setKeyStatus(provider, hasKey) {
  const el = document.getElementById(provider + "-key-status");
  el.textContent = hasKey ? "● key set" : "○ not set";
  el.className = "key-status " + (hasKey ? "set" : "unset");
}

function updateProviderVisibility() {
  const provider = document.querySelector('input[name="provider"]:checked').value;
  document.getElementById("provider-gemini").classList.toggle("hidden", provider !== "gemini");
  document.getElementById("provider-openai").classList.toggle("hidden", provider !== "openai");
}

function updateSheetFieldsVisibility() {
  const on = document.getElementById("sheet-sync-toggle").checked;
  document.getElementById("sheet-fields").classList.toggle("hidden", !on);
}

async function persistSettings() {
  const provider = document.querySelector('input[name="provider"]:checked').value;
  await api().save_settings({
    last_provider: provider,
    batch_size: parseInt(document.getElementById("batch-size-input").value, 10) || 25,
    max_retries: parseInt(document.getElementById("max-retries-input").value, 10) || 0,
    sheet_sync_enabled: document.getElementById("sheet-sync-toggle").checked,
    google_sheet_id: document.getElementById("sheet-id-input").value.trim(),
    service_account_path: document.getElementById("service-account-input").value.trim(),
  });
}

function wireSetupScreen() {
  document.querySelectorAll('input[name="provider"]').forEach(r => {
    r.addEventListener("change", () => { updateProviderVisibility(); persistSettings(); });
  });
  document.getElementById("sheet-sync-toggle").addEventListener("change", () => {
    updateSheetFieldsVisibility(); persistSettings();
  });
  ["sheet-id-input", "service-account-input", "batch-size-input", "max-retries-input"].forEach(id => {
    document.getElementById(id).addEventListener("change", persistSettings);
  });

  document.getElementById("browse-btn").addEventListener("click", async () => {
    const res = await api().choose_strings_file();
    if (res.ok) {
      document.getElementById("path-input").value = res.path;
      document.getElementById("path-error").textContent = "";
    } else if (res.error) {
      document.getElementById("path-error").textContent = res.error;
    }
  });

  document.getElementById("sa-browse-btn").addEventListener("click", async () => {
    const res = await api().choose_service_account_file();
    if (res.ok) {
      document.getElementById("service-account-input").value = res.path;
      persistSettings();
    }
  });

  document.querySelectorAll("[data-save-key]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const provider = btn.dataset.saveKey;
      const input = document.getElementById(provider + "-key-input");
      const val = input.value.trim();
      if (!val) return;
      await api().set_api_key(provider, val);
      input.value = "";
      setKeyStatus(provider, true);
    });
  });

  document.getElementById("scan-btn").addEventListener("click", doScan);

  document.getElementById("lang-filter-input").addEventListener("input", (e) => {
    renderLangPicker(e.target.value);
  });
}

async function doScan() {
  const path = document.getElementById("path-input").value.trim();
  const errEl = document.getElementById("path-error");
  const statusEl = document.getElementById("scan-status");
  errEl.textContent = "";
  if (!path) {
    errEl.textContent = "Enter or browse to the English strings.xml file.";
    return;
  }
  statusEl.textContent = "Scanning…";
  document.getElementById("scan-btn").disabled = true;

  const res = await api().scan(path, Array.from(selectedNewLangs));

  document.getElementById("scan-btn").disabled = false;
  statusEl.textContent = "";

  if (!res.ok) {
    errEl.textContent = res.error || "Scan failed.";
    return;
  }

  scanResult = res.result;
  renderReviewScreen();
  showScreen("review");
}

// --- Review screen ------------------------------------------------------

function renderReviewScreen() {
  langDisplayToCode = {};
  Object.entries(scanResult.languages).forEach(([code, name]) => { langDisplayToCode[name] = code; });

  const summaryEl = document.getElementById("review-summary");
  const langNames = Object.values(scanResult.languages);
  let html = `<div class="section-title">Detected</div><ul>`;
  html += `<li>${scanResult.eng_count} translatable strings in English source</li>`;
  html += `<li>${langNames.length} language${langNames.length === 1 ? "" : "s"}: ${langNames.join(", ") || "none found"}</li>`;
  if (scanResult.variant_folders.length) {
    html += `<li>${scanResult.variant_folders.length} screen/orientation variant folder(s) (raw copy, no translation): ${scanResult.variant_folders.join(", ")}</li>`;
  }
  html += `</ul>`;
  if (scanResult.unrecognized_folders.length) {
    html += `<div class="section-title summary-warn">Not touched (unrecognized)</div>`;
    html += `<ul class="summary-warn"><li>${scanResult.unrecognized_folders.join(", ")} — couldn't confidently classify as a language or a variant, left alone.</li></ul>`;
  }
  if (scanResult.parse_errors.length) {
    html += `<div class="section-title summary-warn">Skipped (parse error)</div>`;
    html += `<ul class="summary-warn"><li>${scanResult.parse_errors.join(", ")} — existing file failed to parse, excluded from diffing and writes so nothing gets corrupted.</li></ul>`;
  }
  if (scanResult.invalid_lang_codes && scanResult.invalid_lang_codes.length) {
    html += `<div class="section-title summary-warn">Not created</div>`;
    html += `<ul class="summary-warn"><li>${scanResult.invalid_lang_codes.map(escapeHtml).join(", ")} — not a supported new-folder language yet. Supported: de, es, fr, in, it, ja, ko, pt, ru, zh-rCN.</li></ul>`;
  }
  summaryEl.innerHTML = html;

  selectedKeys = new Set(scanResult.keys.map(k => k.key));
  const tbody = document.getElementById("review-tbody");
  tbody.innerHTML = "";

  if (scanResult.keys.length === 0) {
    tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; color:var(--text-dim); padding:20px;">Everything is already translated in every detected language.</td></tr>`;
  }

  scanResult.keys.forEach(k => {
    const tr = document.createElement("tr");
    tr.dataset.key = k.key;
    tr.dataset.text = k.text;
    const missingNames = k.missing_in.map(code => scanResult.languages[code] || code);
    tr.innerHTML = `
      <td class="col-check"><input type="checkbox" checked data-key="${escapeHtml(k.key)}" /></td>
      <td class="key-cell">${escapeHtml(k.key)}</td>
      <td>${escapeHtml(k.text)}</td>
      <td>${missingNames.map(n => `<span class="badge">${escapeHtml(n)}</span>`).join("")}</td>
    `;
    tbody.appendChild(tr);
  });

  tbody.querySelectorAll('input[type="checkbox"]').forEach(cb => {
    cb.addEventListener("change", () => {
      if (cb.checked) selectedKeys.add(cb.dataset.key);
      else selectedKeys.delete(cb.dataset.key);
      updateSelectedCount();
    });
  });

  document.getElementById("review-filter-input").value = "";
  applyReviewFilter();
  updateSelectedCount();
}

function applyReviewFilter() {
  const q = document.getElementById("review-filter-input").value.trim().toLowerCase();
  const rows = document.querySelectorAll("#review-tbody tr[data-key]");
  let visible = 0;
  rows.forEach(tr => {
    const matches = !q
      || tr.dataset.key.toLowerCase().includes(q)
      || tr.dataset.text.toLowerCase().includes(q);
    tr.classList.toggle("hidden", !matches);
    if (matches) visible++;
  });

  const countEl = document.getElementById("review-filter-count");
  if (rows.length === 0) {
    countEl.textContent = "";
  } else if (q) {
    countEl.textContent = `Showing ${visible} of ${rows.length}`;
  } else {
    countEl.textContent = "";
  }
}

function updateSelectedCount() {
  document.getElementById("selected-count").textContent =
    `${selectedKeys.size} of ${scanResult.keys.length} selected`;
  document.getElementById("run-btn").disabled = selectedKeys.size === 0;
}

function wireReviewScreen() {
  document.getElementById("select-all-btn").addEventListener("click", () => {
    document.querySelectorAll('#review-tbody tr[data-key]:not(.hidden) input[type="checkbox"]')
      .forEach(cb => { cb.checked = true; selectedKeys.add(cb.dataset.key); });
    updateSelectedCount();
  });
  document.getElementById("select-none-btn").addEventListener("click", () => {
    document.querySelectorAll('#review-tbody tr[data-key]:not(.hidden) input[type="checkbox"]')
      .forEach(cb => { cb.checked = false; selectedKeys.delete(cb.dataset.key); });
    updateSelectedCount();
  });
  document.getElementById("back-to-setup-btn").addEventListener("click", () => showScreen("setup"));
  document.getElementById("run-btn").addEventListener("click", startRun);

  document.getElementById("review-filter-input").addEventListener("input", applyReviewFilter);
}

// --- Progress screen ------------------------------------------------------

let progressState = {};

function startRun() {
  const provider = document.querySelector('input[name="provider"]:checked').value;
  const syncSheet = document.getElementById("sheet-sync-toggle").checked;

  progressState = {};
  document.getElementById("progress-langs").innerHTML = "";
  document.getElementById("progress-log").textContent = "";

  showScreen("progress");
  api().run_translation(Array.from(selectedKeys), provider, syncSheet);
}

function ensureLangProgressRow(lang) {
  if (progressState[lang]) return progressState[lang];
  const container = document.getElementById("progress-langs");
  const div = document.createElement("div");
  div.className = "progress-lang";
  div.innerHTML = `
    <div class="progress-lang-head"><span>${escapeHtml(lang)}</span><span class="progress-lang-count">0/0</span></div>
    <div class="progress-bar-track"><div class="progress-bar-fill" style="width:0%"></div></div>
  `;
  container.appendChild(div);
  const row = { el: div, count: div.querySelector(".progress-lang-count"), fill: div.querySelector(".progress-bar-fill") };
  progressState[lang] = row;
  return row;
}

window.onTranslationProgress = function (lang, done, total) {
  const row = ensureLangProgressRow(lang);
  row.count.textContent = `${done}/${total}`;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  row.fill.style.width = pct + "%";
  if (done >= total) row.fill.classList.add("done");
};

window.onTranslationLog = function (msg) {
  const log = document.getElementById("progress-log");
  log.textContent += msg + "\n";
  log.scrollTop = log.scrollHeight;
};

window.onTranslationError = function (msg) {
  const log = document.getElementById("progress-log");
  log.textContent += "ERROR: " + msg + "\n";
  log.scrollTop = log.scrollHeight;
  renderResultsScreen({ written: {}, failures: {}, variant_written: {}, sheet_status: "skipped", sheet_error: null, sheet_tab_name: null, fatal: msg });
  showScreen("results");
};

window.onTranslationDone = function (payload) {
  renderResultsScreen(payload);
  showScreen("results");
};

// --- Results screen ------------------------------------------------------

function renderResultsScreen(payload) {
  const el = document.getElementById("results-summary");
  let html = "";

  if (payload.fatal) {
    html += `<p class="error-text">Run failed before completion: ${escapeHtml(payload.fatal)}</p>`;
  }

  const writtenLangs = Object.keys(payload.written || {});
  html += `<div class="section-title">Written</div>`;
  if (writtenLangs.length === 0 && Object.keys(payload.variant_written || {}).length === 0) {
    html += `<p class="hint">Nothing new was written.</p>`;
  } else {
    writtenLangs.forEach(lang => {
      html += `<div class="results-lang-row"><span>${escapeHtml(lang)}</span><span class="count-ok">+${payload.written[lang]}</span></div>`;
    });
    Object.keys(payload.variant_written || {}).forEach(folder => {
      html += `<div class="results-lang-row"><span>${escapeHtml(folder)} (raw copy)</span><span class="count-ok">+${payload.variant_written[folder]}</span></div>`;
    });
  }

  const failLangs = Object.keys(payload.failures || {});
  if (failLangs.length) {
    html += `<div class="section-title summary-warn">Still missing after retries</div>`;
    failLangs.forEach(lang => {
      html += `<div class="results-lang-row"><span>${escapeHtml(lang)}</span><span class="count-fail">${payload.failures[lang].length}</span></div>`;
      html += `<div class="hint">${payload.failures[lang].map(escapeHtml).join(", ")}</div>`;
    });
    html += `<p class="hint">Rerun to retry — the next scan will pick these back up as missing.</p>`;
  }

  html += `<div class="section-title">Google Sheet</div>`;
  if (payload.sheet_status === "synced") {
    html += `<p><span class="count-ok">Synced</span> — tab "${escapeHtml(payload.sheet_tab_name || "")}"</p>`;
  } else if (payload.sheet_status === "error") {
    html += `<p class="error-text">Sheet sync failed: ${escapeHtml(payload.sheet_error || "unknown error")}</p>`;
  } else {
    html += `<p class="hint">Skipped (sync not enabled, or nothing new was written).</p>`;
  }

  el.innerHTML = html;
}

function wireResultsScreen() {
  document.getElementById("new-run-btn").addEventListener("click", () => {
    scanResult = null;
    selectedKeys = new Set();
    showScreen("setup");
  });
}

// --- Updates ------------------------------------------------------

let pendingUpdate = null;
let manualUpdateCheckInFlight = false;

async function loadAppVersion() {
  const v = await api().get_app_version();
  document.getElementById("app-version").textContent = "v" + v;
}

async function checkForUpdate(manual) {
  // Fires the check and returns immediately -- the network call happens on
  // a background thread in Python; the result comes back later via
  // onUpdateCheckResult. Never await a result here, so a slow/unreachable
  // GitHub can't freeze the UI at launch.
  const menuItem = document.getElementById("menu-check-update");
  if (manual) {
    manualUpdateCheckInFlight = true;
    menuItem.disabled = true;
    menuItem.textContent = "Checking…";
  }
  api().check_for_update();
}

window.onUpdateCheckResult = function (info) {
  const menuItem = document.getElementById("menu-check-update");
  if (manualUpdateCheckInFlight) {
    menuItem.disabled = false;
    menuItem.textContent = "Check for updates";
  }

  if (info.available) {
    pendingUpdate = info;
    renderUpdateBanner(info);
  } else if (manualUpdateCheckInFlight) {
    alert("You're on the latest version.");
  }
  manualUpdateCheckInFlight = false;
};

function renderUpdateBanner(info) {
  const banner = document.getElementById("update-banner");
  document.getElementById("update-banner-text").textContent =
    `Update available: ${info.version} — a newer version is ready to install.`;
  banner.classList.remove("hidden");
}

function wireUpdateBanner() {
  document.getElementById("update-dismiss-btn").addEventListener("click", () => {
    document.getElementById("update-banner").classList.add("hidden");
  });

  document.getElementById("update-install-btn").addEventListener("click", async () => {
    if (!pendingUpdate) return;
    document.getElementById("update-banner-text").textContent = "Downloading update… 0%";
    document.getElementById("update-install-btn").disabled = true;
    document.getElementById("update-dismiss-btn").disabled = true;
    await api().download_and_install_update(pendingUpdate.download_url);
  });
}

window.onUpdateDownloadProgress = function (downloaded, total) {
  const pct = total > 0 ? Math.round((downloaded / total) * 100) : 0;
  document.getElementById("update-banner-text").textContent = `Downloading update… ${pct}%`;
};

window.onUpdateInstalling = function () {
  document.getElementById("update-banner-text").textContent =
    "Launching installer — this app will close now, finish the install in the setup window that opens.";
};

window.onUpdateError = function (msg) {
  document.getElementById("update-banner-text").textContent = "Update failed: " + msg;
  document.getElementById("update-install-btn").disabled = false;
  document.getElementById("update-dismiss-btn").disabled = false;
};

// --- Menu / About ------------------------------------------------------

const GITHUB_USERNAME = "adnaanaeem";
let aboutLoaded = false;

function wireMenu() {
  const menuBtn = document.getElementById("menu-btn");
  const dropdown = document.getElementById("menu-dropdown");

  menuBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    dropdown.classList.toggle("hidden");
  });
  document.addEventListener("click", () => dropdown.classList.add("hidden"));
  dropdown.addEventListener("click", (e) => e.stopPropagation());

  document.getElementById("menu-check-update").addEventListener("click", () => {
    dropdown.classList.add("hidden");
    checkForUpdate(true);
  });
  document.getElementById("menu-about").addEventListener("click", () => {
    dropdown.classList.add("hidden");
    openAboutModal();
  });
}

async function openAboutModal() {
  const modal = document.getElementById("about-modal");
  modal.classList.remove("hidden");
  document.getElementById("about-avatar").src = `https://github.com/${GITHUB_USERNAME}.png`;

  const v = await api().get_app_version();
  document.getElementById("about-version").textContent = "v" + v;

  if (aboutLoaded) return;
  try {
    const resp = await fetch(`https://api.github.com/users/${GITHUB_USERNAME}`);
    if (!resp.ok) return;
    const profile = await resp.json();
    if (profile.name) document.getElementById("about-name").textContent = profile.name;
    document.getElementById("about-location").textContent = profile.location ? `📍 ${profile.location}` : "";
    document.getElementById("about-company").textContent = profile.company ? `🏢 ${profile.company}` : "";
    if (profile.html_url) {
      const link = document.getElementById("about-link");
      link.href = profile.html_url;
      link.textContent = profile.html_url.replace(/^https?:\/\//, "");
    }
    aboutLoaded = true;
  } catch (e) {
    // offline or GitHub unreachable -- the static fallback already in the HTML stays as-is.
  }
}

function wireAboutModal() {
  document.getElementById("about-close-btn").addEventListener("click", () => {
    document.getElementById("about-modal").classList.add("hidden");
  });
  document.getElementById("about-modal").addEventListener("click", (e) => {
    if (e.target.id === "about-modal") document.getElementById("about-modal").classList.add("hidden");
  });
}

// --- Event polling ------------------------------------------------------
//
// Python never calls window.evaluate_js() from a background thread -- that
// reliably hung the whole app (confirmed with a py-spy stack dump; see the
// comment on Api._emit in main.py for the full story, including why
// marshaling the call onto the GUI thread didn't fix it either). Instead,
// background threads queue {fn, args} events server-side and this polls
// for them on a plain interval, dispatching each to the same
// window.onXxx(...) handlers used throughout this file. The polling
// interval is cheap (an empty-queue round trip) so it just runs
// continuously rather than being started/stopped per operation.

function startEventPolling() {
  setInterval(async () => {
    const events = await api().poll_events();
    events.forEach(e => {
      const fn = window[e.fn];
      if (typeof fn === "function") fn(...e.args);
    });
  }, 250);
}

// --- Init ------------------------------------------------------

function init() {
  wireSetupScreen();
  wireReviewScreen();
  wireResultsScreen();
  wireUpdateBanner();
  wireMenu();
  wireAboutModal();
  loadSettings();
  loadLanguagePicker();
  loadAppVersion();
  startEventPolling();
  checkForUpdate(false);
  showScreen("setup");
}

if (window.pywebview) {
  init();
} else {
  window.addEventListener("pywebviewready", init);
}
