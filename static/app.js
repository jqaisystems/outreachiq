/* OutreachIQ - Frontend Logic */

let selectedIndustry = "";
let selectedLimit = 20;
let selectedService = "branding";
let selectedServiceMix = "smart_mix";
let selectedSearchMode = "direct_client";
let selectedMarketPreset = "premium_global";
let servicePresets = {};
let prospectingRecommendations = [];
let prospectingControlData = {};
let industries = [];
let activeFilter = "all";
let currentPage = 1;
const PAGE_SIZE = 60;
let allLeads = [];

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  loadIndustries();
  loadProspectingRecommendations();
  setupLimitChips();
});

async function loadIndustries() {
  const res = await api("/api/industries");
  industries = res.industries || [];
  servicePresets = res.service_presets || servicePresets || {};

  // Search screen chips
  const container = document.getElementById("industry-chips");
  container.innerHTML = industries.map(i =>
    `<button class="chip" data-key="${i.key}" onclick="selectIndustry(this,'${i.key}')">${i.label}</button>`
  ).join("");
  setIndustry(selectedIndustry);
  renderProspectingControls(res);
  renderServicePresets();

  // Pipeline filter dropdown
  const sel = document.getElementById("f-industry");
  if (sel) {
    industries.forEach(i => {
      const opt = document.createElement("option");
      opt.value = i.key;
      opt.textContent = i.label;
      sel.appendChild(opt);
    });
  }

  // Add modal dropdown
  const msel = document.getElementById("m-industry");
  if (msel) {
    msel.innerHTML = '<option value="">Select...</option>' +
      industries.map(i => `<option value="${i.key}">${i.label}</option>`).join("");
  }
}

async function loadProspectingRecommendations() {
  const res = await api("/api/prospecting/recommendations");
  if (res.error) return;
  servicePresets = res.service_presets || servicePresets || {};
  prospectingRecommendations = res.recommendations || [];
  renderProspectingControls(res);
  renderServicePresets();
  renderRecommendations();
  renderMonthlyFitSummary(res.monthly_refresh);
}

function renderProspectingControls(data = {}) {
  prospectingControlData = {
    services: data.services || prospectingControlData.services || Object.keys(servicePresets).map(k => ({key: k, label: serviceLabel(k)})),
    search_modes: data.search_modes || prospectingControlData.search_modes || [
      {key: "direct_client", label: "Direct Client"},
      {key: "agency_partner", label: "Agency Partner"},
    ],
    service_mixes: data.service_mixes || prospectingControlData.service_mixes || defaultServiceMixes(),
    market_presets: data.market_presets || prospectingControlData.market_presets || [
      {key: "premium_global", label: "Premium Global"},
      {key: "europe_first", label: "Europe First"},
      {key: "us_only", label: "US Only"},
    ],
  };
  renderChoiceChips("service-chips", prospectingControlData.services || [], selectedService, selectService);
  renderChoiceChips("mode-chips", prospectingControlData.search_modes || [], selectedSearchMode, selectSearchMode);
  renderChoiceChips("mix-chips", prospectingControlData.service_mixes || [], selectedServiceMix, selectServiceMix);
  renderChoiceChips("market-chips", prospectingControlData.market_presets || [], selectedMarketPreset, selectMarketPreset);
}

function renderChoiceChips(id, items, selected, handler) {
  const el = document.getElementById(id);
  if (!el || !items.length) return;
  el.innerHTML = items.map(item =>
    `<button class="chip ${item.key === selected ? "on" : ""}" data-key="${item.key}">${esc(item.label)}</button>`
  ).join("");
  el.querySelectorAll(".chip").forEach(btn => {
    btn.addEventListener("click", () => handler(btn.dataset.key));
  });
}

function selectService(key) {
  selectedService = key || "branding";
  renderProspectingControls({});
  renderServicePresets();
  renderRecommendations();
}

function selectSearchMode(key) {
  selectedSearchMode = key || "direct_client";
  renderProspectingControls({});
  renderServicePresets();
  renderRecommendations();
}

function selectServiceMix(key) {
  selectedServiceMix = key || "smart_mix";
  renderProspectingControls({});
}

function selectMarketPreset(key) {
  selectedMarketPreset = key || "premium_global";
  renderProspectingControls({});
  renderRecommendations();
}

function serviceLabel(key) {
  return {
    branding: "Branding",
    web_design: "Web Design",
    editorial_print: "Editorial & Print",
    ai_systems: "AI Automation Systems",
  }[key] || key;
}

function modeLabel(key) {
  return key === "agency_partner" ? "Agency Partner" : "Direct Client";
}

function defaultServiceMixes() {
  return [
    {key: "smart_mix", label: "Smart Mix"},
    {key: "branding_only", label: "Branding Only"},
    {key: "branding_web", label: "Branding + Web"},
    {key: "branding_web_print", label: "Branding + Web + Print"},
    {key: "all_services", label: "All Services"},
  ];
}

function serviceMixLabel(key) {
  const found = defaultServiceMixes().find(item => item.key === key);
  return found ? found.label : key;
}

function renderServicePresets() {
  const el = document.getElementById("service-presets");
  if (!el) return;
  const presets = ((servicePresets[selectedService] || {})[selectedSearchMode] || []);
  if (!presets.length) {
    el.innerHTML = `<div class="info-box">No presets yet for this combination.</div>`;
    return;
  }
  el.innerHTML = presets.map((preset, i) => `
    <button class="preset-btn" onclick="applyServicePreset(${i})">
      <strong>${esc(preset.label)}</strong>
      <span>${esc(preset.query)}</span>
    </button>
  `).join("");
}

function renderRecommendations() {
  const el = document.getElementById("recommended-searches");
  if (!el) return;
  const filtered = prospectingRecommendations.filter(r =>
    (!r.service_focus || r.service_focus === selectedService) &&
    (!r.search_mode || r.search_mode === selectedSearchMode) &&
    (!r.market_preset || r.market_preset === selectedMarketPreset)
  ).slice(0, 4);
  const fallback = prospectingRecommendations.filter(r =>
    (!r.service_focus || r.service_focus === selectedService) &&
    (!r.search_mode || r.search_mode === selectedSearchMode)
  ).slice(0, 4);
  const rows = filtered.length ? filtered : fallback;
  if (!rows.length) {
    el.innerHTML = `<div class="info-box">Choose a preset or enter a custom query.</div>`;
    return;
  }
  el.innerHTML = rows.map((r, i) => `
    <button class="recommendation-card" onclick="applyRecommendation(${prospectingRecommendations.indexOf(r)})">
      <strong>${esc(r.query)} in ${esc(r.location || "")}</strong>
      <span>${esc(r.expected_fit || r.reason || "")}</span>
    </button>
  `).join("");
}

function renderMonthlyFitSummary(refresh) {
  const el = document.getElementById("monthly-fit-summary");
  if (!el || !refresh || !refresh.summary) return;
  const summary = refresh.summary;
  const promote = refresh.promote || [];
  const top = promote[0];
  el.style.display = "block";
  el.innerHTML = `
    <strong>Monthly fit:</strong>
    ${summary.hot + summary.warm} hot/warm from ${summary.total} reviewed leads.
    ${top ? `Best current lane: ${esc(top.service_focus_label)} | ${esc(top.search_mode_label)} | ${esc(top.niche)} in ${esc(top.region)}.` : "Keep testing service and market combinations."}
  `;
}

function applyServicePreset(index) {
  const presets = ((servicePresets[selectedService] || {})[selectedSearchMode] || []);
  const preset = presets[index];
  if (!preset) return;
  document.getElementById("custom-query").value = preset.query || "";
  setIndustry(preset.industry || "");
}

function applyRecommendation(index) {
  const rec = prospectingRecommendations[index];
  if (!rec) return;
  selectedService = rec.service_focus || selectedService;
  selectedServiceMix = rec.service_mix || selectedServiceMix;
  selectedSearchMode = rec.search_mode || selectedSearchMode;
  selectedMarketPreset = rec.market_preset || selectedMarketPreset;
  document.getElementById("custom-query").value = rec.query || "";
  if (rec.location) document.getElementById("search-location").value = rec.location;
  setIndustry(rec.industry || industryForQuery(rec.query));
  renderProspectingControls({});
  renderServicePresets();
  renderRecommendations();
}

function industryForQuery(query) {
  const q = (query || "").toLowerCase();
  for (const modes of Object.values(servicePresets || {})) {
    for (const presets of Object.values(modes || {})) {
      const match = (presets || []).find(p => (p.query || "").toLowerCase() === q);
      if (match) return match.industry || "";
    }
  }
  return "";
}

function setIndustry(key) {
  selectedIndustry = key || "";
  document.querySelectorAll("#industry-chips .chip").forEach(c => {
    c.classList.toggle("on", !!selectedIndustry && c.dataset.key === selectedIndustry);
  });
}

function setupLimitChips() {
  document.querySelectorAll("#limit-chips .chip").forEach(chip => {
    chip.addEventListener("click", () => {
      document.querySelectorAll("#limit-chips .chip").forEach(c => c.classList.remove("on"));
      chip.classList.add("on");
      selectedLimit = parseInt(chip.dataset.val);
    });
  });
}

// ---------------------------------------------------------------------------
// Tab navigation
// ---------------------------------------------------------------------------

function showTab(name) {
  document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
  document.getElementById("s-" + name).classList.add("active");
  document.querySelectorAll(".nav-link").forEach(l => l.classList.remove("active"));
  const navBtn = document.querySelector(`.nav-link[data-screen="${name}"]`);
  if (navBtn) navBtn.classList.add("active");

  if (name === "pipeline") {
    loadLeads();
  } else if (name === "stats") {
    loadStats();
  }
}

// ---------------------------------------------------------------------------
// Industry chip selection (Search tab)
// ---------------------------------------------------------------------------

function selectIndustry(el, key) {
  document.querySelectorAll("#industry-chips .chip").forEach(c => c.classList.remove("on"));
  if (selectedIndustry === key) {
    selectedIndustry = "";
  } else {
    el.classList.add("on");
    selectedIndustry = key;
  }
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

async function doSearch() {
  const location = document.getElementById("search-location").value.trim();
  const customQuery = document.getElementById("custom-query").value.trim();
  const errEl = document.getElementById("search-err");
  const successEl = document.getElementById("search-success");
  errEl.style.display = "none";
  successEl.style.display = "none";

  if (!location) {
    errEl.textContent = "Please enter a target location.";
    errEl.style.display = "block";
    return;
  }
  if (!selectedIndustry && !customQuery) {
    errEl.textContent = "Please select an industry or enter a custom query.";
    errEl.style.display = "block";
    return;
  }

  const btn = document.getElementById("search-btn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span> Searching...';

  const body = {
    industry: selectedIndustry,
    location: location,
    limit: selectedLimit,
    service_focus: selectedService,
    service_mix: selectedServiceMix,
    search_mode: selectedSearchMode,
    market_preset: selectedMarketPreset,
    exclude_motion: document.getElementById("exclude-motion") ? document.getElementById("exclude-motion").checked : true,
    partner_lane: selectedSearchMode === "agency_partner",
  };
  if (customQuery) body.query = customQuery;

  const res = await api("/api/search", "POST", body);
  btn.disabled = false;
  btn.innerHTML = "Search Google Maps";

  if (res.error) {
    errEl.textContent = res.error;
    errEl.style.display = "block";
    return;
  }

  successEl.innerHTML = `Found <strong>${res.found}</strong> businesses. <strong>${res.added}</strong> new leads added.` +
    (res.duplicates > 0 ? ` (${res.duplicates} duplicates skipped)` : "") +
    (res.filtered_motion > 0 ? ` (${res.filtered_motion} motion-focused result${res.filtered_motion > 1 ? "s" : ""} filtered)` : "") +
    `<br><small style="opacity:.75">${esc(res.service_focus_label || serviceLabel(selectedService))} | ${esc(res.service_mix_label || serviceMixLabel(selectedServiceMix))} | ${esc(res.search_mode_label || modeLabel(selectedSearchMode))}</small>` +
    (res.secondary_service_labels && res.secondary_service_labels.length ? `<br><small style="opacity:.75">Supporting: ${esc(res.secondary_service_labels.join(", "))}</small>` : "") +
    (res.note ? `<br><small style="opacity:.7">${res.note}</small>` : "") +
    ` <a href="#" onclick="showTab('pipeline');return false;">View pipeline &rarr;</a>`;
  successEl.style.display = "block";
  toast(`${res.added} new leads added`);
}

// ---------------------------------------------------------------------------
// Pipeline filter tabs
// ---------------------------------------------------------------------------

function setFilter(filter, el) {
  const previousFilter = activeFilter;
  activeFilter = filter;
  currentPage = 1;
  document.querySelectorAll(".ftab").forEach(b => b.classList.remove("active"));
  if (el) el.classList.add("active");
  const sortEl = document.getElementById("f-sort");
  if (sortEl && filter === "favorites") {
    sortEl.value = "favorited_at";
  } else if (sortEl && previousFilter === "favorites" && sortEl.value === "favorited_at") {
    sortEl.value = "found_at";
  }
  loadLeads();
}

// ---------------------------------------------------------------------------
// Leads table
// ---------------------------------------------------------------------------

async function loadLeads() {
  const params = new URLSearchParams();
  const isReviewQueue = activeFilter === "tone_review";
  const isFavorites = activeFilter === "favorites";
  const isMissingEmail = activeFilter === "missing_email";

  // Apply active filter
  if (isMissingEmail) {
    params.set("missing_email", "1");
  } else if (activeFilter !== "all" && !isReviewQueue && !isFavorites) {
    // hot/warm/cold are both priority and status in our system
    if (["hot", "warm", "cold"].includes(activeFilter)) {
      params.set("priority", activeFilter);
    } else {
      params.set("status", activeFilter);
    }
  }

  const industry = document.getElementById("f-industry") ? document.getElementById("f-industry").value : "";
  const q = document.getElementById("f-search") ? document.getElementById("f-search").value : "";
  const sort = document.getElementById("f-sort") ? document.getElementById("f-sort").value : "found_at";

  if (industry) params.set("industry", industry);
  if (q) params.set("q", q);
  if (sort) params.set("sort", sort);
  params.set("order", sort === "name" ? "asc" : "desc");

  const endpoint = isReviewQueue ? "/api/email/review-queue?" : isFavorites ? "/api/favorites?" : "/api/leads?";
  const res = await api(endpoint + params.toString());
  const tbody = document.getElementById("leads-tbody");
  const empty = document.getElementById("leads-empty");

  renderNextStep();
  renderReviewQueueSummary(isReviewQueue ? res : null);
  renderFavoritesSummary(isFavorites ? res : null);

  if (!res.leads || res.leads.length === 0) {
    tbody.innerHTML = "";
    empty.textContent = isReviewQueue
      ? "No unsent drafts need review."
      : isFavorites
        ? "No favorites yet. Click a star on any lead to save it here."
      : "No prospects here. Run a search to get started.";
    empty.style.display = "block";
    renderPagination(0);
    return;
  }

  allLeads = res.leads;
  empty.style.display = "none";

  // Clamp current page to valid range
  const totalPages = Math.ceil(allLeads.length / PAGE_SIZE);
  if (currentPage > totalPages) currentPage = totalPages;
  if (currentPage < 1) currentPage = 1;

  renderCurrentPageLeads();
}

function renderLeadRows(leads) {
  return leads.map(renderLeadRow).join("");
}

function renderCurrentPageLeads() {
  const tbody = document.getElementById("leads-tbody");
  if (!tbody) return;

  const totalPages = Math.ceil(allLeads.length / PAGE_SIZE);
  if (currentPage > totalPages) currentPage = totalPages;
  if (currentPage < 1) currentPage = 1;

  const start = (currentPage - 1) * PAGE_SIZE;
  const pageLeads = allLeads.slice(start, start + PAGE_SIZE);

  tbody.innerHTML = renderLeadRows(pageLeads);
  renderPagination(allLeads.length);
}

function updateVisibleLead(updatedLead) {
  if (!updatedLead || !updatedLead.id) return false;
  const index = allLeads.findIndex(lead => lead.id === updatedLead.id);
  if (index === -1) return false;
  allLeads[index] = { ...allLeads[index], ...updatedLead };
  renderCurrentPageLeads();
  return true;
}

function isSentOrLater(lead) {
  return ["sent", "follow-up", "replied", "meeting", "converted"].includes(lead.status) || !!lead.date_sent;
}

function renderLeadRow(lead) {
  const scoreColor = lead.priority === "hot" ? "#DC2626" :
                     lead.priority === "warm" ? "#D97706" :
                     lead.priority === "cold" ? "#2563EB" : "#999";

  const priorityBadge = lead.priority
    ? `<span class="badge ${lead.priority}">${lead.priority}</span>`
    : '<span class="badge unscored">unscored</span>';

  const statusBadge = `<span class="badge ${lead.status || 'unscored'}">${lead.status || 'unscored'}</span>`;
  const reviewBadge = lead.review_status ? renderToneBadge({status: lead.review_status}) : renderToneBadge(lead.tone_audit);
  const sentClass = isSentOrLater(lead) ? " sent-row" : "";
  const sentTitle = isSentOrLater(lead) && lead.date_sent ? ` title="Sent ${esc(lead.date_sent)}"` : "";

  return `<tr class="lead-row${sentClass}"${sentTitle} onclick="openDetail('${lead.id}')">
    <td class="score-cell" style="color:${scoreColor}">${lead.score || '-'}</td>
    <td>${priorityBadge}</td>
    <td style="font-weight:500;overflow:hidden;text-overflow:ellipsis;">
      <div class="lead-company-line">
        ${renderFavoriteButton(lead)}
        <span class="brand-tip" data-tip="${esc(lead.brand_gap || 'No brand gap recorded yet.')}">${esc(lead.name)}</span>
        ${lead.enrichment_failed ? `<span class="tone-flag risky" title="Enrichment found no website summary, email, or company data. Likely a dud lead.">enrichment failed</span>` : ''}
        ${lead.approved_variant !== null && lead.approved_variant !== undefined && lead.status !== 'sent' ? `<span class="prospect-tag partner" title="Approved and queued to send">approved ${String.fromCharCode(65 + Number(lead.approved_variant))}</span>` : ''}
      </div>
      ${renderFavoriteMeta(lead)}
      ${renderLeadReviewFlags(lead)}
    </td>
    <td style="color:#666;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
      ${esc(lead.niche || lead.industry)}
      ${renderProspectTags(lead)}
    </td>
    <td style="color:#666;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(lead.city || '-')}</td>
    <td><div class="status-stack">${statusBadge}${reviewBadge}</div></td>
    <td class="actions-cell" onclick="event.stopPropagation()">
      ${activeFilter === 'tone_review' ? `<button class="btn navy xs" onclick="openDetail('${lead.id}')">Review</button>` : ''}
      ${activeFilter !== 'tone_review' && lead.priority && lead.priority !== 'skip' ? `<button class="btn gold xs" onclick="copyWriteEmailPrompt(event, '${lead.id}')">Write Email</button>` : ''}
      ${(lead.status === 'hot' || lead.status === 'warm' || lead.status === 'cold' || lead.status === 'drafted') ?
        `<button class="btn green xs" style="margin-left:4px;" onclick="markSent(event, '${lead.id}')">Mark Sent</button>` : ''}
      ${lead.status === 'sent' ? `<button class="btn outline xs" style="margin-left:4px;" onclick="undoSentFromRow(event, '${lead.id}')">Undo Sent</button>` : ''}
    </td>
  </tr>`;
}

function renderProspectTags(lead) {
  const tags = [];
  if (lead.service_focus_label) {
    tags.push(`<span class="prospect-tag service">${esc(lead.service_focus_label)}</span>`);
  }
  if (lead.service_mix_label) {
    tags.push(`<span class="prospect-tag mix">${esc(lead.service_mix_label)}</span>`);
  }
  if (lead.search_mode === "agency_partner" || lead.partner_lane) {
    tags.push(`<span class="prospect-tag partner">Partner</span>`);
  }
  return tags.length ? `<div class="prospect-tags">${tags.join("")}</div>` : "";
}

function renderLeadReviewFlags(lead) {
  const flags = (lead.review_flags || []).slice(0, 3);
  if (!flags.length) return "";
  return `<div class="lead-review-flags">
    ${flags.map(f => `<span class="tone-flag ${esc(f.severity || 'needs_review')}" title="${esc(f.detail || '')}">${esc(f.label || f.code)}</span>`).join("")}
  </div>`;
}

function renderFavoriteButton(lead, mode = "row") {
  const active = !!lead.is_favorite;
  const title = active ? "Remove from favorites" : "Add to favorites";
  const icon = active ? "&#9733;" : "&#9734;";
  return `<button class="favorite-star ${active ? 'on' : ''} ${mode === 'detail' ? 'detail' : ''}"
    title="${title}" aria-label="${title}"
    onclick="toggleFavorite(event, '${lead.id}', ${active ? 'true' : 'false'})">${icon}</button>`;
}

function renderFavoriteMeta(lead) {
  if (!lead.is_favorite) return "";
  const parts = [];
  if (lead.favorite_order) parts.push(`#${lead.favorite_order}`);
  if (lead.favorited_at) parts.push(formatShortDate(lead.favorited_at));
  const note = (lead.favorite_note || "").trim();
  return `<div class="favorite-row-meta">
    ${parts.length ? `<span>${esc(parts.join(" | "))}</span>` : ""}
    ${note ? `<em>${esc(note)}</em>` : ""}
  </div>`;
}

function renderFavoritesSummary(res) {
  const el = document.getElementById("favorites-summary");
  if (!el) return;
  if (!res) {
    el.innerHTML = "";
    return;
  }
  const count = res.count || (res.leads || []).length || 0;
  el.innerHTML = `
    <div class="favorites-summary">
      <div>
        <strong>Favorites</strong>
        <span>Saved leads for revision or special follow-up, ordered by when you added them.</span>
      </div>
      <div class="favorites-summary-count">${count} saved</div>
    </div>
  `;
}

function renderReviewQueueSummary(res) {
  const el = document.getElementById("review-queue-summary");
  if (!el) return;
  if (!res) {
    el.innerHTML = "";
    return;
  }
  const counts = res.counts || {};
  el.innerHTML = `
    <div class="review-queue-summary">
      <div class="review-queue-title">
        <strong>Review Queue</strong><br>
        Local draft QA before sending. No API usage.
      </div>
      <div class="review-queue-counts">
        <span class="review-count-chip">${counts.total || 0} total</span>
        <span class="review-count-chip">${counts.risky || 0} risky</span>
        <span class="review-count-chip">${counts.missing_email || 0} missing email</span>
        <span class="review-count-chip">${counts.bad_greeting || 0} bad greeting</span>
        <span class="review-count-chip">${counts.old_single_draft || 0} old draft</span>
        <button class="repair-action-btn strong" onclick="bulkRepairReviewQueue()">Auto Repair All</button>
      </div>
    </div>
  `;
}

async function bulkRepairReviewQueue() {
  if (!confirm("Create data/written.json with local repairs for every unsent draft in Needs Review? This does not call AI or paid APIs.")) return;
  const res = await api("/api/email/bulk-repair", "POST", {});
  if (res.error) return toast(res.error);
  toast(`${res.count} repaired drafts written. Click Import Emails.${res.missing_email ? ` ${res.missing_email} still missing email.` : ""}`);
}

function renderPagination(total) {
  const container = document.getElementById("pagination");
  if (!container) return;

  const totalPages = Math.ceil(total / PAGE_SIZE);
  if (totalPages <= 1) {
    container.innerHTML = "";
    return;
  }

  const start = (currentPage - 1) * PAGE_SIZE + 1;
  const end = Math.min(currentPage * PAGE_SIZE, total);

  let btns = "";
  btns += `<button class="btn outline xs" ${currentPage <= 1 ? 'disabled' : ''} onclick="goPage(${currentPage - 1})">&laquo; Prev</button>`;
  for (let i = 1; i <= totalPages; i++) {
    btns += `<button class="btn ${i === currentPage ? 'navy' : 'outline'} xs" onclick="goPage(${i})">${i}</button>`;
  }
  btns += `<button class="btn outline xs" ${currentPage >= totalPages ? 'disabled' : ''} onclick="goPage(${currentPage + 1})">Next &raquo;</button>`;

  container.innerHTML = `<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
    ${btns}
    <span style="color:#666;font-size:12px;margin-left:8px;">Showing ${start}-${end} of ${total}</span>
  </div>`;
}

function goPage(page) {
  currentPage = page;
  const tbody = document.getElementById("leads-tbody");
  const start = (currentPage - 1) * PAGE_SIZE;
  const pageLeads = allLeads.slice(start, start + PAGE_SIZE);

  tbody.innerHTML = renderLeadRows(pageLeads);

  renderPagination(allLeads.length);
  // Scroll to top of table
  document.getElementById("leads-tbody")?.closest("table")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ---------------------------------------------------------------------------
// Next Step guide (pipeline tab)
// ---------------------------------------------------------------------------

// Compact pipeline funnel bar: Total / Hot / Warm / Cold / Drafted / Approved / Sent / Replied / Meeting / Converted.
// Each chip (except Approved) filters the list by activating the matching .ftab.
function renderPipelineStats(stats) {
  const el = document.getElementById("pipeline-stats");
  if (!el) return;
  if (!stats || stats.error) { el.innerHTML = ""; return; }
  const approved = (stats.sending && stats.sending.approved_pending) || 0;
  _approvedPending = approved;
  const chips = [
    { label: "Total",     value: stats.total     || 0, cls: "total",     filter: "all" },
    { label: "Hot",       value: stats.hot       || 0, cls: "hot",       filter: "hot" },
    { label: "Warm",      value: stats.warm      || 0, cls: "warm",      filter: "warm" },
    { label: "Cold",      value: stats.cold      || 0, cls: "cold",      filter: "cold" },
    { label: "Drafted",   value: stats.drafted   || 0, cls: "drafted",   filter: "drafted" },
    { label: "Approved",  value: approved,             cls: "approved",  filter: null },
    { label: "Sent",      value: stats.sent      || 0, cls: "sent",      filter: "sent" },
    ...(stats.bounced ? [{ label: "Bounced", value: stats.bounced, cls: "bounced", filter: "bounced" }] : []),
    ...(stats.follow_up ? [{ label: "Follow-up", value: stats.follow_up, cls: "followup", filter: "follow-up" }] : []),
    { label: "Replied",   value: stats.replied   || 0, cls: "replied",   filter: "replied" },
    { label: "Meeting",   value: stats.meeting   || 0, cls: "meeting",   filter: "meeting" },
    { label: "Converted", value: stats.converted || 0, cls: "converted", filter: "converted" },
  ];
  el.innerHTML = chips.map(c => `
    <div class="pstat ${c.cls}${c.filter ? " clickable" : ""}"${c.filter ? ` onclick="filterFromStat('${c.filter}')" title="Show ${esc(c.label)} leads"` : ""}>
      <div class="pstat-label">${esc(c.label)}</div>
      <div class="pstat-val">${c.value}</div>
    </div>
  `).join("");
}

// Apply a filter from a stat chip by activating the matching tab.
function filterFromStat(filter) {
  const tab = document.querySelector(`.ftab[data-filter="${filter}"]`);
  setFilter(filter, tab);
}

async function renderNextStep() {
  const el = document.getElementById("next-step-guide");
  if (!el) return;

  const stats = await api("/api/stats");
  renderPipelineStats(stats);

  if (activeFilter === "favorites") {
    el.innerHTML = "";
    return;
  }

  if (stats.error) { el.innerHTML = ""; return; }

  const unscored  = stats.unscored  || 0;
  const hot       = stats.hot       || 0;
  const warm      = stats.warm      || 0;
  const cold      = stats.cold      || 0;
  const drafted   = stats.drafted   || 0;
  const sent      = stats.sent      || 0;
  const replied   = stats.replied   || 0;
  const meeting   = stats.meeting   || 0;
  const converted = stats.converted || 0;
  const total     = stats.total     || 0;

  const scored         = hot + warm + cold;
  const past_draft     = sent + (stats.follow_up || 0) + replied + meeting + converted;
  const needs_email    = scored - drafted - past_draft;

  let guide = null;

  if (total === 0) {
    guide = {
      label: "Get started",
      steps: [
        { n: "1", text: 'Go to <strong>Search</strong> tab', action: `onclick="showTab('search')"`, btn: "Open Search" },
        { n: "2", text: "Pick an industry and location" },
        { n: "3", text: "Click <strong>Search Google Maps</strong>" },
      ],
    };
  } else if (unscored > 0) {
    guide = {
      label: `${unscored} lead${unscored > 1 ? "s" : ""} need scoring`,
      steps: [
        { n: "1", text: "Click <strong>Export for Scoring</strong> below", action: `onclick="doScoreExport()"`, btn: "Export for Scoring" },
        { n: "2", text: 'Ask Claude Code: <code>"score my prospects"</code>' },
        { n: "3", text: "Click <strong>Import Scores</strong> below", action: `onclick="doScoreImport()"`, btn: "Import Scores" },
      ],
    };
  } else if (needs_email > 0) {
    guide = {
      label: `${needs_email} lead${needs_email > 1 ? "s" : ""} need emails written`,
      steps: [
        { n: "1", text: "Click <strong>Export for Email Writing</strong> below", action: `onclick="doEmailExport()"`, btn: "Export for Emails" },
        { n: "2", text: 'Ask Claude Code: <code>"write emails"</code>' },
        { n: "3", text: "Click <strong>Import Emails</strong> below", action: `onclick="doEmailImport()"`, btn: "Import Emails" },
      ],
    };
  } else if (drafted > 0) {
    guide = {
      label: `${drafted} email${drafted > 1 ? "s" : ""} ready to send`,
      steps: [
        { n: "1", text: "Open a <strong>Drafted</strong> lead from the table" },
        { n: "2", text: "Review the email, then click <strong>Gmail</strong> or <strong>Hotmail</strong>" },
        { n: "3", text: "Come back and click <strong>Mark Sent</strong>" },
      ],
    };
  } else if (replied > 0 || meeting > 0) {
    guide = {
      label: "Follow up on active leads",
      steps: [
        { n: "1", text: `You have <strong>${replied}</strong> replied and <strong>${meeting}</strong> in meeting` },
        { n: "2", text: "Open each lead and update the status" },
        { n: "3", text: "Mark as <strong>Meeting</strong> or <strong>Converted</strong> as they progress" },
      ],
    };
  }

  if (!guide) { el.innerHTML = ""; return; }

  el.innerHTML = `
    <div style="border-left:3px solid #C4A84A;background:#FDFAF4;padding:12px 16px;border-radius:0 4px 4px 0;display:flex;align-items:flex-start;gap:16px;flex-wrap:wrap;">
      <div style="min-width:120px;">
        <div style="font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#999;font-family:-apple-system,sans-serif;margin-bottom:2px;">Next Step</div>
        <div style="font-size:12px;font-weight:600;color:#5A4A2A;font-family:-apple-system,sans-serif;">${guide.label}</div>
      </div>
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;flex:1;">
        ${guide.steps.map((s, i) => `
          <div style="display:flex;align-items:center;gap:8px;">
            <div style="display:flex;align-items:center;gap:6px;">
              <span style="background:#C4A84A;color:#fff;border-radius:50%;width:18px;height:18px;display:inline-flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;flex-shrink:0;font-family:-apple-system,sans-serif;">${s.n}</span>
              <span style="font-size:12px;color:#444;font-family:-apple-system,sans-serif;line-height:1.4;">${s.text}</span>
            </div>
            ${i < guide.steps.length - 1 ? '<span style="color:#CCC;font-size:14px;">&#8250;</span>' : ""}
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Stats tab
// ---------------------------------------------------------------------------

async function loadStats() {
  const [stats, usage] = await Promise.all([
    api("/api/stats"),
    api("/api/usage"),
  ]);

  // Funnel
  const funnel = document.getElementById("stats-funnel");
  const stages = [
    { label: "Total", value: stats.total, color: "#111" },
    { label: "Scored", value: stats.scored, color: "#A8832A" },
    { label: "Drafted", value: stats.drafted, color: "#065F46" },
    { label: "Sent", value: stats.sent, color: "#2D6A4F" },
    { label: "Replied", value: stats.replied, color: "#7C3AED" },
    { label: "Meeting", value: stats.meeting, color: "#D97706" },
    { label: "Converted", value: stats.converted, color: "#A8832A" },
  ];
  funnel.innerHTML = stages.map((s, i) => `
    <div class="funnel-stage">
      <div class="f-num" style="color:${s.color}">${s.value || 0}</div>
      <div class="f-label">${s.label}</div>
      ${i < stages.length - 1 ? '<div class="f-arrow">&#8250;</div>' : ""}
    </div>
  `).join("");

  // Priority breakdown
  const cards = document.getElementById("priority-cards");
  cards.innerHTML = [
    { cls: "hot",  label: "Hot",  val: stats.hot  },
    { cls: "warm", label: "Warm", val: stats.warm },
    { cls: "cold", label: "Cold", val: stats.cold },
    { cls: "skip", label: "Skip", val: stats.skip },
  ].map(p => `
    <div class="priority-card ${p.cls}">
      <div class="pc-num">${p.val || 0}</div>
      <div class="pc-label">${p.label}</div>
    </div>
  `).join("");

  // API key status
  const apiSection = document.getElementById("api-status-section");
  if (stats.api_keys) {
    const keyCards = Object.entries(stats.api_keys).map(([k, v]) => {
      const isOk = v === "OK";
      return `<div class="api-key-card">
        <div class="key-name">${k}</div>
        <div class="key-val ${isOk ? '' : 'missing'}">${v}</div>
      </div>`;
    }).join("");
    apiSection.innerHTML = `
      <div class="lbl" style="margin-bottom:12px;">API Keys</div>
      <div class="api-key-status">${keyCards}</div>
    `;
  }

  const enrichmentSection = document.getElementById("enrichment-status-section");
  const enrichment = stats.enrichment || {};
  const missing = stats.enrichment_missing || {};
  enrichmentSection.innerHTML = `
    <div class="lbl" style="margin-bottom:12px;">Enrichment Completeness</div>
    <div class="api-key-status">
      ${["complete", "partial", "missing"].map(k => `
        <div class="api-key-card">
          <div class="key-name">${k}</div>
          <div class="key-val">${enrichment[k] || 0}</div>
        </div>
      `).join("")}
    </div>
    <div class="usage-note">Most common missing fields: ${
      Object.entries(missing).sort((a,b) => b[1] - a[1]).slice(0, 6)
        .map(([k,v]) => `${esc(k.replaceAll("_", " "))}: ${v}`).join(" · ") || "none"
    }</div>
  `;

  const usageSection = document.getElementById("usage-status-section");
  usageSection.innerHTML = renderUsageSection(usage);

  renderSendingSection(stats.sending || {}, (stats.api_keys || {}).gmail, stats.bounced || 0);
  renderVariantPerfSection(stats.variant_performance || {});
}

// ---------------------------------------------------------------------------
// Sending & safety panel (Part 4)
// ---------------------------------------------------------------------------

let _lastFollowUpCount = 0;

async function renderSendingSection(sending, gmailStatus, bouncedCount) {
  const el = document.getElementById("sending-section");
  if (!el) return;
  bouncedCount = bouncedCount || 0;
  const fq = await api("/api/email/follow-up-queue");
  _lastFollowUpCount = fq.count || 0;
  const aq = await api("/api/email/approved-count");
  const approvedLeads = (aq && Array.isArray(aq.leads)) ? aq.leads : [];
  const paused = !!sending.kill_switch;
  const pending = (aq && typeof aq.count === "number") ? aq.count : (sending.approved_pending || 0);
  _approvedPending = pending;
  const sentToday = sending.sent_today || 0;
  const cap = sending.daily_cap || 0;
  const gmailOk = gmailStatus === "OK";
  const followupsReady = sending.followups_ready || 0;

  el.innerHTML = `
    <div class="lbl" style="margin-bottom:12px;">Sending &amp; Safety</div>
    <div class="card" style="padding:18px;display:flex;flex-wrap:wrap;gap:14px;align-items:center;">
      <div class="api-key-card"><div class="key-name">Approved & queued</div><div class="key-val">${pending}</div></div>
      <div class="api-key-card"><div class="key-name">Sent today</div><div class="key-val">${sentToday} / ${cap}</div></div>
      <div class="api-key-card"><div class="key-name">Follow-up due</div><div class="key-val">${_lastFollowUpCount}</div></div>
      ${bouncedCount ? `<div class="api-key-card"><div class="key-name">Bounced</div><div class="key-val" style="color:#B91C1C;">${bouncedCount}</div></div>` : ""}
      <div class="api-key-card"><div class="key-name">Gmail</div><div class="key-val ${gmailOk ? '' : 'missing'}">${esc(gmailStatus || 'unknown')}</div></div>
      <div style="flex:1;"></div>
      <button class="btn ${paused ? 'green' : 'outline'} sm" onclick="toggleKillSwitch(${paused})">
        ${paused ? "&#9658; Resume sending" : "&#10073;&#10073; Pause (kill switch)"}
      </button>
      <button class="btn navy sm" onclick="checkReplies()">Check replies</button>
      ${bouncedCount ? `<button class="btn outline sm" onclick="requeueBounced()" title="Return bounced leads to Drafted for re-approval and resend">Requeue bounced (${bouncedCount})</button>` : ""}
      <button id="send-approved-btn" class="btn gold sm" ${(!gmailOk || pending === 0 || paused || sendingApproved) ? "disabled" : ""} onclick="sendApproved()">
        ${sendingApproved ? "Sending..." : `Send Approved Emails (${pending})`}
      </button>
    </div>
    ${(_lastFollowUpCount || followupsReady) ? `
      <div class="card" style="padding:12px 18px;margin-top:10px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;">
        <span style="font-size:12px;font-weight:600;color:#0E7490;">Follow-ups</span>
        <span class="usage-note" style="margin:0;">${_lastFollowUpCount} due &middot; ${followupsReady} drafted &amp; ready</span>
        <div style="flex:1;"></div>
        <button class="btn outline sm" ${_lastFollowUpCount ? "" : "disabled"} onclick="exportFollowups()" title="Write data/to_followup.json for Claude">Export follow-ups (${_lastFollowUpCount})</button>
        <button class="btn navy sm" onclick="importFollowups()" title="Import data/followup_written.json">Import follow-ups</button>
        <button class="btn gold sm" ${(!gmailOk || !followupsReady || paused) ? "disabled" : ""} onclick="sendFollowups()">Send follow-ups (${followupsReady})</button>
      </div>` : ""}
    ${paused ? `<div class="usage-note" style="color:#DC2626;">Sending is paused. No emails will go out until you resume.</div>` : ""}
    ${!gmailOk ? `<div class="usage-note">Gmail not connected. Run <code>python authorize_gmail.py</code> once, then reload.</div>` : ""}
    ${approvedLeads.length ? `
      <div class="card" style="padding:14px;margin-top:12px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
          <strong>Approved emails (${approvedLeads.length})</strong>
          <span class="usage-note">These send when you click "Send Approved Emails". Remove any you do not want sent.</span>
        </div>
        <div style="max-height:300px;overflow:auto;display:flex;flex-direction:column;gap:6px;">
          ${approvedLeads.map(l => `
            <div style="display:flex;align-items:center;gap:10px;padding:8px 10px;border:1px solid #ececec;border-radius:8px;">
              <span class="prospect-tag partner" title="Approved variant">${esc(l.variant_label || '?')}</span>
              <div style="flex:1;min-width:0;">
                <div style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(l.name || l.id)}</div>
                <div class="usage-note" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(l.contact_email || 'no email')}${l.subject ? ' &middot; ' + esc(l.subject) : ''}</div>
              </div>
              <button class="btn outline xs" onclick="openDetail('${l.id}')">Open</button>
              <button class="btn outline xs" onclick="unapproveFromQueue('${l.id}')" title="Remove this email from the approved send queue">Remove</button>
            </div>
          `).join("")}
        </div>
      </div>
    ` : ""}
    <div id="send-progress"></div>
  `;
}

async function toggleKillSwitch(currentlyPaused) {
  const res = await api("/api/email/kill-switch", "POST", { paused: !currentlyPaused });
  if (res.error) { toast(res.error); return; }
  toast(res.paused ? "Sending paused" : "Sending resumed");
  loadStats();
}

let sendingApproved = false;

async function sendApproved() {
  if (sendingApproved) return;  // guard against double-trigger (a cause of duplicate sends)
  if (!window.confirm("Send all approved emails through Gmail now? They go out throttled, one at a time.")) return;
  sendingApproved = true;
  const btn = document.getElementById("send-approved-btn");
  if (btn) { btn.disabled = true; btn.textContent = "Sending..."; }
  const prog = document.getElementById("send-progress");
  if (prog) prog.innerHTML = `<div class="usage-note">Sending... you can Pause to stop mid-batch.</div>`;
  try {
    const res = await api("/api/email/send-approved", "POST", {});
    if (res.error) { toast(res.error); if (prog) prog.innerHTML = `<div class="usage-note" style="color:#DC2626;">${esc(res.error)}</div>`; return; }
    toast(`Sent ${res.sent}, skipped ${res.skipped}${res.cap_reached ? " (daily cap reached)" : ""}`);
    if (prog) {
      const rows = (res.results || []).map(r =>
        `<div style="font-size:12px;color:${r.result === 'sent' ? '#2D6A4F' : '#999'};">
          ${esc(r.name || r.id)}: <strong>${esc(r.result)}</strong>${r.reason ? ` (${esc(r.reason)})` : ""}
        </div>`).join("");
      prog.innerHTML = `<div class="card" style="padding:12px;margin-top:10px;max-height:240px;overflow:auto;">${rows || "No results"}</div>`;
    }
  } finally {
    sendingApproved = false;
    loadLeads();
    loadStats();
    refreshApprovedStat();
  }
}

async function checkReplies() {
  toast("Checking Gmail for replies...");
  const res = await api("/api/email/check-replies", "POST", {});
  if (res.error) { toast(res.error); return; }
  const parts = [];
  if (res.new_replies) parts.push(`${res.new_replies} new repl${res.new_replies === 1 ? "y" : "ies"}`);
  if (res.new_bounces) parts.push(`${res.new_bounces} bounce${res.new_bounces === 1 ? "" : "s"}`);
  toast(parts.length ? parts.join(", ") + " found" : "No new replies or bounces");
  if (res.new_replies || res.new_bounces) { loadLeads(); loadStats(); }
}

async function exportFollowups() {
  const res = await api("/api/email/export-followups", "POST", {});
  if (res.error) { toast(res.error); return; }
  toast(res.exported
    ? `${res.exported} lead${res.exported === 1 ? "" : "s"} exported to data/to_followup.json. Ask Claude Code: "write follow-ups"`
    : "No follow-ups due for export");
}

async function importFollowups() {
  const res = await api("/api/email/import-followups", "POST", {});
  if (res.error) { toast(res.error); return; }
  let msg = `${res.imported} follow-up draft${res.imported === 1 ? "" : "s"} imported`;
  if (res.warnings && res.warnings.length) msg += `; ${res.warnings.length} with issues (they will be skipped at send until fixed)`;
  toast(msg);
  loadStats();
}

async function sendFollowups() {
  if (!window.confirm("Send all drafted follow-ups as threaded Gmail replies now? They go out throttled, one at a time.")) return;
  const res = await api("/api/email/send-followups", "POST", {});
  if (res.error) { toast(res.error); return; }
  toast(`Follow-ups: sent ${res.sent}, skipped ${res.skipped}${res.cap_reached ? " (daily cap reached)" : ""}`);
  loadLeads();
  loadStats();
}

async function requeueBounced() {
  if (!window.confirm("Return all bounced leads to Drafted so they can be re-approved and resent? Check their contact emails before approving again.")) return;
  const res = await api("/api/email/requeue-bounced", "POST", {});
  if (res.error) { toast(res.error); return; }
  toast(res.requeued ? `${res.requeued} bounced lead${res.requeued === 1 ? "" : "s"} returned to Drafted` : "No bounced leads to requeue");
  if (res.requeued) { loadLeads(); loadStats(); }
}

function renderVariantPerfSection(perf) {
  const el = document.getElementById("variant-perf-section");
  if (!el) return;
  const byVariant = perf.by_variant || {};
  const byIndustry = perf.by_industry || {};
  const variantRows = Object.entries(byVariant);
  if (!variantRows.length) {
    el.innerHTML = `<div class="lbl" style="margin-bottom:12px;">Variant Performance</div>
      <div class="usage-note">No sent emails yet. Reply rates appear here once you start sending.</div>`;
    return;
  }
  const vCards = variantRows.map(([label, d]) => `
    <div class="api-key-card">
      <div class="key-name">Variant ${esc(label)}</div>
      <div class="key-val">${d.reply_rate}%</div>
      <div class="usage-note" style="margin:0;">${d.replied}/${d.sent} replied</div>
    </div>`).join("");
  const indRows = Object.entries(byIndustry)
    .sort((a, b) => b[1].sent - a[1].sent).slice(0, 8)
    .map(([ind, d]) => `<tr><td>${esc(ind)}</td><td>${d.sent}</td><td>${d.replied}</td><td>${d.reply_rate}%</td></tr>`).join("");
  el.innerHTML = `
    <div class="lbl" style="margin-bottom:12px;">Variant Performance</div>
    <div class="api-key-status">${vCards}</div>
    <div class="card" style="padding:0;overflow-x:auto;margin-top:14px;">
      <table class="usage-table">
        <thead><tr><th>Industry</th><th>Sent</th><th>Replied</th><th>Reply rate</th></tr></thead>
        <tbody>${indRows || '<tr><td colspan="4" style="color:#999;">No data</td></tr>'}</tbody>
      </table>
    </div>`;
}

function renderUsageSection(usage) {
  const today = usage.today || {};
  const month = usage.month || {};
  const providers = Array.from(new Set([...Object.keys(today), ...Object.keys(month)]));
  const rows = providers.length ? providers.map(provider => {
    const t = today[provider] || {};
    const m = month[provider] || {};
    return `<tr>
      <td>${esc(provider)}</td>
      <td>${t.calls || 0}</td>
      <td>${m.calls || 0}</td>
      <td>${Number(m.estimated_credits || 0).toFixed(1)}</td>
      <td>${m.estimated_tokens || 0}</td>
      <td>${m.errors || 0}</td>
    </tr>`;
  }).join("") : `<tr><td colspan="6" style="color:#999;">No usage has been logged yet.</td></tr>`;
  const errors = usage.recent_errors || [];
  return `
    <div class="lbl" style="margin-bottom:12px;">API Usage</div>
    <div class="card" style="padding:0;overflow-x:auto;">
      <table class="usage-table">
        <thead><tr><th>Provider</th><th>Today</th><th>This Month</th><th>Est. Credits</th><th>Est. Tokens</th><th>Errors</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <div class="usage-note">Token counts are exact only for direct AI APIs. Codex/Claude batches are local estimates from file size.</div>
    ${errors.length ? `<div class="usage-errors">${errors.map(e => `<div><strong>${esc(e.provider)}:</strong> ${esc(e.error || "")}</div>`).join("")}</div>` : ""}
  `;
}

// ---------------------------------------------------------------------------
// Signature constant used for dashboard previews and compose links.
// Must mirror config.EMAIL_SIGNATURE (set via SIGNATURE_* vars in .env):
// edit both places if you customize your signature.
// ---------------------------------------------------------------------------

const EMAIL_SIGNATURE = `Kind Regards,
____________________________

Your Name - Your Title
W | www.example.com

E| you@example.com`;

const EMAIL_SIGNATURE_HTML = `Kind Regards,<br>
____________________________<br>
<br>
Your Name - Your Title<br>
W | <a href="https://www.example.com">www.example.com</a><br>
<br>
E| you@example.com`;

// Optional AI add-on: read the live checkbox + textarea first (so it works even
// if the box was ticked without clicking Save), falling back to saved fields.
function getAiAddonText(lead) {
  if (!lead) return "";
  const cb = document.getElementById(`d-aiaddon-on-${lead.id}`);
  const enabled = cb ? cb.checked : !!lead.ai_addon_enabled;
  if (!enabled) return "";
  const ta = document.getElementById(`d-aiaddon-${lead.id}`);
  return ((ta ? ta.value : (lead.ai_addon || "")) || "").trim();
}

function getEmailBody(lead, touchIndex) {
  let body;
  if (touchIndex !== undefined && touchIndex !== null) {
    const ta = document.getElementById(`d-seqbody-${lead.id}-${touchIndex}`);
    if (ta) body = ta.value;
    else {
      const variants = lead.email_variants || [];
      if (variants[touchIndex]) body = variants[touchIndex].body;
    }
  }
  if (body === undefined) {
    body = document.getElementById(`d-body-${lead.id}`)?.value
      || lead.outreach_draft || "";
  }
  const addon = getAiAddonText(lead);
  return body + (addon ? "\n\n" + addon : "") + "\n\n" + EMAIL_SIGNATURE;
}

function getEmailBodyHTML(lead, touchIndex) {
  let body = "";
  if (touchIndex !== undefined && touchIndex !== null) {
    const ta = document.getElementById(`d-seqbody-${lead.id}-${touchIndex}`);
    if (ta) body = ta.value;
    else {
      const variants = lead.email_variants || [];
      if (variants[touchIndex]) body = variants[touchIndex].body;
    }
  }
  if (!body) {
    body = document.getElementById(`d-body-${lead.id}`)?.value
      || lead.outreach_draft || "";
  }
  const escapeHtml = (s) => s
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/\n/g, "<br>");
  const addon = getAiAddonText(lead);
  const htmlBody = escapeHtml(body) + (addon ? "<br><br>" + escapeHtml(addon) : "");
  return `<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.6;">${htmlBody}<br><br>${EMAIL_SIGNATURE_HTML}</div>`;
}

// Track which variant tab is active per lead
let _activeSeqTab = 0;

// ---------------------------------------------------------------------------
// Lead detail panel
// ---------------------------------------------------------------------------

// Store current open lead for profile card operations
let _currentLead = null;
let _approvedPending = 0; // global count of emails approved and waiting to send

// Refresh the approved-and-queued count and update any visible "Approved N" stats.
async function refreshApprovedStat() {
  const res = await api("/api/email/approved-count");
  if (res && typeof res.count === "number") {
    _approvedPending = res.count;
    document.querySelectorAll(".approved-stat-val").forEach(el => { el.textContent = _approvedPending; });
  }
}

function renderFavoritePanel(lead) {
  const added = lead.favorited_at ? formatShortDate(lead.favorited_at) : "";
  return `
    <div class="detail-section favorite-panel ${lead.is_favorite ? 'on' : ''}">
      <div class="favorite-panel-head">
        <h3>Favorite</h3>
        <div class="favorite-panel-actions">
          ${renderFavoriteButton(lead, "detail")}
          <span>${lead.is_favorite ? `Saved${added ? ` ${esc(added)}` : ""}` : "Not saved"}</span>
        </div>
      </div>
      <textarea id="d-favorite-note-${lead.id}" rows="2" placeholder="Quick note, why this company is worth revisiting...">${esc(lead.favorite_note || "")}</textarea>
      <div class="favorite-panel-buttons">
        <button class="btn outline xs" onclick="saveFavoriteNote('${lead.id}')">${lead.is_favorite ? "Save Favorite Note" : "Add to Favorites"}</button>
        ${lead.is_favorite ? `<button class="btn ghost xs" onclick="removeFavoriteFromDetail('${lead.id}')">Remove Favorite</button>` : ""}
      </div>
    </div>
  `;
}

async function openDetail(id) {
  const res = await api(`/api/leads/${encodeURIComponent(id)}`);
  if (res.error) return toast(res.error);
  const lead = res.lead;
  _currentLead = lead;

  document.getElementById("d-name").textContent = lead.name;
  document.getElementById("d-meta").textContent =
    `${lead.niche || lead.industry} | ${lead.city || ""}, ${lead.country || ""} | ${lead.primary_service_label || lead.service_focus_label || "Branding"} | ${lead.service_mix_label || "Smart Mix"} | ${lead.search_mode_label || "Direct Client"} | ${lead.status || "unscored"}`;

  // Position of this lead in the visible (filtered/sorted) list, for prev/next nav.
  const navIdx = allLeads.findIndex(l => l.id === lead.id);
  const hasPrev = navIdx > 0;
  const hasNext = navIdx !== -1 && navIdx < allLeads.length - 1;

  const body = document.getElementById("detail-body");

  const profiles = lead.linkedin_profiles || [];

  body.innerHTML = `
    ${renderFavoritePanel(lead)}

    <div class="detail-section">
      <h3>Business Info</h3>
      <div class="detail-grid">
        <div class="detail-field"><div class="label">Address</div><div class="value">${esc(lead.address || "-")}</div></div>
        <div class="detail-field"><div class="label">Phone</div><div class="value">${esc(lead.phone || "-")}</div></div>
        <div class="detail-field"><div class="label">Website</div><div class="value">${lead.website ? `<a href="${esc(lead.website)}" target="_blank">${esc(lead.website)}</a>` : '<span class="no-web">NO WEBSITE</span>'}</div></div>
        <div class="detail-field"><div class="label">Rating</div><div class="value">${lead.rating ? lead.rating.toFixed(1) + " (" + lead.review_count + " reviews)" : "-"}</div></div>
        <div class="detail-field"><div class="label">Google Maps</div><div class="value">${lead.google_maps_url ? `<a href="${esc(lead.google_maps_url)}" target="_blank">Open in Maps</a>` : "-"}</div></div>
        <div class="detail-field"><div class="label">Added</div><div class="value">${lead.date_added || (lead.found_at ? new Date(lead.found_at).toLocaleDateString() : "-")}</div></div>
        <div class="detail-field"><div class="label">Service Focus</div><div class="value">${esc(lead.service_focus_label || "Branding")}</div></div>
        <div class="detail-field"><div class="label">Outreach Mix</div><div class="value">${esc(lead.service_mix_label || "Smart Mix")}</div></div>
        <div class="detail-field"><div class="label">Primary Service</div><div class="value">${esc(lead.primary_service_label || lead.service_focus_label || "Brand Identity")}</div></div>
        <div class="detail-field"><div class="label">Supporting Services</div><div class="value">${esc((lead.secondary_service_labels || []).join(", ") || "None")}</div></div>
        ${lead.outreach_angle ? `<div class="detail-field"><div class="label">Outreach Angle</div><div class="value">${esc(lead.outreach_angle)}</div></div>` : ""}
        <div class="detail-field"><div class="label">Search Lane</div><div class="value">${esc(lead.search_mode_label || "Direct Client")}</div></div>
        ${lead.search_query ? `<div class="detail-field"><div class="label">Search Query</div><div class="value">${esc(lead.search_query)}</div></div>` : ""}
        ${lead.company_size ? `<div class="detail-field"><div class="label">Employees</div><div class="value">${esc(String(lead.company_size))}</div></div>` : ""}
        ${lead.founded_year ? `<div class="detail-field"><div class="label">Founded</div><div class="value">${lead.founded_year}</div></div>` : ""}
        ${lead.estimated_revenue ? `<div class="detail-field"><div class="label">Est. Revenue</div><div class="value">${esc(lead.estimated_revenue)}</div></div>` : ""}
        ${lead.industry_apollo ? `<div class="detail-field"><div class="label">Industry (Apollo)</div><div class="value">${esc(lead.industry_apollo)}</div></div>` : ""}
      </div>
    </div>

    ${renderEnrichmentPanel(lead)}

    ${lead.score ? `
    <div class="detail-section">
      <h3>Score</h3>
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">
        <span style="font-family:'Cormorant Garamond',serif;font-size:40px;font-weight:500;color:${lead.priority === 'hot' ? '#DC2626' : lead.priority === 'warm' ? '#D97706' : '#2563EB'}">${lead.score}</span>
        <span class="badge ${lead.priority}">${lead.priority}</span>
        ${lead.date_scored ? `<span style="font-size:11px;color:#999;font-family:-apple-system,sans-serif;">Scored ${lead.date_scored}</span>` : ""}
      </div>
      <p style="font-size:13px;color:#2C2C2C;line-height:1.7;font-family:-apple-system,sans-serif;margin-bottom:8px;">${esc(lead.score_reason || "")}</p>
      ${lead.brand_gap ? `<div class="brand-gap">${esc(lead.brand_gap)}</div>` : ""}
    </div>` : ""}

    ${lead.priority && lead.priority !== "skip" ? `
    <div class="detail-section" id="email-zone-${lead.id}">
      <h3 style="display:flex;align-items:center;gap:8px;">Email Variants ${renderToneBadge(lead.tone_audit)}</h3>
      ${renderToneAudit(lead)}
      ${(lead.email_variants && lead.email_variants.length) ? `
        ${renderVariantMeta(lead)}
        <div class="email-field-label">To</div>
        <input class="email-to-input" id="d-to-${lead.id}" value="${esc(lead.contact_email || '')}" placeholder="email@company.com">
        <div class="seq-tabs" id="seq-tabs-${lead.id}">
          ${lead.email_variants.map((e, i) => `
            <button class="seq-tab ${i === 0 ? 'active' : ''}" onclick="switchVariantTab('${lead.id}', ${i})" data-touch="${i}">
              <span class="seq-tab-num">${e.label || String.fromCharCode(65 + i)}</span>
              <span class="seq-tab-label">${esc(e.approach || e.type || '')}</span>
            </button>
          `).join("")}
          <div class="lead-nav">
            <button class="lead-nav-btn" onclick="gotoAdjacentLead(-1)" ${hasPrev ? "" : "disabled"} title="Previous lead (above)">&#9650;</button>
            <button class="lead-nav-btn" onclick="gotoAdjacentLead(1)" ${hasNext ? "" : "disabled"} title="Next lead (below)">&#9660;</button>
          </div>
        </div>
        <div id="seq-panels-${lead.id}">
          ${lead.email_variants.map((e, i) => `
            <div class="seq-panel ${i === 0 ? 'active' : ''}" id="seq-panel-${lead.id}-${i}">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                <span class="seq-type-badge">${esc(e.approach || e.type || '')}</span>
              </div>
              ${renderVariantToneWarnings(lead, i)}
              ${renderVariantRepairActions(lead, i)}
              <div class="email-field-label">Subject</div>
              <input class="email-subject-input" id="d-seqsubject-${lead.id}-${i}" value="${esc(e.subject || '')}">
              <div class="email-field-label">Body</div>
              <textarea class="email-body-textarea" id="d-seqbody-${lead.id}-${i}">${esc(e.body || '')}</textarea>
              <div class="signature-preview">${esc(EMAIL_SIGNATURE)}</div>
              <div class="email-actions">
                <button class="btn green xs" onclick="approveVariant('${lead.id}', ${i})" title="${lead.approved_variant === i && lead.status !== 'sent' ? 'Click to remove this variant from the approved send queue' : "Mark this variant approved so 'Send Approved Emails' sends it via Gmail"}">${lead.approved_variant === i && lead.status !== 'sent' ? "&#10003; Approved (remove)" : "Approve for Gmail"}</button>
                <button class="btn gold xs" onclick="openGmailSeq('${lead.id}', ${i})">Gmail</button>
                <button class="btn navy xs" onclick="openHotmailSeq('${lead.id}', ${i})">Hotmail</button>
                <button class="btn outline xs" onclick="copyEmailSeq('${lead.id}', ${i})">Copy</button>
                <span class="approved-stat" title="Emails approved and waiting to send">Approved <strong class="approved-stat-val">${_approvedPending}</strong></span>
              </div>
            </div>
          `).join("")}
        </div>
        <div style="margin-top:8px;display:flex;gap:6px;">
          <button class="btn outline xs" onclick="saveVariants('${lead.id}')">Save All Changes</button>
          <button class="regenerate-btn" onclick="regenerateEmail('${lead.id}')">Regenerate with Claude Code</button>
        </div>
        ${renderAiAddon(lead)}
      ` : lead.outreach_draft ? `
        <div class="email-field-label">Subject</div>
        <input class="email-subject-input" id="d-subject-${lead.id}" value="${esc(lead.outreach_subject || '')}" placeholder="Subject line...">
        <div class="email-field-label">To</div>
        <input class="email-to-input" id="d-to-${lead.id}" value="${esc(lead.contact_email || '')}" placeholder="email@company.com">
        <div class="email-field-label">Body</div>
        <textarea class="email-body-textarea" id="d-body-${lead.id}">${esc(lead.outreach_draft || '')}</textarea>
        <div class="signature-preview">${esc(EMAIL_SIGNATURE)}</div>
        <div class="email-actions">
          <button class="btn green xs" onclick="approveVariant('${lead.id}', 0)" title="${lead.approved_variant === 0 && lead.status !== 'sent' ? 'Click to remove from the approved send queue' : "Mark approved so 'Send Approved Emails' sends it via Gmail"}">${lead.approved_variant === 0 && lead.status !== 'sent' ? "&#10003; Approved (remove)" : "Approve for Gmail"}</button>
          <button class="btn gold xs" onclick="openGmail('${lead.id}')">Open in Gmail</button>
          <button class="btn navy xs" onclick="openHotmail('${lead.id}')">Open in Hotmail</button>
          <button class="btn outline xs" onclick="copyEmail('${lead.id}')">Copy Email</button>
          <button class="btn outline xs" onclick="saveEmail('${lead.id}')">Save Changes</button>
          <span class="approved-stat" title="Emails approved and waiting to send">Approved <strong class="approved-stat-val">${_approvedPending}</strong></span>
        </div>
        <div style="margin-top:8px;">
          <button class="regenerate-btn" onclick="regenerateEmail('${lead.id}')">Regenerate with Claude Code</button>
        </div>
        ${renderAiAddon(lead)}
      ` : `
        <p style="font-size:12px;color:#666;font-family:-apple-system,sans-serif;margin-bottom:10px;">No email written yet. Click <strong>Export for Email Writing</strong> in the pipeline, ask Claude Code to write emails, then <strong>Import Emails</strong>.</p>
        ${lead.outreach_subject ? `
        <div style="margin-bottom:8px;">
          <div class="lbl">Suggested Subject</div>
          <div style="font-size:13px;color:#2C2C2C;padding:8px 12px;background:#fff;border:1.5px solid #DDD5C8;border-radius:3px;">${esc(lead.outreach_subject)}</div>
        </div>` : ""}
      `}
    </div>

    <div class="detail-section">
      <h3>LinkedIn</h3>
      <div id="profiles-container-${lead.id}">
        ${profiles.length ? profiles.map((p, i) => renderProfileCard(lead.id, p, i)).join("") : ""}
      </div>
      <button class="add-profile-btn" onclick="addLinkedInProfile('${lead.id}')">+ Add Profile</button>
    </div>` : ""}

    ${lead.priority && lead.priority !== "skip" ? renderOutcomePanel(lead) : ""}

    <div class="detail-section">
      <h3>Contact Info</h3>
      <div class="detail-grid">
        <div class="detail-field"><div class="label">Contact Email</div>
          <div style="display:flex;gap:6px;align-items:center;">
            <input type="text" id="d-email-${lead.id}" value="${esc(lead.contact_email || '')}" placeholder="email@company.com" style="font-size:12px;padding:6px 10px;flex:1;">
            ${lead.website ? `<button class="btn outline xs" onclick="scrapeContactEmail('${esc(lead.id)}', '${esc(lead.website)}')" title="Scan website for email">Scrape</button>` : ""}
          </div>
          ${(lead.contact_page_emails && lead.contact_page_emails.length) ? `
          <div style="margin-top:8px;">
            <div style="font-size:11px;color:#999;font-family:-apple-system,sans-serif;margin-bottom:5px;">Found by Firecrawl:</div>
            <div style="display:flex;flex-wrap:wrap;gap:5px;">
              ${lead.contact_page_emails.map(e => `
                <button onclick="useEmail('${lead.id}','${esc(e)}')"
                  style="background:#F3EDE3;border:1px solid #DDD5C8;color:#5A4A2A;font-size:11px;padding:3px 10px;border-radius:12px;cursor:pointer;font-family:-apple-system,sans-serif;"
                  title="Click to use this email">${esc(e)}</button>
              `).join("")}
            </div>
          </div>` : ""}
        </div>
        <div class="detail-field"><div class="label">Decision Maker</div>
          <input type="text" id="d-dm-${lead.id}" value="${esc(lead.decision_maker || '')}" placeholder="Name" style="font-size:12px;padding:6px 10px;">
        </div>
        <div class="detail-field"><div class="label">Title</div>
          <input type="text" id="d-dmt-${lead.id}" value="${esc(lead.decision_maker_title || '')}" placeholder="CEO, Founder..." style="font-size:12px;padding:6px 10px;">
        </div>
      </div>
      <button class="btn outline xs" style="margin-top:8px;" onclick="saveContactInfo('${lead.id}')">Save Contact Info</button>
    </div>

    <div class="detail-section">
      <h3>Notes</h3>
      <textarea id="d-notes-${lead.id}" rows="3" style="width:100%;">${esc(lead.notes || "")}</textarea>
      <button class="btn outline xs" style="margin-top:6px;" onclick="saveNotes('${lead.id}')">Save Notes</button>
    </div>

    ${lead.reply_snippet ? `
    <div class="detail-section">
      <h3>Reply</h3>
      <div style="font-size:12px;color:#444;font-family:-apple-system,sans-serif;">
        <div style="color:#7C3AED;margin-bottom:4px;">${esc(lead.reply_from || '')}</div>
        <div style="background:#F7F4EF;border:1.5px solid #DDD5C8;border-radius:3px;padding:8px 12px;">${esc(lead.reply_snippet)}</div>
      </div>
      <button class="btn gold xs" style="margin-top:8px;" onclick="addWinToMemory('${lead.id}')" title="Append the winning approach + subject to memory.md What Works">Add win to memory</button>
    </div>` : ""}

    <div class="detail-actions">
      ${lead.status === 'unscored' || !lead.status ? `<span style="font-size:11px;color:#999;font-family:-apple-system,sans-serif;">Export for scoring first, then import scores.</span>` : ""}
      ${(lead.status === 'hot' || lead.status === 'warm' || lead.status === 'cold') ? `<button class="btn navy sm" onclick="setDetailStatus('${lead.id}','drafted')">Mark Drafted</button>` : ""}
      ${lead.status === 'drafted' ? `<button class="btn green sm" onclick="setDetailStatus('${lead.id}','sent')">Mark Sent</button>` : ""}
      ${lead.status === 'sent' ? `<button class="btn purple sm" onclick="setDetailStatus('${lead.id}','replied')">Mark Replied</button>` : ""}
      ${lead.status === 'sent' ? `<button class="btn outline sm" onclick="undoSent('${lead.id}')">Undo Sent</button>` : ""}
      ${lead.status === 'replied' ? `<button class="btn amber sm" onclick="setDetailStatus('${lead.id}','meeting')">Mark Meeting</button>` : ""}
      ${lead.status === 'meeting' ? `<button class="btn gold sm" onclick="setDetailStatus('${lead.id}','converted')">Mark Converted</button>` : ""}
      ${lead.status !== 'skip' ? `<button class="btn ghost sm" onclick="setDetailStatus('${lead.id}','skip')">Skip</button>` : ""}
      ${lead.contact_email ? `<button class="btn ghost xs" onclick="addToDoNotContact('${esc(lead.contact_email)}')" title="Never email this address again">Do not contact</button>` : ""}
      <button class="btn danger xs" onclick="deleteLead('${lead.id}')">Delete</button>
    </div>
  `;

  document.getElementById("detail-overlay").classList.add("open");
  document.getElementById("detail-panel").classList.add("open");

  // Jump straight to the email zone when this lead has one.
  const zone = document.getElementById(`email-zone-${id}`);
  if (zone) requestAnimationFrame(() => zone.scrollIntoView({ block: "start" }));

  // Show the live "Approved & queued" count next to the action buttons.
  refreshApprovedStat();
}

// Move to the lead above (-1) or below (+1) in the visible list, keeping the panel open.
async function gotoAdjacentLead(delta) {
  if (!_currentLead) return;
  // Persist any unsaved edits on the current lead before switching away.
  try { await flushLeadEdits(_currentLead); } catch (_) { /* best-effort */ }
  const idx = allLeads.findIndex(l => l.id === _currentLead.id);
  if (idx === -1) return;
  const next = allLeads[idx + delta];
  if (!next) return; // at the first/last lead
  currentPage = Math.floor((idx + delta) / PAGE_SIZE) + 1; // keep the table page in sync
  renderCurrentPageLeads();
  openDetail(next.id);
}

function renderEnrichmentPanel(lead) {
  const audit = lead.enrichment_audit || {};
  const status = audit.status || "missing";
  const missing = audit.missing_fields || [];
  const provider = audit.providers || {};
  const firecrawl = provider.firecrawl || {};
  const apolloOrg = provider.apollo_organization || {};
  const apolloPeople = provider.apollo_people || {};
  const contacts = lead.contact_candidates || [];
  const linkedins = lead.linkedin_candidates || [];
  const keywords = lead.apollo_keywords || [];

  return `
    <div class="detail-section detail-section-collapsed" id="enrichment-section-${lead.id}">
      <h3 style="cursor:pointer;display:flex;justify-content:space-between;align-items:center;" onclick="toggleEnrichmentSection('${lead.id}')">
        <span>Enrichment <span class="enrich-badge ${status}">${status}</span></span>
        <span id="enrichment-toggle-${lead.id}" style="font-size:11px;color:#999;font-family:-apple-system,sans-serif;font-weight:400;">show</span>
      </h3>
      <div id="enrichment-content-${lead.id}" style="display:none;">
        ${missing.length ? `<div class="enrich-missing"><strong>Missing:</strong> ${missing.map(m => esc(m.replaceAll("_", " "))).join(", ")}</div>` : `<div class="enrich-ok">Core enrichment fields are filled.</div>`}

        <div class="enrich-provider-grid">
          ${renderProviderStatus("Firecrawl", firecrawl, [
            `${firecrawl.pages_scraped || 0} pages`,
            `${firecrawl.emails_found || 0} emails`,
            `${firecrawl.social_links_found || 0} social links`
          ])}
          ${renderProviderStatus("Apollo Company", apolloOrg, [
            `${(apolloOrg.fields_returned || []).length} fields`
          ])}
          ${renderProviderStatus("Apollo People", apolloPeople, [
            `${(apolloPeople.fields_returned || []).length} fields`
          ])}
        </div>

        ${lead.website_summary ? `<div class="enrich-block"><div class="label">Website Summary</div><p>${esc(lead.website_summary)}</p></div>` : ""}
        ${lead.brand_signals ? `<div class="enrich-block"><div class="label">Brand Signals</div><p>${esc(lead.brand_signals)}</p></div>` : ""}
        ${keywords.length ? `<div class="enrich-block"><div class="label">Apollo Keywords</div><div class="candidate-wrap">${keywords.map(k => `<span class="candidate-chip muted">${esc(k)}</span>`).join("")}</div></div>` : ""}

        <div class="enrich-block">
          <div class="label">Contact Candidates</div>
          ${contacts.length ? `<div class="candidate-wrap">${contacts.map(c => `
            <button class="candidate-chip ${c.selected ? "selected" : ""}" onclick="useEmail('${lead.id}','${esc(c.email || c.value || "")}')" title="${esc(c.source_provider || "unknown")}">${esc(c.email || c.value || "")}</button>
          `).join("")}</div>` : `<p>No email candidates captured yet.</p>`}
        </div>

        <div class="enrich-block">
          <div class="label">LinkedIn Candidates</div>
          ${linkedins.length ? `<div class="candidate-list">${linkedins.map(c => `
            <div class="candidate-row">
              <div>
                <a href="${esc(c.url)}" target="_blank">${esc(c.name || c.kind || "LinkedIn")}</a>
                <span>${esc(c.kind || "")} · ${esc(c.source_provider || "unknown")}</span>
              </div>
              <button class="btn outline xs" onclick="useLinkedInCandidate('${lead.id}','${esc(c.url)}')">Use</button>
            </div>
          `).join("")}</div>` : `<p>No LinkedIn candidates captured yet.</p>`}
        </div>

        <div class="enrich-actions">
          <button class="btn outline xs" onclick="loadSnapshots('${lead.id}')" title="View local provider snapshots without API usage">View Snapshots</button>
          <button class="btn outline xs" onclick="reEnrichLead('${lead.id}', false)" title="Re-run Firecrawl and Apollo company enrichment">Re-enrich</button>
          <button class="btn navy xs" onclick="reEnrichLead('${lead.id}', true)" title="Try Apollo People only when a name, email, or LinkedIn URL exists">Find Person Data</button>
        </div>
        <div id="snapshot-viewer-${lead.id}" class="snapshot-viewer" style="display:none;"></div>
        ${lead.enriched_at ? `<div class="enrich-foot">Last enriched: ${new Date(lead.enriched_at).toLocaleString()}</div>` : ""}
      </div>
    </div>
  `;
}

function renderProviderStatus(label, info, facts) {
  const status = info.status || "missing";
  const errors = info.errors || [];
  return `
    <div class="enrich-provider">
      <div class="provider-top"><strong>${esc(label)}</strong><span class="enrich-badge ${status}">${esc(status)}</span></div>
      <div class="provider-facts">${facts.map(f => `<span>${esc(f)}</span>`).join("")}</div>
      ${errors.length ? `<div class="provider-error">${esc(errors[0])}</div>` : ""}
    </div>
  `;
}

// Persist any edits made in the open lead panel that were not explicitly saved
// (Contact Info, Notes, email subject/body or variants), so leaving the lead
// keeps the changes instead of dropping them. Best-effort and silent on errors.
async function flushLeadEdits(lead) {
  if (!lead || !lead.id) return false;
  const id = lead.id;
  let changed = false;

  // Contact email can live in two inputs: the Contact Info field and the email
  // "To" field. Reconcile them so whichever the user edited wins, and both the
  // contact-info PATCH and the email-draft save write the same address.
  const emailEl = document.getElementById(`d-email-${id}`);
  const toEl = document.getElementById(`d-to-${id}`);
  const origEmail = lead.contact_email || "";
  let newEmail = origEmail;
  if (emailEl && emailEl.value !== origEmail) newEmail = emailEl.value;
  else if (toEl && toEl.value !== origEmail) newEmail = toEl.value;
  if (emailEl) emailEl.value = newEmail;
  if (toEl) toEl.value = newEmail;

  // Contact Info section (email, decision maker, title).
  const patch = {};
  if (newEmail !== origEmail) patch.contact_email = newEmail;
  const dmEl = document.getElementById(`d-dm-${id}`);
  if (dmEl && dmEl.value !== (lead.decision_maker || "")) patch.decision_maker = dmEl.value;
  const dmtEl = document.getElementById(`d-dmt-${id}`);
  if (dmtEl && dmtEl.value !== (lead.decision_maker_title || "")) patch.decision_maker_title = dmtEl.value;
  if (Object.keys(patch).length) {
    const res = await api(`/api/leads/${encodeURIComponent(id)}`, "PATCH", patch);
    if (!res.error) { changed = true; if (res.lead) _currentLead = res.lead; }
  }

  // Notes section.
  const notesEl = document.getElementById(`d-notes-${id}`);
  if (notesEl && notesEl.value !== (lead.notes || "")) {
    const res = await api("/api/update-notes", "POST", { id, notes: notesEl.value });
    if (!res.error) changed = true;
  }

  // Email subject/body or the A/B/C variants.
  let emailDirty = false;
  const subjEl = document.getElementById(`d-subject-${id}`);
  const bodyEl = document.getElementById(`d-body-${id}`);
  if (subjEl && subjEl.value !== (lead.outreach_subject || "")) emailDirty = true;
  if (bodyEl && bodyEl.value !== (lead.outreach_draft || "")) emailDirty = true;
  (lead.email_variants || []).forEach((v, i) => {
    const vs = document.getElementById(`d-seqsubject-${id}-${i}`);
    const vb = document.getElementById(`d-seqbody-${id}-${i}`);
    if (vs && vs.value !== (v.subject || "")) emailDirty = true;
    if (vb && vb.value !== (v.body || "")) emailDirty = true;
  });
  if (emailDirty) {
    const ok = await saveCurrentEmailDraft(id); // silent, no refresh
    if (ok) changed = true;
  }

  if (changed) toast("Saved your changes");
  return changed;
}

async function closeDetail(save = true) {
  const lead = _currentLead;
  if (save && lead) {
    try { await flushLeadEdits(lead); } catch (_) { /* best-effort */ }
  }
  document.getElementById("detail-overlay").classList.remove("open");
  document.getElementById("detail-panel").classList.remove("open");
  _currentLead = null;
}

function toggleEnrichmentSection(leadId) {
  const content = document.getElementById(`enrichment-content-${leadId}`);
  const toggle = document.getElementById(`enrichment-toggle-${leadId}`);
  if (!content) return;
  const isHidden = content.style.display === "none";
  content.style.display = isHidden ? "block" : "none";
  if (toggle) toggle.textContent = isHidden ? "hide" : "show";
}

async function reEnrichLead(leadId, includePeople = false) {
  toast(includePeople ? "Looking for person data..." : "Re-enriching...");
  const res = await api(`/api/enrich/${encodeURIComponent(leadId)}`, "POST", { include_people: includePeople });
  if (res.error) { toast("Re-enrich failed: " + res.error); return; }
  toast("Re-enriched. Reloading...");
  openDetail(leadId);
}

async function loadSnapshots(leadId) {
  const viewer = document.getElementById(`snapshot-viewer-${leadId}`);
  if (!viewer) return;
  viewer.style.display = "block";
  viewer.innerHTML = `<div class="snapshot-note">Loading local snapshots...</div>`;
  const res = await api(`/api/enrichment/snapshots/${encodeURIComponent(leadId)}`);
  if (res.error) {
    viewer.innerHTML = `<div class="snapshot-error">${esc(res.error)}</div>`;
    return;
  }
  const snapshots = res.snapshots || [];
  if (!snapshots.length) {
    viewer.innerHTML = `<div class="snapshot-note">No saved provider snapshots yet. Re-enrich to create one.</div>`;
    return;
  }
  viewer.innerHTML = `
    <div class="snapshot-note">Local snapshot, no API usage</div>
    <div class="snapshot-list">
      ${snapshots.map(s => renderSnapshotRow(leadId, s)).join("")}
    </div>
  `;
}

function renderSnapshotRow(leadId, snapshot) {
  const when = snapshot.timestamp ? new Date(snapshot.timestamp).toLocaleString() : "Unknown time";
  const provider = snapshot.provider || "unknown";
  return `
    <div class="snapshot-row" id="snapshot-row-${cssSafe(snapshot.id)}">
      <div class="snapshot-meta">
        <strong>${esc(provider)}</strong>
        <span>${esc(snapshot.endpoint || "unknown")} · ${esc(when)}</span>
        ${snapshot.request_ref ? `<code>${esc(snapshot.request_ref)}</code>` : ""}
      </div>
      <button class="btn outline xs" onclick="openSnapshot('${leadId}', '${esc(snapshot.id)}')">Open JSON</button>
    </div>
    <div class="snapshot-json-wrap" id="snapshot-json-${cssSafe(snapshot.id)}" style="display:none;"></div>
  `;
}

async function openSnapshot(leadId, snapshotId) {
  const target = document.getElementById(`snapshot-json-${cssSafe(snapshotId)}`);
  if (!target) return;
  const isOpen = target.style.display !== "none";
  if (isOpen) {
    target.style.display = "none";
    return;
  }
  target.style.display = "block";
  target.innerHTML = `<div class="snapshot-note">Reading local JSON...</div>`;
  const res = await api(`/api/enrichment/snapshots/${encodeURIComponent(leadId)}/${encodeURIComponent(snapshotId)}`);
  if (res.error) {
    target.innerHTML = `<div class="snapshot-error">${esc(res.error)}</div>`;
    return;
  }
  const json = JSON.stringify(res.snapshot || {}, null, 2);
  target.innerHTML = `
    <div class="snapshot-json-actions">
      <span>Raw saved provider response</span>
      <button class="btn outline xs" onclick="copySnapshotJson('${cssSafe(snapshotId)}')">Copy JSON</button>
    </div>
    <pre id="snapshot-pre-${cssSafe(snapshotId)}">${esc(json)}</pre>
  `;
}

function copySnapshotJson(safeId) {
  const pre = document.getElementById(`snapshot-pre-${safeId}`);
  if (!pre) return;
  navigator.clipboard.writeText(pre.textContent || "").then(() => toast("Snapshot JSON copied"));
}

// ---------------------------------------------------------------------------
// Email actions
// ---------------------------------------------------------------------------

async function saveCurrentEmailDraft(leadId) {
  if (_currentLead?.email_variants?.length) {
    return await saveVariants(leadId, { silent: true, refresh: false });
  }
  if (document.getElementById(`d-body-${leadId}`)) {
    return await saveEmail(leadId, { silent: true, refresh: false });
  }
  return true;
}

function gateMessage(title, items) {
  return `${title}\n\n${items.map(f => `- ${f.label || f.code}${f.detail ? `: ${f.detail}` : ""}`).join("\n")}`;
}

async function runSendGate(leadId, variantIndex, action) {
  const body = { id: leadId, action };
  if (variantIndex !== undefined && variantIndex !== null) body.variant_index = variantIndex;
  const res = await api("/api/email/send-gate", "POST", body);
  if (res.error) {
    toast(res.error);
    return false;
  }
  if (res.blocked) {
    alert(gateMessage("Send blocked. Fix these first:", res.blocks || []));
    return false;
  }
  if (res.requires_override) {
    if (!window.confirm(gateMessage("Review warnings before sending. Continue anyway?", res.warnings || []))) {
      return false;
    }
  }
  if (["gmail", "hotmail", "copy"].includes(action)) {
    await api("/api/email/outcome", "POST", {
      id: leadId,
      event: "prepared",
      channel: action,
      variant_index: variantIndex,
    });
  }
  return true;
}

// Approve a variant: persist edits, run the send gate, then queue for Gmail.
async function approveVariant(leadId, variantIndex) {
  const lead = _currentLead && _currentLead.id === leadId ? _currentLead : null;
  const alreadyApproved = lead
    && lead.approved_variant !== null && lead.approved_variant !== undefined
    && Number(lead.approved_variant) === variantIndex
    && lead.status !== 'sent';

  // Clicking an already-approved variant toggles it back off (no send gate needed).
  if (alreadyApproved) {
    const res = await api("/api/email/approve", "POST", { id: leadId, unapprove: true });
    if (res.error) { toast(res.error); return; }
    toast("Removed from the approved queue.");
    if (!updateVisibleLead(res.lead)) loadLeads();
    if (_currentLead && _currentLead.id === leadId) _currentLead = res.lead;
    openDetail(leadId);
    loadStats();
    return;
  }

  if (!(await saveCurrentEmailDraft(leadId))) return;
  if (!(await runSendGate(leadId, variantIndex, "approve"))) return;
  const res = await api("/api/email/approve", "POST", { id: leadId, variant_index: variantIndex });
  if (res.error) { toast(res.error); return; }
  toast("Approved and queued. Send from the Stats tab.");
  if (!updateVisibleLead(res.lead)) loadLeads();
  if (_currentLead && _currentLead.id === leadId) _currentLead = res.lead;
  openDetail(leadId);
  loadStats();
}

// Remove a lead from the approved send queue (used by the Stats-tab Approved panel).
async function unapproveFromQueue(leadId) {
  const res = await api("/api/email/approve", "POST", { id: leadId, unapprove: true });
  if (res.error) { toast(res.error); return; }
  toast("Removed from the approved queue.");
  if (_currentLead && _currentLead.id === leadId) _currentLead = res.lead;
  updateVisibleLead(res.lead);
  loadStats();
}

async function addWinToMemory(leadId) {
  const res = await api("/api/memory/add-win", "POST", { id: leadId });
  if (res.error) { toast(res.error); return; }
  toast("Added to memory.md: " + res.added);
}

async function addToDoNotContact(email) {
  if (!email) { toast("No email to add"); return; }
  if (!window.confirm(`Add ${email} to the do-not-contact list? They will be skipped on every send.`)) return;
  const res = await api("/api/email/do-not-contact", "POST", { email });
  if (res.error) { toast(res.error); return; }
  toast("Added to do-not-contact list");
}

async function openGmail(leadId) {
  if (!(await saveCurrentEmailDraft(leadId))) return;
  if (!(await runSendGate(leadId, null, "gmail"))) return;
  const subjectEl = document.getElementById(`d-subject-${leadId}`);
  const toEl = document.getElementById(`d-to-${leadId}`);
  const subject = subjectEl ? subjectEl.value : (_currentLead?.outreach_subject || "");
  const to = toEl ? toEl.value : (_currentLead?.contact_email || "");
  const body = getEmailBody(_currentLead || {id: leadId});
  const url = `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(to)}&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  window.open(url, "_blank");
}

async function openHotmail(leadId) {
  if (!(await saveCurrentEmailDraft(leadId))) return;
  if (!(await runSendGate(leadId, null, "hotmail"))) return;
  const subjectEl = document.getElementById(`d-subject-${leadId}`);
  const toEl = document.getElementById(`d-to-${leadId}`);
  const subject = subjectEl ? subjectEl.value : (_currentLead?.outreach_subject || "");
  const to = toEl ? toEl.value : (_currentLead?.contact_email || "");
  const body = getEmailBody(_currentLead || {id: leadId});
  const url = `https://outlook.live.com/mail/0/deeplink/compose?to=${encodeURIComponent(to)}&subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  window.open(url, "_blank");
}

async function copyEmail(leadId) {
  if (!(await saveCurrentEmailDraft(leadId))) return;
  if (!(await runSendGate(leadId, null, "copy"))) return;
  const lead = _currentLead || {id: leadId};
  const plain = getEmailBody(lead);
  const html = getEmailBodyHTML(lead);
  try {
    const item = new ClipboardItem({
      "text/html": new Blob([html], {type: "text/html"}),
      "text/plain": new Blob([plain], {type: "text/plain"}),
    });
    navigator.clipboard.write([item]).then(() =>
      toast("Copied — links are active when pasted into Gmail or Outlook")
    );
  } catch (_) {
    navigator.clipboard.writeText(plain).then(() => toast("Email copied to clipboard"));
  }
}

async function saveEmail(leadId, options = {}) {
  const subject = document.getElementById(`d-subject-${leadId}`)?.value || "";
  const to = document.getElementById(`d-to-${leadId}`)?.value || "";
  const draft = document.getElementById(`d-body-${leadId}`)?.value || "";
  const res = await api(`/api/leads/${encodeURIComponent(leadId)}`, "PATCH", {
    outreach_subject: subject,
    contact_email: to,
    outreach_draft: draft,
  });
  if (res.error) return toast(res.error);
  if (_currentLead) {
    _currentLead = res.lead || _currentLead;
  }
  if (!options.silent) toast("Email saved");
  if (options.refresh !== false) openDetail(leadId);
  return true;
}

async function scrapeContactEmail(leadId, website) {
  toast("Scanning website for email...");
  const res = await api("/api/scrape-contact", "POST", {website});
  if (res.error) return toast("Could not scan: " + res.error);
  if (!res.emails || res.emails.length === 0) return toast("No email found on website");
  const el = document.getElementById(`d-email-${leadId}`);
  if (el) el.value = res.emails[0];
  if (res.emails.length > 1) toast(`Found: ${res.emails.join(", ")} — first one filled in`);
  else toast(`Found: ${res.emails[0]}`);
}

function useEmail(leadId, email) {
  const el = document.getElementById(`d-email-${leadId}`);
  if (el) el.value = email;
  toast(`Email set to ${email}`);
}

async function useLinkedInCandidate(leadId, url) {
  if (!url) return;
  const res = await api(`/api/leads/${encodeURIComponent(leadId)}`, "PATCH", { linkedin_url: url });
  if (res.error) return toast(res.error);
  toast("LinkedIn candidate selected");
  openDetail(leadId);
}

async function regenerateEmail(leadId) {
  const res = await api("/api/email/export", "POST", { ids: [leadId] });
  if (res.error) { toast(res.error); return; }
  toast(`Lead exported to data/to_write.json. Ask Claude Code: "write emails"`);
}

async function exportVariantRepair(leadId, variantIndex, action) {
  if (_currentLead?.email_variants?.length) {
    const saved = await saveVariants(leadId, { silent: true, refresh: false });
    if (!saved) return;
  }
  const res = await api("/api/email/repair-export", "POST", {
    id: leadId,
    variant_index: variantIndex,
    action,
  });
  if (res.error) return toast(res.error);
  const label = res.repair?.label || String.fromCharCode(65 + variantIndex);
  toast(`Variant ${label} repair exported. Ask Claude Code: "write emails"`);
}

// ---------------------------------------------------------------------------
// Variant UI helpers
// ---------------------------------------------------------------------------

function toneStatusLabel(status) {
  if (status === "strong") return "Strong";
  if (status === "risky") return "Risky";
  if (status === "needs_review") return "Needs review";
  return "";
}

function renderToneBadge(audit) {
  if (!audit || !audit.status) return "";
  const status = audit.status;
  return `<span class="tone-badge ${esc(status)}">${esc(toneStatusLabel(status))}</span>`;
}

function renderToneAudit(lead) {
  const audit = lead.tone_audit || {};
  const flags = audit.flags || [];
  if (!audit.status || !flags.length) return "";
  const shown = flags.slice(0, 6);
  return `
    <div class="tone-audit ${esc(audit.status)}">
      <div class="tone-audit-head">
        <strong>Tone QA:</strong> ${esc(toneStatusLabel(audit.status))}
        <span>Local check, no API usage</span>
      </div>
      <div class="tone-flag-row">
        ${shown.map(f => `<span class="tone-flag ${esc(f.severity || 'needs_review')}" title="${esc(f.detail || '')}">${esc(f.label || f.code)}${f.count > 1 ? ` (${f.count})` : ""}</span>`).join("")}
      </div>
    </div>
  `;
}

function renderVariantToneWarnings(lead, index) {
  const checks = lead.tone_audit?.variant_checks || [];
  const check = checks.find(c => Number(c.index) === index) || checks[index];
  const flags = check?.flags || [];
  if (!flags.length) return "";
  return `
    <div class="variant-tone-warnings">
      ${flags.map(f => `<span class="tone-flag ${esc(f.severity || 'needs_review')}" title="${esc(f.detail || '')}">${esc(f.label || f.code)}</span>`).join("")}
      ${check.word_count ? `<span class="tone-word-count">${check.word_count} words</span>` : ""}
    </div>
  `;
}

function renderVariantRepairActions(lead, index) {
  return `
    <div class="variant-repair-actions">
      <button class="repair-action-btn" onclick="exportVariantRepair('${lead.id}', ${index}, 'fix_greeting')">Fix Greeting</button>
      <button class="repair-action-btn" onclick="exportVariantRepair('${lead.id}', ${index}, 'make_specific')">More Specific</button>
      <button class="repair-action-btn" onclick="exportVariantRepair('${lead.id}', ${index}, 'remove_ai')">Remove AI</button>
      <button class="repair-action-btn" onclick="exportVariantRepair('${lead.id}', ${index}, 'shorten')">Shorten</button>
      <button class="repair-action-btn strong" onclick="exportVariantRepair('${lead.id}', ${index}, 'regenerate_variant')">Regenerate Variant</button>
    </div>
  `;
}

function renderVariantMeta(lead) {
  let html = "";
  if (lead.trigger) {
    html += `<div style="display:flex;gap:12px;margin-bottom:10px;flex-wrap:wrap;">`;
    html += `<div style="font-size:11px;color:#5A4A2A;background:#F3EDE3;padding:4px 10px;border-radius:12px;font-family:-apple-system,sans-serif;">
      <strong>Trigger:</strong> ${esc(lead.trigger)}</div>`;
    html += `</div>`;
  }
  return html;
}

function renderOutcomePanel(lead) {
  const variants = lead.email_variants || [];
  const selectedIndex = lead.variant_sent_index ?? lead.last_send_variant_index ?? 0;
  const channel = lead.send_channel || lead.last_send_channel || "";
  const prepared = lead.last_send_prepared_at
    ? `${esc(lead.last_send_variant_label || "Variant")} via ${esc(lead.last_send_channel || "manual")} on ${new Date(lead.last_send_prepared_at).toLocaleString()}`
    : "Not prepared yet";
  const sent = lead.date_sent
    ? `${esc(lead.variant_sent_label || "Variant")} via ${esc(lead.send_channel || "manual")} on ${esc(lead.date_sent)}`
    : "Not marked sent";
  const variantOptions = variants.length
    ? variants.map((v, i) => `<option value="${i}" ${Number(selectedIndex) === i ? "selected" : ""}>${esc(v.label || String.fromCharCode(65 + i))} · ${esc(v.approach || v.type || "variant")}</option>`).join("")
    : `<option value="0">Single draft</option>`;
  const channelOptions = ["", "gmail", "hotmail", "copy", "manual", "linkedin"].map(v => {
    const label = v ? v[0].toUpperCase() + v.slice(1) : "Select channel";
    return `<option value="${v}" ${channel === v ? "selected" : ""}>${label}</option>`;
  }).join("");
  const replyOptions = [
    ["", "No reply type"],
    ["positive", "Positive"],
    ["interested", "Interested"],
    ["not_now", "Not now"],
    ["referral", "Referral"],
    ["negative", "Negative"],
    ["out_of_office", "Out of office"],
  ].map(([v, label]) => `<option value="${v}" ${lead.reply_type === v ? "selected" : ""}>${label}</option>`).join("");

  return `
    <div class="detail-section outcome-panel">
      <h3>Outcome Tracking</h3>
      <div class="outcome-summary">
        <div><span>Prepared</span><strong>${prepared}</strong></div>
        <div><span>Sent</span><strong>${sent}</strong></div>
        <div><span>Reply</span><strong>${lead.date_replied ? `${esc(lead.reply_type || "reply")} on ${esc(lead.date_replied)}` : "No reply recorded"}</strong></div>
      </div>
      <div class="outcome-grid">
        <div>
          <div class="email-field-label">Variant Sent</div>
          <select id="d-outcome-variant-${lead.id}">${variantOptions}</select>
        </div>
        <div>
          <div class="email-field-label">Channel</div>
          <select id="d-outcome-channel-${lead.id}">${channelOptions}</select>
        </div>
      </div>
      <div class="outcome-grid">
        <div>
          <div class="email-field-label">Reply Type</div>
          <select id="d-reply-type-${lead.id}">${replyOptions}</select>
        </div>
        <div>
          <div class="email-field-label">Reply Notes</div>
          <textarea id="d-reply-notes-${lead.id}" rows="2">${esc(lead.reply_notes || "")}</textarea>
        </div>
      </div>
      <div class="email-actions">
        <button class="btn outline xs" onclick="saveOutcome('${lead.id}', 'save')">Save Outcome</button>
        <button class="btn green xs" onclick="saveOutcome('${lead.id}', 'sent')">Mark Sent With Selection</button>
        <button class="btn purple xs" onclick="saveOutcome('${lead.id}', 'reply')">Mark Replied</button>
      </div>
    </div>
  `;
}

async function saveOutcome(leadId, event) {
  const variantIndex = document.getElementById(`d-outcome-variant-${leadId}`)?.value || "0";
  const channel = document.getElementById(`d-outcome-channel-${leadId}`)?.value || "manual";
  const replyType = document.getElementById(`d-reply-type-${leadId}`)?.value || "";
  const replyNotes = document.getElementById(`d-reply-notes-${leadId}`)?.value || "";

  if (event === "sent") {
    if (!(await saveCurrentEmailDraft(leadId))) return;
    if (!(await runSendGate(leadId, Number(variantIndex), "mark_sent"))) return;
  }

  const res = await api("/api/email/outcome", "POST", {
    id: leadId,
    event,
    variant_index: Number(variantIndex),
    channel,
    reply_type: replyType,
    reply_notes: replyNotes,
  });
  if (res.error) return toast(res.error);
  _currentLead = res.lead || _currentLead;
  toast(event === "reply" ? "Reply outcome saved" : event === "sent" ? "Sent outcome saved" : "Outcome saved");
  openDetail(leadId);
  if (event === "sent" && updateVisibleLead(res.lead)) {
    renderNextStep();
  } else {
    loadLeads();
  }
  loadStats();
}

function switchVariantTab(leadId, index) {
  _activeSeqTab = index;
  document.querySelectorAll(`#seq-tabs-${leadId} .seq-tab`).forEach((t, i) => {
    t.classList.toggle("active", i === index);
  });
  document.querySelectorAll(`#seq-panels-${leadId} .seq-panel`).forEach((p, i) => {
    p.classList.toggle("active", i === index);
  });
}

async function openGmailSeq(leadId, touchIndex) {
  if (!(await saveCurrentEmailDraft(leadId))) return;
  if (!(await runSendGate(leadId, touchIndex, "gmail"))) return;
  const subjectEl = document.getElementById(`d-seqsubject-${leadId}-${touchIndex}`);
  const toEl = document.getElementById(`d-to-${leadId}`);
  const subject = subjectEl ? subjectEl.value : "";
  const to = toEl ? toEl.value : (_currentLead?.contact_email || "");
  const body = getEmailBody(_currentLead || {id: leadId}, touchIndex);
  const url = `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(to)}&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  window.open(url, "_blank");
}

async function openHotmailSeq(leadId, touchIndex) {
  if (!(await saveCurrentEmailDraft(leadId))) return;
  if (!(await runSendGate(leadId, touchIndex, "hotmail"))) return;
  const subjectEl = document.getElementById(`d-seqsubject-${leadId}-${touchIndex}`);
  const toEl = document.getElementById(`d-to-${leadId}`);
  const subject = subjectEl ? subjectEl.value : "";
  const to = toEl ? toEl.value : (_currentLead?.contact_email || "");
  const body = getEmailBody(_currentLead || {id: leadId}, touchIndex);
  const url = `https://outlook.live.com/mail/0/deeplink/compose?to=${encodeURIComponent(to)}&subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  window.open(url, "_blank");
}

async function copyEmailSeq(leadId, touchIndex) {
  if (!(await saveCurrentEmailDraft(leadId))) return;
  if (!(await runSendGate(leadId, touchIndex, "copy"))) return;
  const lead = _currentLead || {id: leadId};
  const plain = getEmailBody(lead, touchIndex);
  const html = getEmailBodyHTML(lead, touchIndex);
  try {
    const item = new ClipboardItem({
      "text/html": new Blob([html], {type: "text/html"}),
      "text/plain": new Blob([plain], {type: "text/plain"}),
    });
    navigator.clipboard.write([item]).then(() =>
      toast("Copied with formatting")
    );
  } catch (_) {
    navigator.clipboard.writeText(plain).then(() => toast("Email copied to clipboard"));
  }
}

async function saveVariants(leadId, options = {}) {
  if (!_currentLead) return;
  const variants = (_currentLead.email_variants || []).map((e, i) => ({
    ...e,
    subject: document.getElementById(`d-seqsubject-${leadId}-${i}`)?.value || e.subject,
    body: document.getElementById(`d-seqbody-${leadId}-${i}`)?.value || e.body,
  }));
  const to = document.getElementById(`d-to-${leadId}`)?.value || "";
  _currentLead.email_variants = variants;
  _currentLead.contact_email = to;
  // Also update outreach_draft/outreach_subject for backward compat
  if (variants.length > 0) {
    _currentLead.outreach_draft = variants[0].body;
    _currentLead.outreach_subject = variants[0].subject;
  }
  const res = await api(`/api/leads/${encodeURIComponent(leadId)}`, "PATCH", {
    email_variants: variants,
    contact_email: to,
    outreach_draft: variants.length > 0 ? variants[0].body : "",
    outreach_subject: variants.length > 0 ? variants[0].subject : "",
  });
  if (res.error) return toast(res.error);
  _currentLead = res.lead || _currentLead;
  if (!options.silent) toast("Variants saved");
  if (options.refresh !== false) openDetail(leadId);
  return true;
}

// ---------------------------------------------------------------------------
// Optional AI add-on (a short P.S. that rides along with the branding email)
// ---------------------------------------------------------------------------

function renderAiAddon(lead) {
  const enabled = !!lead.ai_addon_enabled;
  const text = lead.ai_addon || "";
  return `
    <div class="ai-addon-block">
      <label class="ai-addon-toggle">
        <input type="checkbox" id="d-aiaddon-on-${lead.id}" ${enabled ? "checked" : ""} onchange="saveAiAddon('${lead.id}')">
        <span>Include AI add-on <small>(a short P.S. appended after the body, before the signature)</small></span>
      </label>
      <textarea class="email-body-textarea ai-addon-text" id="d-aiaddon-${lead.id}" placeholder="Optional P.S. offering AI help or training. Leave empty to add nothing.">${esc(text)}</textarea>
      <div class="email-actions">
        <button class="btn outline xs" onclick="saveAiAddon('${lead.id}')">Save AI add-on</button>
        <span style="font-size:11px;color:#888;font-family:-apple-system,sans-serif;">${text ? "Appended only when the box above is ticked." : "No add-on yet. Run AI Add-on export, or write one here."}</span>
      </div>
    </div>`;
}

async function saveAiAddon(leadId) {
  if (!_currentLead) return;
  const text = (document.getElementById(`d-aiaddon-${leadId}`)?.value || "").trim();
  const enabled = !!document.getElementById(`d-aiaddon-on-${leadId}`)?.checked;
  const res = await api(`/api/leads/${encodeURIComponent(leadId)}`, "PATCH", {
    ai_addon: text,
    ai_addon_enabled: enabled,
  });
  if (res.error) return toast(res.error);
  _currentLead = res.lead || _currentLead;
  toast(enabled ? "AI add-on saved and enabled" : "AI add-on saved");
}

// ---------------------------------------------------------------------------
// LinkedIn profile cards
// ---------------------------------------------------------------------------

function renderProfileCard(leadId, profile, index) {
  // Support both old (note/follow_up) and new (connection_note/follow_up_message) field names
  const noteText = profile.connection_note || profile.note || "";
  const followUpText = profile.follow_up_message || profile.follow_up || "";
  const engagements = profile.engagement_suggestions || [];
  const noteLen = noteText.length;
  const counterClass = noteLen > 300 ? "char-over" : noteLen > 280 ? "char-warn" : "char-ok";
  return `
    <div class="profile-card" id="profile-card-${leadId}-${index}">
      <div class="profile-card-header">
        <div>
          <div class="profile-card-title">${esc(profile.name || "Unknown")}</div>
          <div class="profile-card-subtitle">${esc(profile.title || "")}</div>
        </div>
        <button class="profile-remove-btn" onclick="removeLinkedInProfile('${leadId}', ${index})" title="Remove">&times;</button>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:6px;">
        <div>
          <div class="email-field-label">Name</div>
          <input type="text" id="pname-${leadId}-${index}" value="${esc(profile.name || '')}" placeholder="Full Name" style="font-size:12px;padding:5px 8px;">
        </div>
        <div>
          <div class="email-field-label">Title</div>
          <input type="text" id="ptitle-${leadId}-${index}" value="${esc(profile.title || '')}" placeholder="CEO, CMO..." style="font-size:12px;padding:5px 8px;">
        </div>
      </div>
      <div class="email-field-label">LinkedIn URL</div>
      <input type="text" id="purl-${leadId}-${index}" value="${esc(profile.url || '')}" placeholder="https://linkedin.com/in/..." style="font-size:12px;padding:5px 8px;">

      <div class="profile-note-wrap">
        <div class="email-field-label" style="margin-top:8px;">
          Day 0: Connection note <span style="color:#999;font-weight:400;">(max 300 chars)</span>
        </div>
        <textarea class="profile-note-textarea" id="pnote-${leadId}-${index}"
          oninput="updateCharCounter('${leadId}',${index})"
          maxlength="300">${esc(noteText)}</textarea>
        <div class="char-counter-graded"><span id="pcount-${leadId}-${index}" class="${counterClass}">${noteLen}/300</span></div>
        <div style="margin-top:4px;">
          <button class="btn outline xs" onclick="copyLinkedInNote('${leadId}', ${index})">Copy</button>
        </div>
      </div>

      ${engagements.length ? `
      <div class="profile-note-wrap" style="margin-top:8px;border-top:1px dashed #E8E0D5;padding-top:10px;">
        <div class="email-field-label">Day 1-3: Engagement suggestions</div>
        <ul style="margin:6px 0 0 16px;padding:0;font-size:12px;color:#444;font-family:-apple-system,sans-serif;line-height:1.8;">
          ${engagements.map(e => `<li>${esc(e)}</li>`).join("")}
        </ul>
      </div>` : ""}

      <div class="profile-note-wrap" style="margin-top:8px;border-top:1px dashed #E8E0D5;padding-top:10px;">
        <div class="email-field-label">
          Day 5: Follow-up message <span style="color:#999;font-weight:400;">(after accepted)</span>
        </div>
        <textarea class="profile-note-textarea" id="pfollowup-${leadId}-${index}" style="min-height:80px;">${esc(followUpText)}</textarea>
        <div style="margin-top:4px;">
          <button class="btn outline xs" onclick="copyLinkedInFollowUp('${leadId}', ${index})">Copy</button>
        </div>
      </div>

      <div class="profile-actions" style="margin-top:8px;">
        <button class="btn outline xs" onclick="openLinkedInProfile('${leadId}', ${index})">Open Profile</button>
        <button class="btn gold xs" onclick="saveLinkedInProfile('${leadId}')">Save</button>
      </div>
    </div>`;
}

function updateCharCounter(leadId, index) {
  const ta = document.getElementById(`pnote-${leadId}-${index}`);
  const counter = document.getElementById(`pcount-${leadId}-${index}`);
  if (!ta || !counter) return;
  const len = ta.value.length;
  counter.textContent = `${len}/300`;
  counter.className = len > 300 ? "char-over" : len > 280 ? "char-warn" : "char-ok";
}

function addLinkedInProfile(leadId) {
  if (!_currentLead) return;
  if (!_currentLead.linkedin_profiles) _currentLead.linkedin_profiles = [];
  const index = _currentLead.linkedin_profiles.length;
  const newProfile = { name: "", title: "", url: "", note: "", follow_up: "" };
  _currentLead.linkedin_profiles.push(newProfile);
  const container = document.getElementById(`profiles-container-${leadId}`);
  if (container) {
    const div = document.createElement("div");
    div.innerHTML = renderProfileCard(leadId, newProfile, index);
    container.appendChild(div.firstElementChild);
  }
}

function removeLinkedInProfile(leadId, index) {
  if (!_currentLead) return;
  _currentLead.linkedin_profiles.splice(index, 1);
  // Re-render the container
  const container = document.getElementById(`profiles-container-${leadId}`);
  if (container) {
    container.innerHTML = _currentLead.linkedin_profiles.map(
      (p, i) => renderProfileCard(leadId, p, i)
    ).join("");
  }
}

function copyLinkedInNote(leadId, index) {
  const noteEl = document.getElementById(`pnote-${leadId}-${index}`);
  const text = noteEl ? noteEl.value : "";
  navigator.clipboard.writeText(text).then(() => toast("Connection note copied"));
}

function copyLinkedInFollowUp(leadId, index) {
  const el = document.getElementById(`pfollowup-${leadId}-${index}`);
  const text = el ? el.value : "";
  navigator.clipboard.writeText(text).then(() => toast("Follow-up message copied"));
}

function openLinkedInProfile(leadId, index) {
  const urlEl = document.getElementById(`purl-${leadId}-${index}`);
  const url = urlEl ? urlEl.value.trim() : "";
  if (url) {
    window.open(url, "_blank");
  } else {
    toast("No LinkedIn URL set for this profile");
  }
}

async function saveLinkedInProfile(leadId) {
  if (!_currentLead) return;
  // Collect current values from all profile card inputs
  // Store both old and new field names for compatibility
  const profiles = (_currentLead.linkedin_profiles || []).map((existing, i) => ({
    name:     document.getElementById(`pname-${leadId}-${i}`)?.value || "",
    title:    document.getElementById(`ptitle-${leadId}-${i}`)?.value || "",
    url:      document.getElementById(`purl-${leadId}-${i}`)?.value || "",
    note:     document.getElementById(`pnote-${leadId}-${i}`)?.value || "",
    connection_note: document.getElementById(`pnote-${leadId}-${i}`)?.value || "",
    follow_up: document.getElementById(`pfollowup-${leadId}-${i}`)?.value || "",
    follow_up_message: document.getElementById(`pfollowup-${leadId}-${i}`)?.value || "",
    engagement_suggestions: existing.engagement_suggestions || [],
  }));
  _currentLead.linkedin_profiles = profiles;
  await api(`/api/leads/${encodeURIComponent(leadId)}`, "PATCH", { linkedin_profiles: profiles });
  toast("LinkedIn profiles saved");
}

// ---------------------------------------------------------------------------
// Legacy single-note copy (kept for backward compatibility)
// ---------------------------------------------------------------------------

function copyWriteEmailPrompt(event, leadId) {
  event.stopPropagation();
  // Open the detail panel instead - email writing now uses the export/import flow
  openDetail(leadId);
}

// ---------------------------------------------------------------------------
// Status updates
// ---------------------------------------------------------------------------

async function setDetailStatus(id, status) {
  const body = { id, status };
  if (status === "sent") {
    if (!(await saveCurrentEmailDraft(id))) return;
    const variantIndex = _currentLead?.email_variants?.length ? _activeSeqTab : null;
    if (!(await runSendGate(id, variantIndex, "mark_sent"))) return;
    if (variantIndex !== null) body.variant_index = variantIndex;
    body.channel = _currentLead?.last_send_channel || "manual";
  }
  const res = await api("/api/update-status", "POST", body);
  if (res.error) { toast(res.error); return; }
  toast(`Marked as ${status}`);
  closeDetail();
  if (status === "sent" && updateVisibleLead(res.lead)) {
    renderNextStep();
    loadStats();
  } else {
    loadLeads();
  }
}

async function markSent(event, leadId) {
  event.stopPropagation();
  if (!(await runSendGate(leadId, null, "mark_sent"))) return;
  const res = await api("/api/update-status", "POST", { id: leadId, status: "sent" });
  if (res.error) { toast(res.error); return; }
  toast("Marked as sent");
  if (!updateVisibleLead(res.lead)) loadLeads();
  renderNextStep();
  loadStats();
}

async function undoSent(leadId) {
  if (!window.confirm("Move this lead back to Drafted and clear the sent date?")) return;
  const res = await api("/api/update-status", "POST", {
    id: leadId,
    status: "drafted",
    clear_sent: true,
  });
  if (res.error) { toast(res.error); return; }
  toast("Moved back to drafted");
  closeDetail();
  loadLeads();
  renderNextStep();
}

async function undoSentFromRow(event, leadId) {
  event.stopPropagation();
  if (!window.confirm("Move this lead back to Drafted and clear the sent date?")) return;
  const res = await api("/api/update-status", "POST", {
    id: leadId,
    status: "drafted",
    clear_sent: true,
  });
  if (res.error) { toast(res.error); return; }
  toast("Moved back to drafted");
  loadLeads();
  renderNextStep();
}

// ---------------------------------------------------------------------------
// Favorites
// ---------------------------------------------------------------------------

async function toggleFavorite(event, leadId, currentlyFavorite) {
  if (event) event.stopPropagation();
  const makeFavorite = !currentlyFavorite;
  const body = { is_favorite: makeFavorite };

  if (makeFavorite) {
    const note = window.prompt("Quick note for this favorite (optional):", "");
    if (note === null) return;
    body.favorite_note = note;
  }

  const res = await api(`/api/leads/${encodeURIComponent(leadId)}/favorite`, "POST", body);
  if (res.error) { toast(res.error); return; }
  if (_currentLead && _currentLead.id === leadId) _currentLead = res.lead;
  toast(makeFavorite ? "Added to favorites" : "Removed from favorites");
  loadLeads();
  if (document.getElementById("detail-panel")?.classList.contains("open") && _currentLead?.id === leadId) {
    openDetail(leadId);
  }
}

async function saveFavoriteNote(leadId) {
  const note = document.getElementById(`d-favorite-note-${leadId}`)?.value || "";
  const res = await api(`/api/leads/${encodeURIComponent(leadId)}/favorite`, "POST", {
    is_favorite: true,
    favorite_note: note,
  });
  if (res.error) { toast(res.error); return; }
  _currentLead = res.lead || _currentLead;
  toast("Favorite saved");
  loadLeads();
  openDetail(leadId);
}

async function removeFavoriteFromDetail(leadId) {
  const res = await api(`/api/leads/${encodeURIComponent(leadId)}/favorite`, "POST", {
    is_favorite: false,
  });
  if (res.error) { toast(res.error); return; }
  _currentLead = res.lead || _currentLead;
  toast("Removed from favorites");
  loadLeads();
  openDetail(leadId);
}

// ---------------------------------------------------------------------------
// Contact info and notes
// ---------------------------------------------------------------------------

async function saveContactInfo(leadId) {
  const contact_email = document.getElementById(`d-email-${leadId}`)?.value || "";
  const decision_maker = document.getElementById(`d-dm-${leadId}`)?.value || "";
  const decision_maker_title = document.getElementById(`d-dmt-${leadId}`)?.value || "";

  await api(`/api/leads/${encodeURIComponent(leadId)}`, "PATCH", {
    contact_email, decision_maker, decision_maker_title
  });
  toast("Contact info saved");
}

async function saveNotes(leadId) {
  const notes = document.getElementById(`d-notes-${leadId}`)?.value || "";
  await api("/api/update-notes", "POST", { id: leadId, notes });
  toast("Notes saved");
}

async function deleteLead(id) {
  if (!confirm("Delete this prospect permanently?")) return;
  await api(`/api/leads/${encodeURIComponent(id)}`, "DELETE");
  toast("Prospect deleted");
  closeDetail(false); // lead is gone; do not try to save its fields
  loadLeads();
}

// ---------------------------------------------------------------------------
// Score export / import
// ---------------------------------------------------------------------------

async function doScoreExport() {
  const res = await api("/api/score/export", "POST");
  if (res.error && res.count === 0) {
    toast("No unscored leads to export");
    return;
  }
  if (res.error) { toast(res.error); return; }
  toast(`${res.count} leads exported to data/to_score.json. Ask Claude Code to score them.`);
}

async function doScoreImport() {
  const res = await api("/api/score/import", "POST");
  if (res.error) { toast(res.error); return; }
  toast(`${res.updated} leads scored: ${res.hot} hot, ${res.warm} warm, ${res.cold} cold, ${res.skip || 0} skip`);
  loadLeads();
  loadStats();
  renderNextStep();
}

// ---------------------------------------------------------------------------
// Email export / import
// ---------------------------------------------------------------------------

async function doEmailExport(includeCold = false) {
  const res = await api("/api/email/export", "POST", { include_cold: includeCold });
  if (res.error && res.count === 0) {
    toast(includeCold
      ? "No leads ready for email writing"
      : "No hot/warm leads ready. Use Include Cold Leads if you want cold drafts.");
    return;
  }
  if (res.error) { toast(res.error); return; }

  toast(`${res.count} ${includeCold ? "hot/warm/cold" : "hot/warm"} leads exported. Ask Claude Code: "write emails"`);

  if (res.warnings && res.warnings.length > 0) {
    showDuplicateWarnings(res.warnings);
  }
}

function showDuplicateWarnings(warnings) {
  const existing = document.getElementById("dup-warning-box");
  if (existing) existing.remove();

  const box = document.createElement("div");
  box.id = "dup-warning-box";
  box.style.cssText = `
    margin-top:10px;padding:12px 16px;
    background:#FEF3C7;border:1.5px solid #FCD34D;border-radius:4px;
    font-family:-apple-system,sans-serif;font-size:12px;color:#78350F;line-height:1.7;
  `;
  box.innerHTML = `
    <div style="font-weight:700;margin-bottom:6px;font-size:11px;text-transform:uppercase;letter-spacing:.05em;">
      Duplicate contact email${warnings.length > 1 ? "s" : ""} detected
    </div>
    ${warnings.map(w => `<div style="padding-left:8px;border-left:2px solid #FCD34D;margin-bottom:4px;">${esc(w)}</div>`).join("")}
    <div style="margin-top:8px;font-size:11px;color:#92400E;">
      Check these leads before sending. You can update the contact email in each lead's detail panel.
    </div>
    <button onclick="document.getElementById('dup-warning-box').remove()"
      style="margin-top:8px;background:transparent;border:1px solid #FCD34D;border-radius:3px;
      padding:3px 10px;font-size:11px;color:#78350F;font-family:-apple-system,sans-serif;cursor:pointer;">
      Dismiss
    </button>
  `;

  const bulkBar = document.querySelector(".bulk-bar");
  if (bulkBar) bulkBar.after(box);
}

async function doEmailImport() {
  const res = await api("/api/email/import", "POST");
  if (res.error) { toast(res.error); return; }
  const tone = res.tone || {};
  toast(`${res.updated} leads updated. Tone QA: ${tone.strong || 0} strong, ${tone.needs_review || 0} review, ${tone.risky || 0} risky`);
  loadLeads();
  loadStats();
  renderNextStep();
}

async function doFindMissingEmails() {
  const BATCH = 50;
  const dry = await api("/api/email/find-missing-emails", "POST", { dry_run: true });
  if (dry.error) { toast(dry.error); return; }
  if (!dry.targets) { toast("No drafted leads are missing a contact email"); return; }
  const n = Math.min(dry.targets, BATCH);
  if (!confirm(`${dry.targets} drafted leads have no contact email.\n\nRe-enrich the next ${n} now via Firecrawl/Apollo and auto-fill same-domain addresses? This can take a few minutes.`)) return;
  toast(`Finding emails for ${n} leads... this may take a few minutes`);
  const res = await api("/api/email/find-missing-emails", "POST", { limit: BATCH });
  if (res.error) { toast(res.error); return; }
  toast(`${res.promoted} emails added, ${res.emails_found} had candidates, ${res.still_missing} still missing${(res.errors && res.errors.length) ? `, ${res.errors.length} error(s)` : ""}`);
  loadLeads();
  loadStats();
}

async function doAiAddonExport() {
  const res = await api("/api/email/ai-addon-export", "POST", {});
  if (res.error && res.count === 0) { toast("No hot/warm unsent leads need an AI add-on"); return; }
  if (res.error) { toast(res.error); return; }
  toast(`${res.count} leads exported. Ask Claude Code: "write AI add-ons"`);
}

async function doAiAddonImport() {
  const res = await api("/api/email/ai-addon-import", "POST");
  if (res.error) { toast(res.error); return; }
  toast(`${res.updated} AI add-ons attached (off by default).${(res.warnings && res.warnings.length) ? ` ${res.warnings.length} warning(s).` : ""}`);
  if (res.warnings && res.warnings.length) showDuplicateWarnings(res.warnings);
  loadLeads();
}

async function doAiAddonBulk(enabled) {
  const word = enabled ? "Enable" : "Disable";
  if (!confirm(`${word} the AI add-on on all hot and warm leads that have one?`)) return;
  const res = await api("/api/email/ai-addon-bulk", "POST", { enabled });
  if (res.error) { toast(res.error); return; }
  toast(`AI add-on ${enabled ? "enabled" : "disabled"} on ${res.updated} hot/warm leads`);
  loadLeads();
  if (_currentLead) openDetail(_currentLead.id);
}

// ---------------------------------------------------------------------------
// CSV export
// ---------------------------------------------------------------------------

async function doCsvExport() {
  const status = activeFilter !== "all" ? activeFilter : null;
  const body = status ? { status } : {};
  const res = await api("/api/export/csv", "POST", body);
  if (res.error) { toast(res.error); return; }

  const a = document.createElement("a");
  a.href = `/api/export/download/${res.filename}`;
  a.download = res.filename;
  a.click();
  toast(`Exported ${res.count} leads to CSV`);
}

async function doFullCsvExport() {
  const res = await api("/api/export/full-csv", "POST", {});
  if (res.error) { toast(res.error); return; }
  const a = document.createElement("a");
  a.href = `/api/export/download/${res.filename}`;
  a.download = res.filename;
  a.click();
  toast(`Full export: ${res.count} leads with emails and LinkedIn data`);
}

// ---------------------------------------------------------------------------
// Add lead modal
// ---------------------------------------------------------------------------

function openAddModal() {
  document.getElementById("add-modal").classList.add("open");
}

function closeAddModal() {
  document.getElementById("add-modal").classList.remove("open");
}

async function doAddLead() {
  const name = document.getElementById("m-name").value.trim();
  if (!name) { toast("Name is required"); return; }

  const body = {
    name,
    industry: document.getElementById("m-industry").value,
    city: document.getElementById("m-city").value.trim(),
    country: document.getElementById("m-country").value.trim(),
    phone: document.getElementById("m-phone").value.trim(),
    website: document.getElementById("m-website").value.trim(),
    notes: document.getElementById("m-notes").value.trim(),
  };

  const res = await api("/api/leads", "POST", body);
  if (res.error) { toast(res.error); return; }

  ["m-name", "m-city", "m-country", "m-phone", "m-website", "m-notes"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  closeAddModal();
  toast("Prospect added");
  loadLeads();
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function api(url, method = "GET", body = null) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  try {
    const r = await fetch(url, opts);
    const text = await r.text();
    const type = r.headers.get("content-type") || "";
    if (!type.includes("application/json")) {
      return { error: text ? text.slice(0, 240) : `HTTP ${r.status}` };
    }
    const data = text ? JSON.parse(text) : {};
    if (!r.ok && !data.error) data.error = `HTTP ${r.status}`;
    return data;
  } catch (e) {
    return { error: e.message };
  }
}

function esc(str) {
  if (str === null || str === undefined) return "";
  const d = document.createElement("div");
  d.textContent = String(str);
  return d.innerHTML;
}

function cssSafe(str) {
  return String(str || "").replace(/[^a-zA-Z0-9_-]/g, "_");
}

function formatShortDate(value) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value).slice(0, 10);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 3500);
}

// Close panels on Escape; arrow Up/Down move between leads when the panel is open.
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    closeDetail();
    closeAddModal();
    return;
  }
  if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
  const panelOpen = document.getElementById("detail-panel")?.classList.contains("open");
  if (!panelOpen) return;
  // Don't hijack arrow keys while typing in a field.
  const tag = (document.activeElement?.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || document.activeElement?.isContentEditable) return;
  e.preventDefault();
  gotoAdjacentLead(e.key === "ArrowDown" ? 1 : -1);
});

// ---------------------------------------------------------------------------
// Brand gap tooltip (body-level, bypasses table overflow:hidden)
// ---------------------------------------------------------------------------

let _tipEl = null;

function _getTip() {
  if (!_tipEl) {
    _tipEl = document.createElement("div");
    _tipEl.id = "brand-gap-tip";
    document.body.appendChild(_tipEl);
  }
  return _tipEl;
}

function _placeTip(tip, e) {
  const pad = 14;
  tip.style.left = "0";
  tip.style.top = "0";
  tip.style.display = "block";
  const w = tip.offsetWidth;
  const h = tip.offsetHeight;
  let x = e.clientX + pad;
  let y = e.clientY + pad;
  if (x + w > window.innerWidth - 8) x = e.clientX - w - pad;
  if (y + h > window.innerHeight - 8) y = e.clientY - h - pad;
  tip.style.left = x + "px";
  tip.style.top  = y + "px";
}

document.addEventListener("mouseover", e => {
  const el = e.target.closest(".brand-tip");
  if (!el) return;
  const tip = _getTip();
  tip.textContent = el.dataset.tip || "";
  _placeTip(tip, e);
});

document.addEventListener("mousemove", e => {
  if (!_tipEl || _tipEl.style.display === "none") return;
  if (!e.target.closest(".brand-tip")) return;
  _placeTip(_tipEl, e);
});

document.addEventListener("mouseout", e => {
  if (!e.target.closest(".brand-tip")) return;
  if (_tipEl) _tipEl.style.display = "none";
});
