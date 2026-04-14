const POLL_INTERVAL_MS = 5000;
const STATUS_INTERVAL_MS = 1000;

const sectionLabels = {
  devices: "Devices",
  ip_devices: "IP devices",
  runners: "Runners",
  tracking: "Tracking",
  storage: "Storage",
};

const searchInput = document.querySelector("#search-input");
const issuesOnlyInput = document.querySelector("#issues-only");
const statusLine = document.querySelector("#status-line");
const summaryGrid = document.querySelector("#summary-grid");
const tablesRoot = document.querySelector("#tables-root");

let latestSnapshot = null;
let requestInFlight = false;

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
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
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

function formatAgeMinutes(minutes) {
  if (minutes === null || minutes === undefined) {
    return "-";
  }
  return formatRelativeMinutes(minutes);
}

function statusBadge(status, label = status) {
  return `<span class="status-badge status-${escapeHtml(status)}">${escapeHtml(label)}</span>`;
}

function pill(label, className = "muted-pill") {
  return `<span class="pill ${escapeHtml(className)}">${escapeHtml(label)}</span>`;
}

function rowMatches(text, isIssue) {
  const query = searchInput.value.trim().toLowerCase();
  if (issuesOnlyInput.checked && !isIssue) {
    return false;
  }
  if (!query) {
    return true;
  }
  return text.toLowerCase().includes(query);
}

function rowStatus(row, sectionKey) {
  if (sectionKey === "runners" || sectionKey === "tracking") {
    if (row.warn) {
      return "warn";
    }
    return row.ok ? "ok" : "error";
  }
  return row.ok ? "ok" : "error";
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

function latestTemp(row) {
  const history = row.temp_history || [];
  const sample = history[history.length - 1];
  return sample?.temp_c;
}

function summaryCards(snapshot) {
  const summary = snapshot.summary || {};
  const refresh = snapshot.refresh || {};
  return [
    {
      title: "Overview",
      value: snapshot.status.toUpperCase(),
      subtitle: `Updated ${formatTimestamp(snapshot.generated_at)}`,
      badge: statusBadge(snapshot.status),
    },
    {
      title: "Devices",
      value: `${summary.devices_down ?? 0}/${summary.devices_total ?? 0}`,
      subtitle: "down",
      badge: pill(`next ${formatCountdown(refresh.next_heavy_at)}`),
    },
    {
      title: "IP devices",
      value: `${summary.ip_devices_down ?? 0}/${summary.ip_devices_total ?? 0}`,
      subtitle: "down",
      badge: pill("live poll 5s"),
    },
    {
      title: "Runners",
      value: `${summary.runner_issues ?? 0}`,
      subtitle: "issues",
      badge: pill(`${summary.tracking_issues ?? 0} tracking`),
    },
    {
      title: "Storage",
      value: `${Math.round(summary.max_storage_percent ?? 0)}%`,
      subtitle: "max used",
      badge: pill(`${summary.stale_sections ?? 0} stale sections`),
    },
  ];
}

function renderSummary(snapshot) {
  summaryGrid.innerHTML = summaryCards(snapshot)
    .map((card) => `
      <article class="summary-card">
        <div class="badge-row">${card.badge}</div>
        <h2>${escapeHtml(card.title)}</h2>
        <div class="summary-value">${escapeHtml(card.value)}</div>
        <div class="summary-subtitle">${escapeHtml(card.subtitle)}</div>
      </article>
    `)
    .join("");
}

function sectionHeadline(meta, subtitle) {
  const badges = [
    statusBadge(meta.status || "stale"),
    pill(`updated ${formatRelativeMinutes(meta.data_age_minutes)}`),
  ];
  if (meta.last_error) {
    badges.push(pill("using last known state", "status-stale"));
  }
  return `
    <div class="panel-header">
      <div class="panel-header-copy">
        <h2>${escapeHtml(subtitle.title)}</h2>
        <div class="meta-copy">${escapeHtml(subtitle.copy)}</div>
      </div>
      <div class="meta-row">${badges.join("")}</div>
    </div>
  `;
}

function renderDevices(snapshot) {
  const meta = snapshot.meta.devices || {};
  const rows = (snapshot.devices || [])
    .filter((row) => rowMatches(`${row.name} ${row.last_path || ""} ${row.error || ""}`, !row.ok))
    .map((row) => `
      <tr>
        <td>${escapeHtml(row.name)}</td>
        <td>${statusBadge(rowStatus(row, "devices"))}</td>
        <td class="compact">${escapeHtml(formatAgeMinutes(row.age_minutes))}</td>
        <td class="compact">${escapeHtml(formatTimestamp(row.last_seen))}</td>
        <td>${escapeHtml(row.error || "-")}</td>
      </tr>
    `)
    .join("");

  if (!rows) {
    return "";
  }

  return `
    <section class="panel">
      ${sectionHeadline(meta, {
        title: "Devices",
        copy: "Registry-based device health. Healthy means last upload is within 4 hours.",
      })}
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>Age</th>
              <th>Last seen</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </section>
  `;
}

function renderIpDevices(snapshot) {
  const meta = snapshot.meta.ip_devices || {};
  const rows = (snapshot.ip_devices || [])
    .filter((row) => rowMatches(`${row.name} ${row.detail || ""}`, !row.ok || row.over_temp))
    .map((row) => {
      const temp = latestTemp(row);
      return `
        <tr>
          <td>${escapeHtml(row.name)}</td>
          <td>${statusBadge(rowStatus(row, "ip_devices"))}</td>
          <td>${escapeHtml(row.detail || "-")}</td>
          <td class="compact">${temp === undefined ? "-" : `${temp.toFixed(1)} C`}</td>
        </tr>
      `;
    })
    .join("");

  if (!rows) {
    return "";
  }

  return `
    <section class="panel">
      ${sectionHeadline(meta, {
        title: "IP devices",
        copy: "Direct polls against each device health endpoint.",
      })}
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>Detail</th>
              <th>Temp</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
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
        <td class="compact">${escapeHtml(row.pending ?? 0)}</td>
      </tr>
    `)
    .join("");

  if (!rows) {
    return "";
  }

  return `
    <section class="panel">
      ${sectionHeadline(meta, {
        title,
        copy: "Last known state stays visible even if the source goes stale.",
      })}
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>Detail</th>
              <th>Pending</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </section>
  `;
}

function renderStorage(snapshot) {
  const meta = snapshot.meta.storage || {};
  const rows = ["local", "cloud"]
    .map((key) => ({ key, value: snapshot.storage?.[key] }))
    .filter(({ key, value }) => rowMatches(`${key} ${value?.name || ""}`, storageVolumeStatus(value) !== "ok"))
    .map(({ key, value }) => {
      const current = value?.current || {};
      const status = storageVolumeStatus(value);
      return `
        <tr>
          <td>${escapeHtml(value?.name || key)}</td>
          <td>${statusBadge(status)}</td>
          <td class="compact">${escapeHtml(Number(current.used_gb || 0).toFixed(1))} / ${escapeHtml(Number(current.total_gb || 0).toFixed(1))} GB</td>
          <td class="compact">${escapeHtml(Number(current.free_gb || 0).toFixed(1))} GB</td>
          <td class="compact">${escapeHtml(Number(current.percent_used || 0).toFixed(1))}%</td>
        </tr>
      `;
    })
    .join("");

  if (!rows) {
    return "";
  }

  return `
    <section class="panel">
      ${sectionHeadline(meta, {
        title: "Storage",
        copy: "Only storage warnings and errors are shown by default.",
      })}
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Volume</th>
              <th>Status</th>
              <th>Used</th>
              <th>Free</th>
              <th>Percent</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </section>
  `;
}

function renderTables(snapshot) {
  const panels = [
    renderDevices(snapshot),
    renderIpDevices(snapshot),
    renderRunnerTable("Runners", snapshot.runners || [], snapshot.meta.runners || {}, "runners"),
    renderRunnerTable("Tracking", snapshot.tracking || [], snapshot.meta.tracking || {}, "tracking"),
    renderStorage(snapshot),
  ].filter(Boolean);

  if (!panels.length) {
    tablesRoot.innerHTML = `
      <section class="panel empty-panel">
        <h2>No current issues</h2>
        <p class="meta-copy">Everything visible matches your current filters. Turn off "Only issues" to inspect all rows.</p>
      </section>
    `;
    return;
  }

  tablesRoot.innerHTML = panels.join("");
}

function render(snapshot) {
  if (!snapshot) {
    return;
  }
  renderSummary(snapshot);
  renderTables(snapshot);
  updateStatusLine(snapshot);
}

function updateStatusLine(snapshot = latestSnapshot) {
  if (!snapshot) {
    return;
  }
  statusLine.textContent =
    `Snapshot ${snapshot.status.toUpperCase()} · updated ${formatTimestamp(snapshot.generated_at)} ` +
    `· server refresh ${formatCountdown(snapshot.refresh?.next_heavy_at)} ` +
    `· page auto-updates every ${Math.floor(POLL_INTERVAL_MS / 1000)}s`;
}

async function loadSnapshot(force = false) {
  if (requestInFlight && !force) {
    return;
  }
  requestInFlight = true;
  try {
    const response = await fetch(`/api/status?ts=${Date.now()}`, {
      cache: "no-store",
      headers: {
        "Cache-Control": "no-store",
        Pragma: "no-cache",
      },
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    latestSnapshot = await response.json();
    render(latestSnapshot);
  } catch (error) {
    statusLine.textContent = `Failed to load snapshot: ${error.message}`;
  } finally {
    requestInFlight = false;
  }
}

searchInput.addEventListener("input", () => render(latestSnapshot));
issuesOnlyInput.addEventListener("change", () => render(latestSnapshot));
window.addEventListener("focus", () => void loadSnapshot(true));
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    void loadSnapshot(true);
  }
});

void loadSnapshot(true);
setInterval(() => void loadSnapshot(), POLL_INTERVAL_MS);
setInterval(() => updateStatusLine(), STATUS_INTERVAL_MS);
