const POLL_INTERVAL_MS = 30000;
const RERENDER_INTERVAL_MS = 15000;

const sectionLabels = {
  devices: "Argo devices",
  ip_devices: "IP devices",
  runners: "Runners",
  tracking: "Tracking",
  storage: "Storage",
};

const searchInput = document.querySelector("#search-input");
const issuesOnlyInput = document.querySelector("#issues-only");
const statusLine = document.querySelector("#status-line");
const summaryGrid = document.querySelector("#summary-grid");
const sectionGrid = document.querySelector("#section-grid");
const tablesRoot = document.querySelector("#tables-root");

let latestSnapshot = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function toDate(value) {
  return value ? new Date(value) : null;
}

function formatTimestamp(value) {
  const date = toDate(value);
  if (!date || Number.isNaN(date.getTime())) {
    return "never";
  }
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatRelativeMinutes(minutes) {
  if (minutes === null || minutes === undefined) {
    return "unknown";
  }
  if (minutes < 1) {
    return "just now";
  }
  if (minutes < 60) {
    return `${minutes}m ago`;
  }
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const mins = minutes % 60;
  if (days > 0) {
    return `${days}d ${hours}h ago`;
  }
  return `${hours}h ${mins}m ago`;
}

function formatCountdown(value) {
  const date = toDate(value);
  if (!date || Number.isNaN(date.getTime())) {
    return "n/a";
  }
  const diffMs = date.getTime() - Date.now();
  if (diffMs <= 0) {
    return "due now";
  }
  const totalSeconds = Math.floor(diffMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

function statusBadge(status, label = status) {
  return `<span class="status-badge status-${escapeHtml(status)}">${escapeHtml(label)}</span>`;
}

function pill(label, className = "muted-pill") {
  return `<span class="pill ${escapeHtml(className)}">${escapeHtml(label)}</span>`;
}

function sparkline(points, valueKey) {
  const values = points
    .map((point) => Number(point?.[valueKey]))
    .filter((value) => Number.isFinite(value));

  if (values.length < 2) {
    return '<span class="subtle">n/a</span>';
  }

  const width = 128;
  const height = 36;
  const padding = 3;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;

  const polyline = values
    .map((value, index) => {
      const x = padding + (index / (values.length - 1)) * (width - padding * 2);
      const y = height - padding - ((value - min) / span) * (height - padding * 2);
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  return `
    <svg class="sparkline" viewBox="0 0 ${width} ${height}" aria-hidden="true">
      <line class="sparkline-grid" x1="0" y1="${height - padding}" x2="${width}" y2="${height - padding}"></line>
      <polyline points="${polyline}"></polyline>
    </svg>
  `;
}

function rowMatches(text, isIssue) {
  const query = searchInput.value.trim().toLowerCase();
  const issuesOnly = issuesOnlyInput.checked;
  if (issuesOnly && !isIssue) {
    return false;
  }
  if (!query) {
    return true;
  }
  return text.toLowerCase().includes(query);
}

function rowStatus(row, sectionKey) {
  if (sectionKey === "devices") {
    return row.ok ? "ok" : "error";
  }
  if (sectionKey === "ip_devices") {
    return row.ok ? "ok" : "error";
  }
  if (sectionKey === "runners" || sectionKey === "tracking") {
    if (row.warn) {
      return "warn";
    }
    return row.ok ? "ok" : "error";
  }
  return "ok";
}

function storageVolumeStatus(volume) {
  const percent = volume?.current?.percent_used;
  if (percent === undefined || percent === null) {
    return "stale";
  }
  if (percent >= 95) {
    return "error";
  }
  if (percent >= 85) {
    return "warn";
  }
  return "ok";
}

function renderSummary(snapshot) {
  const summary = snapshot.summary || {};
  const refresh = snapshot.refresh || {};
  const cards = [
    {
      title: "Overall",
      value: snapshot.status.toUpperCase(),
      subtitle: `Updated ${formatTimestamp(snapshot.generated_at)}`,
      badge: statusBadge(snapshot.status),
    },
    {
      title: "Argo devices",
      value: summary.devices_total ?? 0,
      subtitle: `${summary.devices_down ?? 0} down`,
      badge: pill(`next ${formatCountdown(refresh.next_refresh_at)}`),
    },
    {
      title: "IP devices",
      value: summary.ip_devices_total ?? 0,
      subtitle: `${summary.ip_devices_down ?? 0} down`,
      badge: pill(`refresh ${formatCountdown(refresh.next_refresh_at)}`),
    },
    {
      title: "Runners + tracking",
      value: (summary.runner_issues ?? 0) + (summary.tracking_issues ?? 0),
      subtitle: "open issues",
      badge: pill(`sync ${formatCountdown(refresh.next_heavy_at)}`),
    },
    {
      title: "Storage",
      value: `${Math.round(summary.max_storage_percent ?? 0)}%`,
      subtitle: "highest usage",
      badge: pill(`${summary.stale_sections ?? 0} stale sections`),
    },
  ];

  summaryGrid.innerHTML = cards
    .map((card) => `
      <article class="summary-card">
        <div class="badge-row">
          ${card.badge}
        </div>
        <h2>${escapeHtml(card.title)}</h2>
        <div class="summary-value">${escapeHtml(card.value)}</div>
        <div class="summary-subtitle">${escapeHtml(card.subtitle)}</div>
      </article>
    `)
    .join("");
}

function renderSectionCards(snapshot) {
  const meta = snapshot.meta || {};
  sectionGrid.innerHTML = Object.entries(sectionLabels)
    .map(([key, label]) => {
      const sectionMeta = meta[key] || {};
      const details = [
        `checked ${formatRelativeMinutes(sectionMeta.checked_age_minutes)}`,
        `data ${formatRelativeMinutes(sectionMeta.data_age_minutes)}`,
      ];
      if (sectionMeta.source) {
        details.push(sectionMeta.source);
      }
      return `
        <article class="section-card">
          <div class="badge-row">
            ${statusBadge(sectionMeta.status || "stale")}
            ${pill(details.join(" · "))}
          </div>
          <h2>${escapeHtml(label)}</h2>
          <p class="section-detail">${escapeHtml((sectionMeta.summary && JSON.stringify(sectionMeta.summary)) || "No summary yet.")}</p>
          ${sectionMeta.last_error ? `<p class="error-copy">${escapeHtml(sectionMeta.last_error)}</p>` : ""}
        </article>
      `;
    })
    .join("");
}

function renderDevices(snapshot) {
  const meta = snapshot.meta.devices || {};
  const rows = (snapshot.devices || [])
    .filter((row) => rowMatches(`${row.name} ${row.last_path || ""} ${row.error || ""}`, !row.ok))
    .map((row) => `
      <tr>
        <td>${escapeHtml(row.name)}</td>
        <td>${statusBadge(rowStatus(row, "devices"))}</td>
        <td>${escapeHtml(formatTimestamp(row.last_seen))}</td>
        <td>${escapeHtml(row.age_minutes ?? "n/a")}m</td>
        <td class="mono">${escapeHtml(row.last_path || "-")}</td>
        <td>${escapeHtml(row.error || "-")}</td>
      </tr>
    `)
    .join("");

  return `
    <section class="panel">
      <div class="panel-header">
        <div class="panel-header-copy">
          <h2>Argo devices</h2>
          <div class="meta-copy">Latest uploads inferred from registry listings.</div>
        </div>
        <div class="meta-row">
          ${statusBadge(meta.status || "stale")}
          ${pill(`checked ${formatTimestamp(meta.checked_at)}`)}
          ${pill(`age ${formatRelativeMinutes(meta.data_age_minutes)}`)}
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>Last seen</th>
              <th>Age</th>
              <th>Last path</th>
              <th>Error</th>
            </tr>
          </thead>
          <tbody>
            ${rows || '<tr><td colspan="6" class="empty-state">No matching device rows.</td></tr>'}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function renderIpDevices(snapshot) {
  const meta = snapshot.meta.ip_devices || {};
  const rows = (snapshot.ip_devices || [])
    .filter((row) => rowMatches(`${row.name} ${row.detail || ""}`, !row.ok || row.over_temp))
    .map((row) => `
      <tr>
        <td>${escapeHtml(row.name)}</td>
        <td>${statusBadge(rowStatus(row, "ip_devices"))}</td>
        <td>${escapeHtml(row.detail || "-")}</td>
        <td>${row.tmux_running ? pill("tmux ok", "status-ok") : pill("tmux down", "status-error")}</td>
        <td>${row.over_temp ? pill("over temp", "status-error") : pill("temp ok", "status-ok")}</td>
        <td>${sparkline(row.temp_history || [], "temp_c")}</td>
      </tr>
    `)
    .join("");

  return `
    <section class="panel">
      <div class="panel-header">
        <div class="panel-header-copy">
          <h2>IP devices</h2>
          <div class="meta-copy">Polled from each device's local <span class="mono">/health</span> endpoint.</div>
        </div>
        <div class="meta-row">
          ${statusBadge(meta.status || "stale")}
          ${pill(`checked ${formatTimestamp(meta.checked_at)}`)}
          ${pill(`age ${formatRelativeMinutes(meta.data_age_minutes)}`)}
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>Detail</th>
              <th>Tmux</th>
              <th>Temperature</th>
              <th>Trend</th>
            </tr>
          </thead>
          <tbody>
            ${rows || '<tr><td colspan="6" class="empty-state">No matching IP device rows.</td></tr>'}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function renderRunnerTable(title, rowsData, meta, sectionKey) {
  const rows = rowsData
    .filter((row) => rowMatches(`${row.name} ${row.detail || ""} ${row.path || ""}`, row.warn || !row.ok))
    .map((row) => `
      <tr>
        <td>${escapeHtml(row.name)}</td>
        <td>${statusBadge(rowStatus(row, sectionKey))}</td>
        <td>${escapeHtml(row.detail || "-")}</td>
        <td>${escapeHtml(row.pending ?? 0)}</td>
        <td class="mono">${escapeHtml(row.path || "-")}</td>
      </tr>
    `)
    .join("");

  return `
    <section class="panel">
      <div class="panel-header">
        <div class="panel-header-copy">
          <h2>${escapeHtml(title)}</h2>
          <div class="meta-copy">Last known section state remains visible even when data becomes stale.</div>
        </div>
        <div class="meta-row">
          ${statusBadge(meta.status || "stale")}
          ${pill(`checked ${formatTimestamp(meta.checked_at)}`)}
          ${pill(`age ${formatRelativeMinutes(meta.data_age_minutes)}`)}
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>Detail</th>
              <th>Pending</th>
              <th>Path</th>
            </tr>
          </thead>
          <tbody>
            ${rows || '<tr><td colspan="5" class="empty-state">No matching rows.</td></tr>'}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function renderStorage(snapshot) {
  const meta = snapshot.meta.storage || {};
  const entries = ["local", "cloud"]
    .map((key) => ({ key, value: snapshot.storage?.[key] }))
    .filter((entry) => rowMatches(`${entry.key} ${entry.value?.name || ""}`, storageVolumeStatus(entry.value) !== "ok"));

  const cards = entries
    .map(({ key, value }) => {
      const current = value?.current || {};
      const percent = Number(current.percent_used || 0);
      const status = storageVolumeStatus(value);
      return `
        <article class="storage-card">
          <div class="badge-row">
            ${statusBadge(status)}
            ${pill(formatRelativeMinutes(meta.data_age_minutes))}
          </div>
          <h3>${escapeHtml(value?.name || key)}</h3>
          <div class="summary-value">${escapeHtml(percent.toFixed(1))}%</div>
          <div class="summary-subtitle">
            ${escapeHtml(Number(current.used_gb || 0).toFixed(1))} GB used of
            ${escapeHtml(Number(current.total_gb || 0).toFixed(1))} GB
          </div>
          <div class="storage-bar"><span style="width:${Math.min(percent, 100)}%"></span></div>
          <div>${sparkline(value?.history || [], "used_gb")}</div>
        </article>
      `;
    })
    .join("");

  return `
    <section class="panel">
      <div class="panel-header">
        <div class="panel-header-copy">
          <h2>Storage</h2>
          <div class="meta-copy">Local and cloud storage snapshots with persisted trends.</div>
        </div>
        <div class="meta-row">
          ${statusBadge(meta.status || "stale")}
          ${pill(`checked ${formatTimestamp(meta.checked_at)}`)}
          ${pill(`age ${formatRelativeMinutes(meta.data_age_minutes)}`)}
        </div>
      </div>
      <div class="storage-grid">
        ${cards || '<div class="empty-state">No matching storage rows.</div>'}
      </div>
    </section>
  `;
}

function renderTables(snapshot) {
  tablesRoot.innerHTML = [
    renderDevices(snapshot),
    renderIpDevices(snapshot),
    renderRunnerTable("Runners", snapshot.runners || [], snapshot.meta.runners || {}, "runners"),
    renderRunnerTable("Tracking", snapshot.tracking || [], snapshot.meta.tracking || {}, "tracking"),
    renderStorage(snapshot),
  ].join("");
}

function render(snapshot) {
  if (!snapshot) {
    return;
  }

  renderSummary(snapshot);
  renderSectionCards(snapshot);
  renderTables(snapshot);

  statusLine.textContent =
    `Snapshot ${snapshot.status.toUpperCase()} · updated ${formatTimestamp(snapshot.generated_at)} ` +
    `· next refresh ${formatCountdown(snapshot.refresh?.next_refresh_at)} ` +
    `· next sync ${formatCountdown(snapshot.refresh?.next_heavy_at)}`;
}

async function loadSnapshot() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    latestSnapshot = await response.json();
    render(latestSnapshot);
  } catch (error) {
    statusLine.textContent = `Failed to load snapshot: ${error.message}`;
  }
}

searchInput.addEventListener("input", () => render(latestSnapshot));
issuesOnlyInput.addEventListener("change", () => render(latestSnapshot));

loadSnapshot();
setInterval(loadSnapshot, POLL_INTERVAL_MS);
setInterval(() => render(latestSnapshot), RERENDER_INTERVAL_MS);
