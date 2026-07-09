// ============================================================
// Agent 11 — frontend logic
// Talks to the Flask backend at the same origin. No API keys or
// secrets ever live in this file — everything sensitive stays
// server-side behind ANTHROPIC_API_KEY.
// ============================================================

const state = {
  guidelinesFiles: [],       // File objects staged for /api/guidelines
  guidelinesData: null,      // full guidelines JSON returned by /api/guidelines — resent with every generate call
  draftFiles: [],            // File objects staged for /api/generate (draft_files[])
  references: [],            // [{id, url, title, domain, image, favicon, error, loading}]
  selectedPlatforms: new Set(),
  platformStatus: {},        // {instagram: bool, linkedin: bool, twitter: bool}
  lastResults: null,         // full /api/generate response
  activePlatformTab: null,
  activeView: "dashboard",
};

const $ = (id) => document.getElementById(id);

// ---------------- toasts ----------------

function toast(message, isError = false) {
  const stack = $("toastStack");
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " is-error" : "");
  el.textContent = message;
  stack.appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

// ---------------- navigation ----------------

const VIEW_META = {
  dashboard: { title: "Dashboard", subtitle: "Create. Design. Publish. Scale." },
  studio: { title: "Content Studio", subtitle: "Draft once — publish everywhere, on brand." },
  assets: { title: "Brand Assets", subtitle: "The source of truth every generated post follows." },
  campaigns: { title: "Campaigns", subtitle: "Publish now, or plan what scheduling needs next." },
  analytics: { title: "Analytics", subtitle: "Performance across your connected platforms." },
  settings: { title: "Settings", subtitle: "Connections and environment configuration." },
};

function showView(view) {
  if (!VIEW_META[view]) return;
  state.activeView = view;
  document.querySelectorAll(".view").forEach((el) => { el.hidden = el.id !== `view-${view}`; });
  document.querySelectorAll(".nav-item").forEach((el) => {
    el.classList.toggle("is-active", el.dataset.view === view);
  });
}

function initNav() {
  document.querySelectorAll(".nav-item[data-view]").forEach((btn) => {
    btn.addEventListener("click", () => showView(btn.dataset.view));
  });
  document.querySelectorAll("[data-goto]").forEach((btn) => {
    btn.addEventListener("click", () => showView(btn.dataset.goto));
  });
}

// ---------------- status banner / dashboard / settings ----------------

function setPill(el, ok) {
  if (!el) return;
  el.textContent = ok ? "Connected" : "Not configured";
  el.className = "pill " + (ok ? "pill-ok" : "pill-off");
}

async function loadStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    const banner = $("apiKeyBanner");
    const dot = $("keyStatusDot");
    const text = $("keyStatusText");
    if (data.anthropic_key_set) {
      banner.hidden = true;
      dot.className = "dot dot-ok";
      text.textContent = "Agent 11 · live";
      $("dashEngineStatus").textContent = "Live";
      $("dashEngineNote").textContent = "Claude-powered copy & web-search imagery active";
    } else {
      banner.hidden = false;
      dot.className = "dot dot-warn";
      text.textContent = "Agent 11 · preview mode";
      $("dashEngineStatus").textContent = "Preview mode";
      $("dashEngineNote").textContent = "Set ANTHROPIC_API_KEY for live generation";
    }
    setPill($("settingsAnthropicPill"), !!data.anthropic_key_set);
  } catch (e) {
    $("keyStatusText").textContent = "Connection unknown";
  }

  try {
    const res = await fetch("/api/platform-status");
    state.platformStatus = await res.json();
    const connected = Object.values(state.platformStatus).filter(Boolean).length;
    const total = Object.keys(state.platformStatus).length || 3;
    $("dashPublishStatus").textContent = `${connected} / ${total} connected`;
    setPill($("settingsInstagramPill"), !!state.platformStatus.instagram);
    setPill($("settingsLinkedinPill"), !!state.platformStatus.linkedin);
    setPill($("settingsTwitterPill"), !!state.platformStatus.twitter);
  } catch (e) {
    state.platformStatus = {};
  }
}

// ---------------- guidelines panel ----------------

function fileKindLabel(file) {
  const ext = (file.name.split(".").pop() || "").toUpperCase();
  return ext || "FILE";
}

function renderFileChipList(listEl, files, onRemove) {
  listEl.innerHTML = "";
  listEl.hidden = files.length === 0;
  files.forEach((file, idx) => {
    const li = document.createElement("li");
    li.className = "file-chip";
    li.innerHTML = `
      <span class="file-chip-icon">${fileKindLabel(file)}</span>
      <span class="file-chip-name" title="${file.name}">${file.name}</span>
      <button type="button" class="file-chip-remove" aria-label="Remove file">&times;</button>
    `;
    li.querySelector(".file-chip-remove").addEventListener("click", () => onRemove(idx));
    listEl.appendChild(li);
  });
}

function renderGuidelinesFileList() {
  renderFileChipList($("guidelinesFileList"), state.guidelinesFiles, (idx) => {
    state.guidelinesFiles.splice(idx, 1);
    renderGuidelinesFileList();
  });
}

function renderDraftFileList() {
  renderFileChipList($("draftFileList"), state.draftFiles, (idx) => {
    state.draftFiles.splice(idx, 1);
    renderDraftFileList();
  });
}

function renderGuidelineSummary(g) {
  const el = $("guidelineSummary");
  const studioStatus = $("studioGuidelinesStatus");
  const dashStatus = $("dashGuidelinesStatus");

  if (!g) {
    el.hidden = true;
    studioStatus.textContent = "No guidelines loaded yet.";
    studioStatus.className = "inline-status";
    dashStatus.textContent = "Not loaded";
    return;
  }
  const colorSwatch = (hex) => hex ? `<span class="swatch" style="background:${hex}"></span>${hex}` : "—";
  el.innerHTML = `
    <div><b>Brand:</b> ${g.brand_name || "Unnamed"}</div>
    <div><b>Tone:</b> ${g.tone || "—"}</div>
    <div><b>Colors:</b> ${colorSwatch(g.colors?.primary)} ${colorSwatch(g.colors?.secondary)} ${colorSwatch(g.colors?.accent)}</div>
    ${g.banned_words?.length ? `<div><b>Banned words:</b> ${g.banned_words.join(", ")}</div>` : ""}
    ${g.required_hashtags?.length ? `<div><b>Required hashtags:</b> ${g.required_hashtags.join(" ")}</div>` : ""}
  `;
  el.hidden = false;

  const name = g.brand_name || "Custom guidelines";
  studioStatus.textContent = `Loaded: ${name}`;
  studioStatus.className = "inline-status is-ok";
  dashStatus.textContent = name;
}

// Vercel's serverless functions cap request bodies at ~4.5MB. We stay well
// under that per batch to leave headroom for multipart boundaries and the
// accumulated prior_guidelines_json payload.
const GUIDELINES_BATCH_MAX_BYTES = 3.5 * 1024 * 1024;

function batchFilesBySize(files, maxBytes) {
  const batches = [];
  let current = [];
  let currentSize = 0;
  for (const f of files) {
    if (current.length > 0 && currentSize + f.size > maxBytes) {
      batches.push(current);
      current = [];
      currentSize = 0;
    }
    current.push(f);
    currentSize += f.size;
  }
  if (current.length > 0) batches.push(current);
  return batches;
}

async function uploadGuidelines() {
  if (state.guidelinesFiles.length === 0) return;
  const status = $("guidelinesStatus");
  status.hidden = false;
  status.className = "inline-status";

  const batches = batchFilesBySize(state.guidelinesFiles, GUIDELINES_BATCH_MAX_BYTES);
  let accumulatedGuidelines = null;
  let usedLlmExtraction = false;
  const allSkipped = [];

  try {
    for (let i = 0; i < batches.length; i++) {
      status.textContent = batches.length > 1
        ? `Reading guideline files… (batch ${i + 1} of ${batches.length})`
        : "Reading guideline files…";

      const formData = new FormData();
      batches[i].forEach((f) => formData.append("file", f, f.webkitRelativePath || f.name));
      if (accumulatedGuidelines) {
        formData.append("prior_guidelines_json", JSON.stringify(accumulatedGuidelines));
      }

      const res = await fetch("/api/guidelines", { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Upload failed.");
      accumulatedGuidelines = data.guidelines;
      usedLlmExtraction = data.used_llm_extraction;
      if (data.skipped?.length) allSkipped.push(...data.skipped);
    }

    state.guidelinesData = accumulatedGuidelines;
    status.className = "inline-status is-ok";
    status.textContent = usedLlmExtraction
      ? `Guidelines extracted from ${state.guidelinesFiles.length} file(s).`
      : `Guidelines parsed offline (no API key yet) from ${state.guidelinesFiles.length} file(s).`;
    if (allSkipped.length) status.textContent += ` (skipped: ${allSkipped.join(", ")})`;
    renderGuidelineSummary(accumulatedGuidelines);
    toast("Brand guidelines saved for this session.");
  } catch (e) {
    status.className = "inline-status is-error";
    status.textContent = e.message;
    toast("Couldn't process guidelines: " + e.message, true);
  }
}

// ---------------- reference links panel ----------------

function renderReferenceChips() {
  const list = $("referenceChipList");
  list.innerHTML = "";
  state.references.forEach((ref) => {
    const li = document.createElement("li");
    li.className = "reference-chip";
    if (ref.loading) {
      li.innerHTML = `
        <div class="reference-chip-body">
          <div class="reference-chip-loading">Fetching preview…</div>
          <div class="reference-chip-url">${ref.url}</div>
        </div>
        <button type="button" class="file-chip-remove" aria-label="Remove link">&times;</button>
      `;
    } else if (ref.error) {
      li.innerHTML = `
        <div class="reference-chip-body">
          <div class="reference-chip-title">${ref.domain}</div>
          <div class="reference-chip-error">${ref.error}</div>
        </div>
        <button type="button" class="file-chip-remove" aria-label="Remove link">&times;</button>
      `;
    } else {
      const thumb = ref.image
        ? `<img class="reference-chip-thumb" src="${ref.image}" alt="" onerror="this.style.display='none'">`
        : `<div class="reference-chip-thumb"></div>`;
      li.innerHTML = `
        ${thumb}
        <div class="reference-chip-body">
          <div class="reference-chip-title">${ref.title || ref.domain}</div>
          <div class="reference-chip-url">${ref.domain}</div>
        </div>
        <button type="button" class="file-chip-remove" aria-label="Remove link">&times;</button>
      `;
    }
    li.querySelector(".file-chip-remove").addEventListener("click", () => {
      state.references = state.references.filter((r) => r.id !== ref.id);
      renderReferenceChips();
    });
    list.appendChild(li);
  });
}

async function addReferenceLink() {
  const input = $("referenceLinkInput");
  const url = input.value.trim();
  if (!url) return;
  input.value = "";

  const id = crypto.randomUUID ? crypto.randomUUID() : String(Date.now() + Math.random());
  const ref = { id, url, loading: true, domain: url };
  state.references.push(ref);
  renderReferenceChips();

  try {
    const res = await fetch("/api/reference-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();
    Object.assign(ref, data, { loading: false });
  } catch (e) {
    Object.assign(ref, { loading: false, error: "Couldn't reach that link." });
  }
  renderReferenceChips();
}

// ---------------- platform selection ----------------

function initPlatformCards() {
  document.querySelectorAll(".platform-card").forEach((card) => {
    card.addEventListener("click", () => {
      const key = card.dataset.platform;
      if (state.selectedPlatforms.has(key)) {
        state.selectedPlatforms.delete(key);
        card.classList.remove("is-selected");
      } else {
        state.selectedPlatforms.add(key);
        card.classList.add("is-selected");
      }
    });
  });
}

// ---------------- drag & drop wiring ----------------

function wireDropzone(zoneEl, onFiles) {
  zoneEl.addEventListener("dragover", (e) => { e.preventDefault(); zoneEl.classList.add("drag-over"); });
  zoneEl.addEventListener("dragleave", () => zoneEl.classList.remove("drag-over"));
  zoneEl.addEventListener("drop", (e) => {
    e.preventDefault();
    zoneEl.classList.remove("drag-over");
    const files = Array.from(e.dataTransfer.files || []);
    if (files.length) onFiles(files);
  });
}

// ---------------- generate ----------------

function buildEmptyPreviewSkeleton(count = 3) {
  let html = "";
  for (let i = 0; i < count; i++) {
    html += `
      <div class="skeleton-card">
        <div class="skeleton-block skeleton-image"></div>
        <div class="skeleton-block skeleton-line w-90"></div>
        <div class="skeleton-block skeleton-line w-70"></div>
        <div class="skeleton-block skeleton-line w-40"></div>
      </div>`;
  }
  return html;
}

function validateBeforeGenerate() {
  const draft = $("draftText").value.trim();
  if (!draft && state.draftFiles.length === 0) {
    return "Add a draft — paste some text or attach a file.";
  }
  if (state.selectedPlatforms.size === 0) {
    return "Pick at least one platform.";
  }
  if (!state.guidelinesData && !$("useDefaultGuidelines").checked) {
    return "Upload brand guidelines in Brand Assets, or check \u201Cproceed with generic defaults.\u201D";
  }
  return null;
}

async function generate() {
  const errorEl = $("generateError");
  errorEl.hidden = true;

  const problem = validateBeforeGenerate();
  if (problem) {
    errorEl.textContent = problem;
    errorEl.hidden = false;
    return;
  }

  const btn = $("generateBtn");
  btn.disabled = true;
  btn.classList.add("is-loading");

  const deck = $("resultsDeck");
  deck.hidden = false;
  $("resultsNotes").hidden = true;
  $("resultsGrid").innerHTML = buildEmptyPreviewSkeleton(3 * state.selectedPlatforms.size);
  $("platformTabs").innerHTML = "";
  deck.scrollIntoView({ behavior: "smooth", block: "start" });

  const formData = new FormData();
  formData.append("draft", $("draftText").value.trim());
  state.draftFiles.forEach((f) => formData.append("draft_files", f, f.webkitRelativePath || f.name));
  formData.append("platforms", Array.from(state.selectedPlatforms).join(","));
  formData.append("tone", $("toneSelect").value);
  formData.append("audience", $("audienceSelect").value);
  formData.append("include_hashtags", $("includeHashtags").checked);
  formData.append("add_cta", $("addCta").checked);
  formData.append("reference_links", state.references.map((r) => r.url).join("\n"));
  formData.append("use_default_guidelines", $("useDefaultGuidelines").checked);
  if (state.guidelinesData) formData.append("guidelines_json", JSON.stringify(state.guidelinesData));

  try {
    const res = await fetch("/api/generate", { method: "POST", body: formData });
    const raw = await res.text();
    let data;
    try {
      data = JSON.parse(raw);
    } catch {
      // Server returned something that isn't JSON at all (a platform-level
      // timeout/error page, for instance) rather than our API's own JSON
      // error response. Surface a useful message instead of a raw parse error.
      const hint = res.status === 504
        ? "The request timed out — try fewer platforms at once, or try again."
        : `Server returned an unexpected response (status ${res.status}).`;
      throw new Error(hint);
    }
    if (!res.ok) throw new Error(data.error || "Generation failed.");
    state.lastResults = data;
    renderResults(data);
    toast("Posts generated.");
  } catch (e) {
    deck.hidden = true;
    errorEl.textContent = e.message;
    errorEl.hidden = false;
    toast("Generation failed: " + e.message, true);
  } finally {
    btn.disabled = false;
    btn.classList.remove("is-loading");
  }
}

// ---------------- results rendering ----------------

function charMeterHTML(len, max) {
  const segments = 20;
  const ratio = max ? Math.min(len / max, 1.15) : Math.min(len / 500, 1);
  const filled = Math.round(ratio * segments);
  let spans = "";
  for (let i = 0; i < segments; i++) {
    let cls = "";
    if (i < filled) {
      cls = "is-filled";
      if (max && len > max) cls += " is-over";
      else if (ratio > 0.85) cls += " is-near-limit";
    }
    spans += `<span class="${cls}"></span>`;
  }
  return spans;
}

const PLATFORM_MAX_CHARS = { instagram: 2200, linkedin: 3000, twitter: 280, infographic: null };

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function renderOptionCard(platformKey, option, connected) {
  const maxChars = PLATFORM_MAX_CHARS[platformKey];
  const len = option.optimized_text.length;
  const sourceLabel = { reference_link: "from your link", web_search: "web search", branded_card: "brand card" }[option.image_source] || option.image_source;

  const card = document.createElement("div");
  card.className = "option-card";
  card.innerHTML = `
    <div class="option-image-wrap">
      <img src="${option.image_url}" alt="${escapeHtml(option.alt_text || 'Post visual')}" loading="lazy" />
      <span class="image-source-tag src-${option.image_source}">${sourceLabel}</span>
      ${option.visual_style ? `<span class="visual-style-tag">${escapeHtml(option.visual_style)}</span>` : ""}
    </div>
    <div class="option-body">
      <div class="option-meta">
        <span class="option-title">${escapeHtml(option.title || "")}</span>
        <span class="compliance-tag ${option.compliance_passed ? "pass" : "fail"}">${option.compliance_passed ? "on-brand" : "review"}</span>
      </div>
      <span class="option-angle">${(option.angle || "").replace("-", " ")}</span>
      <div class="option-text" contenteditable="true" spellcheck="false">${option.optimized_text}</div>
      <div class="option-hashtags">${(option.hashtags || []).map((h) => `<span class="hashtag-pill">${h.startsWith("#") ? h : "#" + h}</span>`).join("")}</div>
      <div class="char-meter-row">
        <div class="char-meter">${charMeterHTML(len, maxChars)}</div>
        <span class="char-count">${len}${maxChars ? "/" + maxChars : ""}</span>
      </div>
      ${option.notes ? `<div class="option-notes">${escapeHtml(option.notes)}</div>` : ""}

      <details class="option-details">
        <summary>Alternate version, SEO &amp; visual brief</summary>
        ${option.alt_version ? `<div class="detail-row"><b>Alternate version:</b><br>${escapeHtml(option.alt_version)}</div>` : ""}
        ${option.seo_keywords?.length ? `<div class="detail-row"><b>SEO keywords</b></div><div class="seo-keywords">${option.seo_keywords.map((k) => `<span class="seo-pill">${escapeHtml(k)}</span>`).join("")}</div>` : ""}
        ${option.alt_text ? `<div class="detail-row"><b>Image alt text:</b> ${escapeHtml(option.alt_text)}</div>` : ""}
        ${option.visual_concept ? `<div class="detail-row"><b>Suggested visual concept:</b> ${escapeHtml(option.visual_concept)}</div>` : ""}
      </details>

      <div class="option-actions">
        <button class="btn btn-ghost btn-copy" type="button">Copy</button>
        <button class="btn btn-ghost btn-download" type="button">Save image</button>
      </div>
      <div class="option-actions">
        <input type="datetime-local" class="btn btn-ghost schedule-input" style="flex:1.4" />
        <button class="btn btn-secondary btn-schedule" type="button" title="Schedule this post">Schedule</button>
        <button class="btn btn-primary btn-post-now" type="button" style="width:auto;margin-top:0"
          ${connected ? "" : "disabled title=\"Add this platform's credentials in the backend to enable posting\""}>
          Post now
        </button>
      </div>
    </div>
  `;

  card.querySelector(".btn-copy").addEventListener("click", () => {
    const text = card.querySelector(".option-text").innerText;
    const hashtags = (option.hashtags || []).map((h) => (h.startsWith("#") ? h : "#" + h)).join(" ");
    navigator.clipboard.writeText(hashtags ? `${text}\n\n${hashtags}` : text)
      .then(() => toast("Copied to clipboard."))
      .catch(() => toast("Couldn't copy — select and copy manually.", true));
  });

  card.querySelector(".btn-download").addEventListener("click", () => {
    const a = document.createElement("a");
    a.href = option.image_url;
    const mimeMatch = /^data:image\/(\w+);/.exec(option.image_url);
    const ext = mimeMatch ? mimeMatch[1].replace("jpeg", "jpg") : "png";
    a.download = `agent11_${platformKey}_${Date.now()}.${ext}`;
    a.click();
  });

  const doPublish = (scheduleTime) => publishOption(platformKey, card, option, scheduleTime);
  card.querySelector(".btn-post-now").addEventListener("click", () => doPublish(null));
  card.querySelector(".btn-schedule").addEventListener("click", () => {
    const val = card.querySelector(".schedule-input").value;
    if (!val) { toast("Pick a date and time first.", true); return; }
    doPublish(val);
  });

  return card;
}

async function publishOption(platformKey, card, option, scheduleTime) {
  const text = card.querySelector(".option-text").innerText;
  try {
    const res = await fetch("/api/publish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        platform: platformKey,
        text,
        hashtags: option.hashtags || [],
        image_data_url: option.image_url,           // base64 data URI — used directly for Twitter
        image_source_url: option.image_source_url,  // public URL if available — required for Instagram/LinkedIn
        schedule_time: scheduleTime ? new Date(scheduleTime).toISOString() : undefined,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Publish failed.");
    toast(data.scheduled ? "Post scheduled." : "Posted successfully.");
  } catch (e) {
    toast("Couldn't publish: " + e.message, true);
  }
}

function renderResults(data) {
  const grid = $("resultsGrid");
  const tabs = $("platformTabs");
  const notes = $("resultsNotes");
  grid.innerHTML = "";
  tabs.innerHTML = "";

  const allNotes = [...(data.reference_notes || [])];
  if (data.draft_files_skipped?.length) {
    data.draft_files_skipped.forEach((s) => allNotes.push(`Couldn't read ${s.name}: ${s.reason}`));
  }
  if (allNotes.length) {
    notes.hidden = false;
    notes.innerHTML = allNotes.map((n) => `<div>${escapeHtml(n)}</div>`).join("");
  }

  const platformKeys = Object.keys(data.results);
  state.activePlatformTab = platformKeys[0];

  platformKeys.forEach((key) => {
    const platformData = data.results[key];
    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = "platform-tab" + (key === state.activePlatformTab ? " is-active" : "");
    const connected = platformData.publish_configured;
    tab.innerHTML = `<span class="connect-dot ${connected ? "is-connected" : ""}"></span>${platformData.platform_display_name}`;
    tab.addEventListener("click", () => {
      state.activePlatformTab = key;
      document.querySelectorAll(".platform-tab").forEach((t) => t.classList.remove("is-active"));
      tab.classList.add("is-active");
      renderPlatformGrid(key, data);
    });
    tabs.appendChild(tab);
  });

  renderPlatformGrid(state.activePlatformTab, data);
}

function renderPlatformGrid(key, data) {
  const grid = $("resultsGrid");
  grid.innerHTML = "";
  const platformData = data.results[key];
  platformData.options.forEach((option) => {
    grid.appendChild(renderOptionCard(key, option, platformData.publish_configured));
  });
}

// ---------------- wiring ----------------

function init() {
  initNav();
  loadStatus();
  initPlatformCards();

  // Guidelines dropzone
  const guidelinesZone = $("guidelinesDropzone");
  $("guidelinesBrowseBtn").addEventListener("click", () => $("guidelinesFileInput").click());
  $("guidelinesFolderBtn").addEventListener("click", () => $("guidelinesFolderInput").click());
  $("guidelinesFileInput").addEventListener("change", (e) => {
    state.guidelinesFiles.push(...Array.from(e.target.files));
    renderGuidelinesFileList();
    uploadGuidelines();
    e.target.value = "";
  });
  $("guidelinesFolderInput").addEventListener("change", (e) => {
    state.guidelinesFiles.push(...Array.from(e.target.files));
    renderGuidelinesFileList();
    uploadGuidelines();
    e.target.value = "";
  });
  wireDropzone(guidelinesZone, (files) => {
    state.guidelinesFiles.push(...files);
    renderGuidelinesFileList();
    uploadGuidelines();
  });

  // Draft dropzone
  const draftZone = $("draftDropzone");
  $("draftBrowseBtn").addEventListener("click", () => $("draftFileInput").click());
  $("draftFolderBtn").addEventListener("click", () => $("draftFolderInput").click());
  $("draftFileInput").addEventListener("change", (e) => {
    state.draftFiles.push(...Array.from(e.target.files));
    renderDraftFileList();
    e.target.value = "";
  });
  $("draftFolderInput").addEventListener("change", (e) => {
    state.draftFiles.push(...Array.from(e.target.files));
    renderDraftFileList();
    e.target.value = "";
  });
  wireDropzone(draftZone, (files) => {
    state.draftFiles.push(...files);
    renderDraftFileList();
  });

  // Reference links
  $("addReferenceBtn").addEventListener("click", addReferenceLink);
  $("referenceLinkInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); addReferenceLink(); }
  });

  // Generate
  $("generateBtn").addEventListener("click", generate);
}

document.addEventListener("DOMContentLoaded", init);
