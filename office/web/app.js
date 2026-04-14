const POLL_INTERVAL_MS = 5000;
const STATUS_INTERVAL_MS = 1000;

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

function statusBadge(status, label = status) {
  return `<span class="status-badge status-${escapeHtml(status)}">${escapeHtml(label)}</span>`;
}

function pill(label, className = "muted-pill") {
  return `<span class="pill ${escapeHtml(className)}">${escapeHtml(label)}</span>`;
}

function matchesSearch(text) {
  const query = searchInput.value.trim().toLowerCase();
  if (!query) {
    return true;
  }
  return text.toLowerCase().includes(query);
}

function latestTemp(row) {
  const history = row.temp_history || [];
  const sample = history[history.length - 1];
  return sample?.temp_c;
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

function splitRows(rows, isIssue, textForSearch) {
  const filtered = rows.filter((row) => matchesSearch(textForSearch(row)));
  return {
    all: filtered,
    issues: filtered.filter((row) => isIssue(row)),
    healthy: filtered.filter((row) => !isIssue(row)),
  };
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
      subtitle: "need attention",
      badge: pill(`next ${formatCountdown(refresh.next_heavy_at)}`),
    },
    {
      title: "IP devices",
      value: `${summary.ip_devices_down ?? 0}/${summary.ip_devices_total ?? 0}`,
      subtitle: "need attention",
      badge: pill("polling every 5s"),
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
      subtitle: "highest usage",
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

function sectionHeadline(meta, title, copy) {
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
        <h2>${escapeHtml(title)}</h2>
        <div class="meta-copy">${escapeHtml(copy)}</div>
      </div>
      <div class="meta-row">${badges.join("")}</div>
    </div>
  `;
}

function renderCompactList(title, items) {
  if (!items.length) {
    return "";
  }
  const visible = items.slice(0, 18);
  const hiddenCount = items.length - visible.length;
  return `
    <div class="compact-strip">
      <div class="compact-strip-title">${escapeHtml(title)} (${items.length})</div>
      <div class="compact-list">
        ${visible.map((item) => `<span class="compact-chip">${escapeHtml(item)}</span>`).join("")}
        ${hiddenCount > 0 ? `<span class="compact-chip compact-chip-muted">+${hiddenCount} more</span>` : ""}
      </div>
    </div>
  `;
}

function renderFullTable(columns, rowsHtml) {
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>
    </div>
  `;
}

function renderDevices(snapshot) {
  const meta = snapshot.meta.devices || {};
  const groups = splitRows(
    snapshot.devices || [],
    (row) => !row.ok,
    (row) => `${row.name} ${row.last_path || ""} ${row.error || ""}`,
  );

  if (!groups.all.length) {
    return "";
  }

  const issueRows = groups.issues
    .map((row) => `
      <tr>
        <td>${escapeHtml(row.name)}</td>
        <td>${statusBadge("error")}</td>
        <td class="compact">${escapeHtml(formatRelativeMinutes(row.age_minutes))}</td>
        <td class="compact">${escapeHtml(formatTimestamp(row.last_seen))}</td>
        <td>${escapeHtml(row.error || "-")}</td>
      </tr>
    `)
    .join("");

  const healthyItems = groups.healthy.map((row) => `${row.name} · ${formatRelativeMinutes(row.age_minutes)}`);
  let content = "";
  if (issuesOnlyInput.checked) {
    if (issueRows) {
      content += renderFullTable(["Name", "Status", "Age", "Last seen", "Note"], issueRows);
    }
    content += renderCompactList("Healthy", healthyItems);
  } else {
    const allRows = groups.all
      .map((row) => `
        <tr>
          <td>${escapeHtml(row.name)}</td>
          <td>${statusBadge(row.ok ? "ok" : "error")}</td>
          <td class="compact">${escapeHtml(formatRelativeMinutes(row.age_minutes))}</td>
          <td class="compact">${escapeHtml(formatTimestamp(row.last_seen))}</td>
          <td>${escapeHtml(row.error || "-")}</td>
        </tr>
      `)
      .join("");
    content = renderFullTable(["Name", "Status", "Age", "Last seen", "Note"], allRows);
  }

  return `
    <section class="panel">
      ${sectionHeadline(meta, "Devices", "Registry-based device health. Healthy means last upload is within 4 hours.")}
      ${content}
    </section>
  `;
}

function renderIpDevices(snapshot) {
  const meta = snapshot.meta.ip_devices || {};
  const groups = splitRows(
    snapshot.ip_devices || [],
    (row) => !row.ok || row.over_temp,
    (row) => `${row.name} ${row.detail || ""}`,
  );

  if (!groups.all.length) {
    return "";
  }

  const issueRows = groups.issues
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

  const healthyItems = groups.healthy.map((row) => {
    const temp = latestTemp(row);
    const tempText = temp === undefined ? "no temp" : `${temp.toFixed(1)} C`;
    return `${row.name} · ${tempText}`;
  });

  let content = "";
  if (issuesOnlyInput.checked) {
    if (issueRows) {
      content += renderFullTable(["Name", "Status", "Detail", "Temp"], issueRows);
    }
    content += renderCompactList("Healthy", healthyItems);
  } else {
    const allRows = groups.all
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
    content = renderFullTable(["Name", "Status", "Detail", "Temp"], allRows);
  }

  return `
    <section class="panel">
      ${sectionHeadline(meta, "IP devices", "Direct polls against each device health endpoint.")}
      ${content}
    </section>
  `;
}

function renderRunnerTable(title, rowsData, meta, sectionKey) {
  const groups = splitRows(
    rowsData,
    (row) => row.warn || !row.ok,
    (row) => `${row.name} ${row.detail || ""} ${row.path || ""}`,
  );

  if (!groups.all.length) {
    return "";
  }

  const issueRows = groups.issues
    .map((row) => `
      <tr>
        <td>${escapeHtml(row.name)}</td>
        <td>${statusBadge(rowStatus(row, sectionKey))}</td>
        <td>${escapeHtml(row.detail || "-")}</td>
        <td class="compact">${escapeHtml(row.pending ?? 0)}</td>
      </tr>
    `)
    .join("");

  const healthyItems = groups.healthy.map((row) => row.pending ? `${row.name} · ${row.pending} pending` : row.name);
  let content = "";
  if (issuesOnlyInput.checked) {
    if (issueRows) {
      content += renderFullTable(["Name", "Status", "Detail", "Pending"], issueRows);
    }
    content += renderCompactList("Healthy", healthyItems);
  } else {
    const allRows = groups.all
      .map((row) => `
        <tr>
          <td>${escapeHtml(row.name)}</td>
          <td>${statusBadge(rowStatus(row, sectionKey))}</td>
          <td>${escapeHtml(row.detail || "-")}</td>
          <td class="compact">${escapeHtml(row.pending ?? 0)}</td>
        </tr>
      `)
      .join("");
    content = renderFullTable(["Name", "Status", "Detail", "Pending"], allRows);
  }

  return `
    <section class="panel">
      ${sectionHeadline(meta, title, "Last known state stays visible even if the source goes stale.")}
      ${content}
    </section>
  `;
}

function renderStorage(snapshot) {
  const meta = snapshot.meta.storage || {};
  const rows = ["local", "cloud"]
    .map((key) => ({ key, value: snapshot.storage?.[key] }))
    .filter(({ key, value }) => matchesSearch(`${key} ${value?.name || ""}`));

  if (!rows.length) {
    return "";
  }

  const issueRows = rows
    .filter(({ value }) => storageVolumeStatus(value) !== "ok")
    .map(({ key, value }) => {
      const current = value?.current || {};
      const status = storageVolumeStatus(value);
      return `
        <tr>
          <td>${escapeHtml(value?.name || key)}</td>
          <td>${statusBadge(status)}</td>
          <td class="compact">${escapeHtml(Number(current.used_gb || 0).toFixed(1))} / ${escapeHtml(Number(current.total_gb || 0).toFixed(1))} GB</td>
          <td class="compact">${escapeHtml(Number(current.percent_used || 0).toFixed(1))}%</td>
        </tr>
      `;
    })
    .join("");

  const healthyItems = rows
    .filter(({ value }) => storageVolumeStatus(value) === "ok")
    .map(({ key, value }) => {
      const current = value?.current || {};
      return `${value?.name || key} · ${Number(current.percent_used || 0).toFixed(1)}%`;
    });

  let content = "";
  if (issuesOnlyInput.checked) {
    if (issueRows) {
      content += renderFullTable(["Volume", "Status", "Used", "Percent"], issueRows);
    }
    content += renderCompactList("Healthy", healthyItems);
  } else {
    const allRows = rows
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
    content = renderFullTable(["Volume", "Status", "Used", "Free", "Percent"], allRows);
  }

  return `
    <section class="panel">
      ${sectionHeadline(meta, "Storage", "Healthy storage still shows, just in a compact form when issue emphasis is on.")}
      ${content}
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
        <h2>No matching rows</h2>
        <p class="meta-copy">Nothing matches the current search filter.</p>
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
