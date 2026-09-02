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

function renderRecentPaths(paths) {
  const recentDiv = document.getElementById("recent-paths");
  recentDiv.innerHTML = "";
  (paths || []).forEach(p => {
    const chip = document.createElement("span");
    chip.className = "recent-path-chip";
    chip.innerHTML = `<span class="recent-path-text"></span><span class="recent-path-remove" title="Remove">×</span>`;
    chip.querySelector(".recent-path-text").textContent = p;
    chip.addEventListener("click", () => { document.getElementById("path-input").value = p; });
    chip.querySelector(".recent-path-remove").addEventListener("click", async (e) => {
      e.stopPropagation();
      await api().remove_recent_path(p);
      renderRecentPaths((paths || []).filter(x => x !== p));
    });
    recentDiv.appendChild(chip);
  });
}

async function loadSettings() {
  const s = await api().get_settings();

  renderRecentPaths(s.recent_paths);

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

  document.getElementById("import-sheet-id-display").textContent = s.google_sheet_id || "(not set)";
}

// --- Sheet connection status (shared across Settings/iOS/Import) ---------
//
// Resolves the configured Sheet ID to the sheet's real title, so every
// screen that touches Google Sheets shows *which* sheet it's pointed at
// instead of an opaque ID -- the exact confusion behind a user pasting a
// wrong-but-valid-looking Sheet ID. One backend call, one shared piece of
// state, rendered onto all three screens' status spots.

let sheetConnectionStatus = null;

async function checkSheetConnection() {
  await api().check_sheet_connection();
}

window.onSheetConnectionChecked = function (payload) {
  sheetConnectionStatus = payload;
  renderSheetConnectionStatus();
};

function renderSheetConnectionStatus() {
  const s = sheetConnectionStatus;

  const settingsEl = document.getElementById("settings-sheet-status");
  if (settingsEl) {
    if (!s || !s.configured) {
      settingsEl.textContent = "";
      settingsEl.className = "hint";
    } else if (s.ok) {
      settingsEl.textContent = `✓ Connected to "${s.name}"`;
      settingsEl.className = "hint status-ok";
    } else {
      settingsEl.textContent = `Couldn't connect: ${s.error}`;
      settingsEl.className = "hint error-text";
    }
  }

  const iosEl = document.getElementById("ios-sheet-name-hint");
  if (iosEl) {
    iosEl.textContent = s && s.ok ? `Uploads to "${s.name}"` : "";
  }

  const importNameEl = document.getElementById("import-sheet-name-display");
  if (importNameEl) {
    if (s && s.ok) importNameEl.textContent = s.name;
    else if (s && s.configured) importNameEl.textContent = "(couldn't connect)";
    else importNameEl.textContent = "(not configured)";
  }
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
  document.getElementById("browse-btn").addEventListener("click", async () => {
    const res = await api().choose_strings_file();
    if (res.ok) {
      document.getElementById("path-input").value = res.path;
      document.getElementById("path-error").textContent = "";
    } else if (res.error) {
      document.getElementById("path-error").textContent = res.error;
    }
  });

  document.getElementById("scan-btn").addEventListener("click", doScan);

  document.getElementById("lang-filter-input").addEventListener("input", (e) => {
    renderLangPicker(e.target.value);
  });
}

// --- Settings screen ------------------------------------------------------
//
// Centralizes the AI Provider keys and Google Sheet QA export config that
// used to be duplicated per-screen (Setup had its own copy, Import grew a
// second overridable copy) -- single source of truth, read by Android's
// run, iOS's translate/upload, and the Import screen alike.

function wireSettingsScreen() {
  document.querySelectorAll('input[name="provider"]').forEach(r => {
    r.addEventListener("change", () => { updateProviderVisibility(); persistSettings(); });
  });
  document.getElementById("sheet-sync-toggle").addEventListener("change", () => {
    updateSheetFieldsVisibility(); persistSettings();
  });

  document.getElementById("sheet-id-input").addEventListener("change", async (e) => {
    // Accepts a pasted full share URL, not just the bare ID -- normalize
    // the field to just the ID once parsed, so what's saved/displayed
    // elsewhere is always the clean ID.
    const parsed = await api().parse_sheet_id(e.target.value);
    e.target.value = parsed;
    persistSettings();
    checkSheetConnection();
  });
  document.getElementById("service-account-input").addEventListener("change", () => {
    persistSettings();
    checkSheetConnection();
  });
  ["batch-size-input", "max-retries-input"].forEach(id => {
    document.getElementById(id).addEventListener("change", persistSettings);
  });

  document.getElementById("sa-browse-btn").addEventListener("click", async () => {
    const res = await api().choose_service_account_file();
    if (res.ok) {
      document.getElementById("service-account-input").value = res.path;
      persistSettings();
      refreshServiceAccountEmail();
      checkSheetConnection();
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

  document.getElementById("settings-back-btn").addEventListener("click", () => {
    switchPlatform(currentPlatform);
  });
}

async function refreshServiceAccountEmail() {
  const email = await api().get_service_account_email();
  const text = email || "(set a service account JSON above first)";
  document.getElementById("settings-sa-email").textContent = text;
  document.getElementById("import-sa-email").textContent = text;
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

window.onUpdateInstalling = function (msg) {
  document.getElementById("update-banner-text").textContent = msg;
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

  document.getElementById("menu-settings").addEventListener("click", () => {
    dropdown.classList.add("hidden");
    document.querySelector(".steps").classList.add("hidden");
    document.querySelectorAll(".platform-btn").forEach(b => b.classList.remove("active"));
    showScreen("settings");
  });
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

// --- Platform toggle ------------------------------------------------------

let currentPlatform = "android";

function switchPlatform(platform) {
  currentPlatform = platform;
  document.getElementById("platform-android-btn").classList.toggle("active", platform === "android");
  document.getElementById("platform-ios-btn").classList.toggle("active", platform === "ios");
  document.getElementById("platform-import-btn").classList.toggle("active", platform === "import");
  document.querySelector(".steps").classList.toggle("hidden", platform !== "android");
  showScreen(platform === "android" ? "setup" : platform);
}

function wirePlatformToggle() {
  document.getElementById("platform-android-btn").addEventListener("click", () => switchPlatform("android"));
  document.getElementById("platform-ios-btn").addEventListener("click", () => switchPlatform("ios"));
  document.getElementById("platform-import-btn").addEventListener("click", () => switchPlatform("import"));
}

// --- iOS ------------------------------------------------------------------
//
// A fundamentally different shape from the Android flow above: no scan/diff
// step. A developer types one English string at a time, it's translated
// into every selected language in one call, and gets appended into a
// growing .xcstrings catalog. "This session" accumulates what's been added
// since Load, so it can all be uploaded to the QA Sheet together.

let iosLangOptions = [];
let iosSelectedLangs = new Set();
let iosSession = [];
let iosKeyManuallyEdited = false;

function renderIosRecentPaths(paths) {
  const recentDiv = document.getElementById("ios-recent-paths");
  recentDiv.innerHTML = "";
  (paths || []).forEach(p => {
    const chip = document.createElement("span");
    chip.className = "recent-path-chip";
    chip.innerHTML = `<span class="recent-path-text"></span><span class="recent-path-remove" title="Remove">×</span>`;
    chip.querySelector(".recent-path-text").textContent = p;
    chip.addEventListener("click", () => { document.getElementById("ios-path-input").value = p; });
    chip.querySelector(".recent-path-remove").addEventListener("click", async (e) => {
      e.stopPropagation();
      await api().remove_recent_path(p, "recent_ios_paths");
      renderIosRecentPaths((paths || []).filter(x => x !== p));
    });
    recentDiv.appendChild(chip);
  });
}

async function loadIosRecentPaths() {
  const s = await api().get_settings();
  renderIosRecentPaths(s.recent_ios_paths);
}

async function loadIosLanguagePicker() {
  iosLangOptions = await api().get_ios_language_options();
  iosSelectedLangs = new Set(iosLangOptions.filter(o => o.is_default).map(o => o.code));
  renderIosLangPicker("");
}

function setIosLangSelected(code, isSelected) {
  if (isSelected) iosSelectedLangs.add(code);
  else iosSelectedLangs.delete(code);
  renderIosSelectedLangChips();
  const cb = document.querySelector(`#ios-lang-picker input[data-code="${CSS.escape(code)}"]`);
  if (cb) cb.checked = isSelected;
}

function renderIosLangPicker(filterText) {
  const container = document.getElementById("ios-lang-picker");
  const q = filterText.trim().toLowerCase();
  container.innerHTML = "";
  iosLangOptions.forEach(opt => {
    const matches = !q || opt.display_name.toLowerCase().includes(q) || opt.code.toLowerCase().includes(q);
    if (!matches) return;
    const label = document.createElement("label");
    label.className = "lang-chip";
    label.innerHTML = `
      <input type="checkbox" data-code="${escapeHtml(opt.code)}" ${iosSelectedLangs.has(opt.code) ? "checked" : ""} />
      <span class="lang-flag">${opt.flag}</span>
      <span>${escapeHtml(opt.display_name)}</span>
      <span class="lang-code">${escapeHtml(opt.code)}</span>
    `;
    label.querySelector("input").addEventListener("change", (e) => {
      setIosLangSelected(opt.code, e.target.checked);
    });
    container.appendChild(label);
  });
  renderIosSelectedLangChips();
}

function renderIosSelectedLangChips() {
  const el = document.getElementById("ios-lang-selected-list");
  if (!el) return;
  el.innerHTML = "";
  if (iosSelectedLangs.size === 0) {
    el.innerHTML = `<span class="lang-selected-empty">None selected.</span>`;
    return;
  }
  Array.from(iosSelectedLangs).forEach(code => {
    const opt = iosLangOptions.find(o => o.code === code);
    const chip = document.createElement("span");
    chip.className = "selected-lang-chip";
    chip.innerHTML = `
      <span class="lang-flag">${opt ? opt.flag : "🌐"}</span>
      <span>${escapeHtml(opt ? opt.display_name : code)}</span>
      <span class="remove-x" title="Remove">×</span>
    `;
    chip.querySelector(".remove-x").addEventListener("click", () => setIosLangSelected(code, false));
    el.appendChild(chip);
  });
}

async function doIosLoad() {
  const path = document.getElementById("ios-path-input").value.trim();
  const errEl = document.getElementById("ios-path-error");
  const statusEl = document.getElementById("ios-load-status");
  errEl.textContent = "";
  if (!path) {
    errEl.textContent = "Enter or browse to a .xcstrings file (an existing one, or a new path to create one).";
    return;
  }
  statusEl.textContent = "Loading…";
  document.getElementById("ios-load-btn").disabled = true;

  const res = await api().ios_load_catalog_info(path);

  document.getElementById("ios-load-btn").disabled = false;
  statusEl.textContent = "";

  if (!res.ok) {
    errEl.textContent = res.error || "Failed to load catalog.";
    return;
  }

  statusEl.textContent = `Ready — ${res.existing_key_count} existing string(s) in this catalog.`;
  document.getElementById("ios-main").classList.remove("hidden");
  loadIosRecentPaths();
}

function updateIosKeyFromText() {
  if (iosKeyManuallyEdited) return;
  api().ios_generate_key(document.getElementById("ios-text-input").value).then(key => {
    document.getElementById("ios-key-input").value = key;
  });
}

async function doIosAdd() {
  const path = document.getElementById("ios-path-input").value.trim();
  const text = document.getElementById("ios-text-input").value;
  const context = document.getElementById("ios-context-input").value.trim();
  const key = document.getElementById("ios-key-input").value.trim();
  const statusEl = document.getElementById("ios-add-status");
  const provider = document.querySelector('input[name="provider"]:checked').value;

  if (!text.trim()) { statusEl.textContent = "Enter the English text first."; return; }
  if (!key) { statusEl.textContent = "Key is empty — type some English text or fill in a key manually."; return; }
  if (iosSelectedLangs.size === 0) { statusEl.textContent = "Select at least one target language."; return; }

  statusEl.textContent = "Translating…";
  document.getElementById("ios-add-btn").disabled = true;
  await api().ios_translate_and_add(path, key, text, context, Array.from(iosSelectedLangs), provider);
}

window.onIosAddLog = function (msg) {
  document.getElementById("ios-add-status").textContent = msg;
};

window.onIosAddError = function (msg) {
  document.getElementById("ios-add-status").textContent = "Failed: " + msg;
  document.getElementById("ios-add-btn").disabled = false;
};

window.onIosAddDone = function (payload) {
  const statusEl = document.getElementById("ios-add-status");
  document.getElementById("ios-add-btn").disabled = false;

  let msg = `Added "${payload.key}".`;
  if (payload.skipped_existing.length) {
    msg += ` Already had: ${payload.skipped_existing.join(", ")}.`;
  }
  if (payload.still_missing.length) {
    msg += ` Still missing after retries: ${payload.still_missing.join(", ")}.`;
  }
  statusEl.textContent = msg;

  iosSession.push({ key: payload.key, english_text: payload.english_text, translations: payload.translations });
  renderIosSessionTable();

  document.getElementById("ios-text-input").value = "";
  document.getElementById("ios-context-input").value = "";
  document.getElementById("ios-key-input").value = "";
  iosKeyManuallyEdited = false;
};

function renderIosSessionTable() {
  const tbody = document.getElementById("ios-session-tbody");
  tbody.innerHTML = "";
  iosSession.forEach(item => {
    const tr = document.createElement("tr");
    const langBadges = Object.keys(item.translations)
      .map(code => `<span class="badge">${escapeHtml(code)}</span>`).join("");
    tr.innerHTML = `
      <td class="key-cell">${escapeHtml(item.key)}</td>
      <td>${escapeHtml(item.english_text)}</td>
      <td>${langBadges}</td>
    `;
    tbody.appendChild(tr);
  });
  document.getElementById("ios-session-count").textContent =
    iosSession.length ? `${iosSession.length} string(s) added this session` : "";
  document.getElementById("ios-upload-sheet-btn").disabled = iosSession.length === 0;
}

async function doIosUploadSheet() {
  const provider = document.querySelector('input[name="provider"]:checked').value;
  const statusEl = document.getElementById("ios-upload-status");
  statusEl.textContent = "Uploading…";
  document.getElementById("ios-upload-sheet-btn").disabled = true;
  await api().ios_upload_session_to_sheet(iosSession, provider);
}

window.onIosSheetUploadDone = function (payload) {
  document.getElementById("ios-upload-status").textContent =
    `Synced ${payload.count} string(s) — tab "${payload.tab_name}"`;
  document.getElementById("ios-upload-sheet-btn").disabled = iosSession.length === 0;
};

window.onIosSheetUploadError = function (msg) {
  document.getElementById("ios-upload-status").textContent = "Sheet sync failed: " + msg;
  document.getElementById("ios-upload-sheet-btn").disabled = iosSession.length === 0;
};

function wireIosScreen() {
  document.getElementById("ios-browse-btn").addEventListener("click", async () => {
    const res = await api().choose_ios_catalog_file();
    if (res.ok) {
      document.getElementById("ios-path-input").value = res.path;
      document.getElementById("ios-path-error").textContent = "";
    }
  });

  document.getElementById("ios-load-btn").addEventListener("click", doIosLoad);

  document.getElementById("ios-lang-filter-input").addEventListener("input", (e) => {
    renderIosLangPicker(e.target.value);
  });

  document.getElementById("ios-text-input").addEventListener("input", updateIosKeyFromText);
  document.getElementById("ios-key-input").addEventListener("input", () => { iosKeyManuallyEdited = true; });

  document.getElementById("ios-add-btn").addEventListener("click", doIosAdd);
  document.getElementById("ios-upload-sheet-btn").addEventListener("click", doIosUploadSheet);
}

// --- Import from Sheet ------------------------------------------------------
//
// The reverse direction of both platforms' Sheet sync: read rows a
// reviewer already QA'd/edited in the Sheet back out, let the user pick
// which ones, then write them into a local project file. Writing itself
// happens entirely in Python (sheet_import.py), reusing the same
// never-overwrite write paths every other screen uses -- this is just the
// fetch/review/dispatch plumbing.

let importRows = [];
let importSelectedKeys = new Set();

async function doImportLoadTabs() {
  const errEl = document.getElementById("import-fetch-error");
  errEl.textContent = "";
  const btn = document.getElementById("import-load-tabs-btn");
  btn.disabled = true;
  btn.textContent = "Loading…";
  await api().sheet_list_tabs();
}

window.onSheetTabsDone = function (tabs) {
  const btn = document.getElementById("import-load-tabs-btn");
  btn.disabled = false;
  btn.textContent = "Load tabs";

  const select = document.getElementById("import-tab-select");
  select.innerHTML = "";
  if (tabs.length === 0) {
    select.innerHTML = `<option>No tabs found</option>`;
    select.disabled = true;
    document.getElementById("import-fetch-btn").disabled = true;
    return;
  }
  tabs.forEach(t => {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = t;
    select.appendChild(opt);
  });
  select.disabled = false;
  document.getElementById("import-fetch-btn").disabled = false;
};

window.onSheetTabsError = function (msg) {
  const btn = document.getElementById("import-load-tabs-btn");
  btn.disabled = false;
  btn.textContent = "Load tabs";
  document.getElementById("import-fetch-error").textContent = msg;
};

async function doImportFetch() {
  const tabName = document.getElementById("import-tab-select").value;
  const errEl = document.getElementById("import-fetch-error");
  const btn = document.getElementById("import-fetch-btn");
  errEl.textContent = "";
  if (!tabName) { errEl.textContent = "Load and pick a tab first."; return; }
  btn.disabled = true;
  btn.textContent = "Fetching…";
  await api().sheet_fetch_tab(tabName);
}

window.onSheetFetchDone = function (result) {
  const btn = document.getElementById("import-fetch-btn");
  btn.disabled = false;
  btn.textContent = "Fetch strings";

  importRows = result.rows;
  renderImportTable();
  document.getElementById("import-review").classList.remove("hidden");
};

window.onSheetFetchError = function (msg) {
  const btn = document.getElementById("import-fetch-btn");
  btn.disabled = false;
  btn.textContent = "Fetch strings";
  document.getElementById("import-fetch-error").textContent = msg;
};

function renderImportTable() {
  importSelectedKeys = new Set(importRows.map(r => r.key));
  const tbody = document.getElementById("import-tbody");
  tbody.innerHTML = "";

  if (importRows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; color:var(--text-dim); padding:20px;">No usable rows found in this tab.</td></tr>`;
  }

  importRows.forEach(row => {
    const tr = document.createElement("tr");
    tr.dataset.key = row.key;
    tr.dataset.text = row.english;
    const langBadges = Object.keys(row.values).map(h => `<span class="badge">${escapeHtml(h)}</span>`).join("");
    // Key column is intentionally narrow (import rows should be found by
    // English text, which is what a sheet without a Key column always
    // has) -- long keys truncate with an ellipsis, full text on hover via
    // the title attribute rather than wrapping the row taller.
    const autoNote = row.key_was_generated
      ? " (auto-generated from English text -- no Key column, or an empty Key cell, for this row)"
      : "";
    const autoTag = row.key_was_generated ? ` <span class="hint-inline">*</span>` : "";
    tr.innerHTML = `
      <td class="col-check"><input type="checkbox" checked data-key="${escapeHtml(row.key)}" /></td>
      <td class="key-cell" title="${escapeHtml(row.key + autoNote)}">${escapeHtml(row.key)}${autoTag}</td>
      <td>${escapeHtml(row.english)}</td>
      <td>${langBadges}</td>
    `;
    tbody.appendChild(tr);
  });

  tbody.querySelectorAll('input[type="checkbox"]').forEach(cb => {
    cb.addEventListener("change", () => {
      if (cb.checked) importSelectedKeys.add(cb.dataset.key);
      else importSelectedKeys.delete(cb.dataset.key);
      updateImportSelectedCount();
    });
  });

  document.getElementById("import-filter-input").value = "";
  applyImportFilter();
  updateImportSelectedCount();
}

function applyImportFilter() {
  const q = document.getElementById("import-filter-input").value.trim().toLowerCase();
  const rows = document.querySelectorAll("#import-tbody tr[data-key]");
  let visible = 0;
  rows.forEach(tr => {
    const matches = !q || tr.dataset.key.toLowerCase().includes(q) || tr.dataset.text.toLowerCase().includes(q);
    tr.classList.toggle("hidden", !matches);
    if (matches) visible++;
  });
  const countEl = document.getElementById("import-filter-count");
  countEl.textContent = (rows.length && q) ? `Showing ${visible} of ${rows.length}` : "";
}

function updateImportSelectedCount() {
  document.getElementById("import-selected-count").textContent =
    `${importSelectedKeys.size} of ${importRows.length} selected`;
  document.getElementById("import-write-btn").disabled = importSelectedKeys.size === 0;
}

function updateImportPlatformVisibility() {
  const platform = document.querySelector('input[name="import-platform"]:checked').value;
  document.getElementById("import-android-path-row").classList.toggle("hidden", platform !== "android");
  document.getElementById("import-ios-path-row").classList.toggle("hidden", platform !== "ios");
}

async function doImportWrite() {
  const platform = document.querySelector('input[name="import-platform"]:checked').value;
  const path = (platform === "android"
    ? document.getElementById("import-android-path-input").value
    : document.getElementById("import-ios-path-input").value).trim();
  const statusEl = document.getElementById("import-write-status");
  document.getElementById("import-write-summary").innerHTML = "";

  if (!path) { statusEl.textContent = "Enter or browse to a target file first."; return; }
  if (importSelectedKeys.size === 0) { statusEl.textContent = "Select at least one row."; return; }

  const selectedRows = importRows.filter(r => importSelectedKeys.has(r.key));
  statusEl.textContent = "Writing…";
  document.getElementById("import-write-btn").disabled = true;
  await api().sheet_import_write(platform, path, selectedRows);
}

window.onSheetImportDone = function (payload) {
  document.getElementById("import-write-btn").disabled = importSelectedKeys.size === 0;
  document.getElementById("import-write-status").textContent = "Done.";

  const summaryEl = document.getElementById("import-write-summary");
  let html = "";
  if (payload.platform === "android") {
    const writtenLangs = Object.keys(payload.written || {});
    if (writtenLangs.length) {
      html += `<div class="section-title">Written</div>`;
      writtenLangs.forEach(lang => {
        html += `<div class="results-lang-row"><span>${escapeHtml(lang)}</span><span class="count-ok">+${payload.written[lang]}</span></div>`;
      });
    } else {
      html += `<p class="hint">Nothing new was written — every selected key/language pair already existed.</p>`;
    }
    const failLangs = Object.keys(payload.failures || {});
    if (failLangs.length) {
      html += `<div class="section-title summary-warn">Failed</div>`;
      failLangs.forEach(lang => {
        html += `<div class="hint">${escapeHtml(lang)}: ${escapeHtml(payload.failures[lang])}</div>`;
      });
    }
  } else {
    // iOS: distinguishes genuinely new keys from existing keys that just
    // got a new language filled in, from rows that changed nothing at all
    // (key + every selected language for it already existed) -- never
    // overwrites an existing localization, same rule as everywhere else,
    // and this is what actually shows that rather than just counting rows.
    if (payload.new_keys) {
      html += `<div class="results-lang-row"><span>New keys added</span><span class="count-ok">+${payload.new_keys}</span></div>`;
    }
    if (payload.updated_keys) {
      html += `<div class="results-lang-row"><span>Existing keys, new language(s) filled in</span><span class="count-ok">+${payload.updated_keys}</span></div>`;
    }
    if (payload.already_complete) {
      html += `<div class="results-lang-row"><span>Already had everything selected</span><span>${payload.already_complete}</span></div>`;
    }
    if (!payload.new_keys && !payload.updated_keys && !payload.already_complete) {
      html += `<p class="hint">Nothing was written.</p>`;
    }
    const dupKeys = Object.keys(payload.duplicate_keys || {});
    if (dupKeys.length) {
      html += `<div class="section-title summary-warn">Same key on more than one selected row</div>`;
      dupKeys.forEach(k => {
        const texts = payload.duplicate_keys[k].map(escapeHtml).join('" / "');
        html += `<div class="hint">${escapeHtml(k)}: "${texts}" — merged into one catalog entry (still never overwrites an existing translation).</div>`;
      });
    }
  }
  if (payload.unrecognized_columns && payload.unrecognized_columns.length) {
    html += `<div class="section-title summary-warn">Not recognized as a language</div>`;
    html += `<p class="hint">${payload.unrecognized_columns.map(escapeHtml).join(", ")} — column header didn't match any known language name for this platform, skipped.</p>`;
  }
  summaryEl.innerHTML = html;
};

window.onSheetImportError = function (msg) {
  document.getElementById("import-write-btn").disabled = importSelectedKeys.size === 0;
  document.getElementById("import-write-status").textContent = "Failed: " + msg;
};

function wireImportScreen() {
  document.getElementById("import-settings-link").addEventListener("click", (e) => {
    e.preventDefault();
    document.getElementById("menu-dropdown").classList.add("hidden");
    document.querySelector(".steps").classList.add("hidden");
    document.querySelectorAll(".platform-btn").forEach(b => b.classList.remove("active"));
    showScreen("settings");
  });

  document.getElementById("import-load-tabs-btn").addEventListener("click", doImportLoadTabs);
  document.getElementById("import-fetch-btn").addEventListener("click", doImportFetch);
  document.getElementById("import-filter-input").addEventListener("input", applyImportFilter);

  document.getElementById("import-select-all-btn").addEventListener("click", () => {
    document.querySelectorAll('#import-tbody tr[data-key]:not(.hidden) input[type="checkbox"]')
      .forEach(cb => { cb.checked = true; importSelectedKeys.add(cb.dataset.key); });
    updateImportSelectedCount();
  });
  document.getElementById("import-select-none-btn").addEventListener("click", () => {
    document.querySelectorAll('#import-tbody tr[data-key]:not(.hidden) input[type="checkbox"]')
      .forEach(cb => { cb.checked = false; importSelectedKeys.delete(cb.dataset.key); });
    updateImportSelectedCount();
  });

  document.querySelectorAll('input[name="import-platform"]').forEach(r => {
    r.addEventListener("change", updateImportPlatformVisibility);
  });

  document.getElementById("import-android-browse-btn").addEventListener("click", async () => {
    const res = await api().choose_strings_file();
    if (res.ok) document.getElementById("import-android-path-input").value = res.path;
  });
  document.getElementById("import-ios-browse-btn").addEventListener("click", async () => {
    const res = await api().choose_ios_catalog_file();
    if (res.ok) document.getElementById("import-ios-path-input").value = res.path;
  });

  document.getElementById("import-write-btn").addEventListener("click", doImportWrite);
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
  wireSettingsScreen();
  wireReviewScreen();
  wireResultsScreen();
  wireUpdateBanner();
  wireMenu();
  wireAboutModal();
  wirePlatformToggle();
  wireIosScreen();
  wireImportScreen();
  loadSettings();
  loadLanguagePicker();
  loadIosRecentPaths();
  loadIosLanguagePicker();
  refreshServiceAccountEmail();
  checkSheetConnection();
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
