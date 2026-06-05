const roleSelect = document.querySelector("#role-select");
const typeSelect = document.querySelector("#type-select");
const loadButton = document.querySelector("#load-button");
const refreshButton = document.querySelector("#refresh-button");
const statusPanel = document.querySelector("#status");
const jobList = document.querySelector("#job-list");
const cachePill = document.querySelector("#cache-pill");
const activeRole = document.querySelector("#active-role");
const jobCount = document.querySelector("#job-count");
const fetchedAt = document.querySelector("#fetched-at");

function setStatus(message, tone = "") {
  statusPanel.textContent = message;
  statusPanel.className = `status-panel ${tone}`.trim();
}

function setBusy(isBusy) {
  loadButton.disabled = isBusy;
  refreshButton.disabled = isBusy;
  roleSelect.disabled = isBusy;
  typeSelect.disabled = isBusy;
}

function formatDate(value) {
  if (!value) return "Not refreshed";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function sourceName(value) {
  const text = String(value || "unknown").trim();
  return text ? text.toUpperCase() : "UNKNOWN";
}

function renderJobs(payload) {
  activeRole.textContent = payload.role_label || "-";
  jobCount.textContent = `${payload.count || 0} job${payload.count === 1 ? "" : "s"}`;
  fetchedAt.textContent = formatDate(payload.fetched_at);
  cachePill.textContent = payload.cache_status === "hit" ? "Cache loaded" : "Cache missing";
  cachePill.className = `cache-pill ${payload.cache_status || "missing"}`;

  if (payload.cache_status === "missing") {
    jobList.innerHTML = `<div class="empty-state">${payload.message || "No cached jobs yet."}</div>`;
    return;
  }

  if (!payload.jobs?.length) {
    jobList.innerHTML = `<div class="empty-state">No ${typeSelect.options[typeSelect.selectedIndex].text.toLowerCase()} found in this cache.</div>`;
    return;
  }

  jobList.innerHTML = payload.jobs.map((job) => {
    const skills = (job.skills || []).slice(0, 8).map((skill) => `<span>${escapeHtml(skill)}</span>`).join("");
    const internshipBadge = job.is_internship ? `<span class="badge internship">Internship</span>` : "";
    const description = job.description ? `<p class="job-description">${escapeHtml(job.description)}</p>` : "";
    const apply = job.job_url ? `<a class="apply-link" href="${escapeAttribute(job.job_url)}" target="_blank" rel="noreferrer">Open posting</a>` : "";
    return `
      <article class="job-card">
        <header>
          <h2>${escapeHtml(job.title)}</h2>
          <p class="company-line">${escapeHtml(job.company)} · ${escapeHtml(job.location)}</p>
        </header>
        <div class="badge-row">
          <span class="badge source">${escapeHtml(sourceName(job.board))}</span>
          <span class="badge">${escapeHtml(job.employment_type || "Not specified")}</span>
          ${internshipBadge}
        </div>
        ${skills ? `<div class="skill-row">${skills}</div>` : ""}
        ${description}
        ${apply}
      </article>
    `;
  }).join("");
}

async function requestJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Request failed");
  return data;
}

async function loadRoles() {
  const data = await requestJson("/api/roles");
  roleSelect.innerHTML = data.roles.map((role) => (
    `<option value="${escapeAttribute(role.key)}">${escapeHtml(role.label)}</option>`
  )).join("");
}

async function loadCache() {
  const role = roleSelect.value;
  const type = typeSelect.value;
  setBusy(true);
  setStatus("Reading local cache...", "loading");
  try {
    const payload = await requestJson(`/api/jobs?role=${encodeURIComponent(role)}&type=${encodeURIComponent(type)}`);
    renderJobs(payload);
    setStatus(payload.cache_status === "hit" ? "Loaded cached jobs." : payload.message);
  } catch (error) {
    setStatus(error.message || "Could not load jobs.", "error");
  } finally {
    setBusy(false);
  }
}

async function refreshJobs() {
  const role = roleSelect.value;
  const type = typeSelect.value;
  setBusy(true);
  setStatus("Scraping fresh jobs. This can take a while, especially with LinkedIn enabled...", "loading");
  try {
    const payload = await requestJson(`/api/jobs/refresh?role=${encodeURIComponent(role)}&type=${encodeURIComponent(type)}`, {
      method: "POST",
    });
    renderJobs(payload);
    const warning = payload.errors?.length ? ` ${payload.errors.length} warning(s) were recorded.` : "";
    setStatus(`Refresh complete. Saved ${payload.total_cached || 0} cached posting(s).${warning}`);
  } catch (error) {
    setStatus(error.message || "Refresh failed.", "error");
  } finally {
    setBusy(false);
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

loadButton.addEventListener("click", loadCache);
refreshButton.addEventListener("click", refreshJobs);
roleSelect.addEventListener("change", loadCache);
typeSelect.addEventListener("change", loadCache);

loadRoles()
  .then(loadCache)
  .catch((error) => setStatus(error.message || "Could not load roles.", "error"));
