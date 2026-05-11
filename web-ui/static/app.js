const state = {
  ws: null,
  connected: false,
  files: {},
  activeTable: "",
  selectedTables: new Set(),
  lastColumns: [],
  lastRows: [],
  lastSql: "",
  lastChartType: "None"
};

const $ = (id) => document.getElementById(id);
const starters = [
  "Show all meter details",
  "Count meters by status as a bar chart",
  "Show HES wise smart meter distribution",
  "Find consumers with missing GPS coordinates",
  "Show consumption trend over time as a line chart",
  "Detect unusual spikes or zero readings"
];

document.addEventListener("DOMContentLoaded", () => {
  buildStarters();
  bindEvents();
  connectWebSocket();
  refreshStatus();
});

function bindEvents() {
  $("file-input").addEventListener("change", (event) => uploadFiles([...event.target.files]));
  $("refresh-btn").addEventListener("click", refreshStatus);
  $("clear-btn").addEventListener("click", clearMemory);
  $("send-btn").addEventListener("click", sendQuery);
  $("query-input").addEventListener("input", autoSizeInput);
  $("query-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendQuery();
    }
  });

  const dropZone = $("drop-zone");
  ["dragenter", "dragover"].forEach((name) => dropZone.addEventListener(name, (event) => {
    event.preventDefault();
    dropZone.classList.add("drag");
  }));
  ["dragleave", "drop"].forEach((name) => dropZone.addEventListener(name, (event) => {
    event.preventDefault();
    dropZone.classList.remove("drag");
  }));
  dropZone.addEventListener("drop", (event) => uploadFiles([...event.dataTransfer.files]));

  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => switchTab(tab.dataset.tab)));
  document.querySelectorAll(".chart-tools button").forEach((button) => button.addEventListener("click", () => redrawChart(button.dataset.chart)));
  $("download-btn").addEventListener("click", downloadCsv);
  $("copy-sql").addEventListener("click", copySql);
}

function buildStarters() {
  const grid = $("starter-grid");
  starters.forEach((text) => {
    const button = document.createElement("button");
    button.className = "starter";
    button.textContent = text;
    button.addEventListener("click", () => {
      $("query-input").value = text;
      autoSizeInput();
      sendQuery();
    });
    grid.appendChild(button);
  });
}

function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  state.ws = new WebSocket(`${protocol}://${location.host}/ws`);
  state.ws.onopen = () => {
    state.connected = true;
    updateConnection(true);
    autoSizeInput();
  };
  state.ws.onclose = () => {
    state.connected = false;
    updateConnection(false);
    setTimeout(connectWebSocket, 1600);
  };
  state.ws.onerror = () => updateConnection(false);
  state.ws.onmessage = (event) => handleWsMessage(JSON.parse(event.data));
}

function handleWsMessage(message) {
  if (message.type === "thinking") {
    $("thinking").style.display = "flex";
    scrollChat();
    return;
  }
  $("thinking").style.display = "none";
  $("send-btn").disabled = false;

  if (message.type === "error") {
    addMessage("ai", message.text || "Something went wrong.", { error: true, sql: message.sql });
    toast(message.text || "Query failed", "error");
    return;
  }
  if (message.type === "status") {
    toast(message.text || "Status updated");
    return;
  }
  if (message.type === "result") {
    renderResult(message);
  }
}

async function refreshStatus() {
  try {
    const response = await fetch("/status");
    const status = await response.json();
    $("engine-label").textContent = cleanEngine(status.engine_badge || status.ai_engine || "AI Engine");
    $("metric-limit").textContent = Number(status.max_rows || 0).toLocaleString();

    state.files = {};
    (status.tables || []).forEach((table) => {
      state.files[table.name] = { ...table, type: "table", filename: table.name };
    });
    (status.documents || []).forEach((name) => {
      state.files[name] = { name, type: "document", filename: name };
    });
    state.activeTable = status.active_table || state.activeTable || ((status.tables || [])[0] || {}).name || "";
    if (state.activeTable && state.selectedTables.size === 0) state.selectedTables.add(state.activeTable);
    renderFiles();
    renderScope();
    updateCounts();
  } catch (error) {
    toast(`Status refresh failed: ${error.message}`, "error");
  }
}

async function uploadFiles(files) {
  for (const file of files) {
    await uploadFile(file);
  }
  $("file-input").value = "";
}

async function uploadFile(file) {
  const form = new FormData();
  form.append("file", file);
  toast(`Uploading ${file.name}...`);
  try {
    const response = await fetch("/upload", { method: "POST", body: form });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || "Upload failed");
    state.files[data.name] = data;
    if (data.type === "table") {
      state.activeTable = data.name;
      state.selectedTables.clear();
      state.selectedTables.add(data.name);
      setActiveTable(data.name);
    }
    renderFiles();
    renderScope();
    updateCounts();
    $("welcome").style.display = "none";
    toast(`${data.filename || data.name} loaded successfully`, "success");
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderFiles() {
  const list = $("file-list");
  list.innerHTML = "";
  const entries = Object.values(state.files);
  if (!entries.length) {
    const empty = document.createElement("div");
    empty.id = "empty-files";
    empty.className = "empty-state";
    empty.textContent = "Upload meter, consumer, billing, outage, HES, or interval reading data to begin.";
    list.appendChild(empty);
    return;
  }
  entries.forEach((file) => {
    const isTable = file.type === "table";
    const item = document.createElement("div");
    item.className = `file-item ${file.name === state.activeTable && isTable ? "active" : ""}`;
    item.innerHTML = `
      <div class="file-icon ${isTable ? "" : "doc"}">${isTable ? "DATA" : "DOC"}</div>
      <div>
        <div class="file-name" title="${escapeHtml(file.filename || file.name)}">${escapeHtml(file.filename || file.name)}</div>
        <div class="file-meta">${fileMeta(file)}</div>
      </div>
      <button class="delete-btn" title="Remove">x</button>
    `;
    if (isTable) {
      item.addEventListener("click", (event) => {
        if (event.target.closest("button")) return;
        state.activeTable = file.name;
        state.selectedTables.clear();
        state.selectedTables.add(file.name);
        setActiveTable(file.name);
        renderFiles();
        renderScope();
      });
    }
    item.querySelector("button").addEventListener("click", () => deleteFile(file));
    list.appendChild(item);
  });
}

function fileMeta(file) {
  if (file.type === "table") {
    const colCount = (file.columns || []).length;
    return `${Number(file.rows || 0).toLocaleString()} rows, ${colCount} columns`;
  }
  if (file.char_count) return `${Number(file.char_count).toLocaleString()} chars, ${file.format || "document"}`;
  return "Document loaded";
}

async function deleteFile(file) {
  const endpoint = file.type === "table" ? `/table/${encodeURIComponent(file.name)}` : `/document/${encodeURIComponent(file.name)}`;
  try {
    const response = await fetch(endpoint, { method: "DELETE" });
    if (!response.ok) throw new Error("Remove failed");
    delete state.files[file.name];
    state.selectedTables.delete(file.name);
    if (state.activeTable === file.name) state.activeTable = firstTableName();
    if (state.activeTable) state.selectedTables.add(state.activeTable);
    renderFiles();
    renderScope();
    updateCounts();
    toast(`${file.filename || file.name} removed`, "success");
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderScope() {
  const bar = $("scope-bar");
  bar.innerHTML = `<span class="scope-label">Query scope</span>`;
  const tables = Object.values(state.files).filter((file) => file.type === "table");
  if (!tables.length) {
    const span = document.createElement("span");
    span.className = "scope-label";
    span.textContent = "Upload a table to enable scoped queries";
    bar.appendChild(span);
    return;
  }
  const all = document.createElement("button");
  all.className = `chip ${state.selectedTables.size === tables.length ? "selected" : ""}`;
  all.textContent = "All tables";
  all.addEventListener("click", () => {
    state.selectedTables = new Set(tables.map((table) => table.name));
    renderScope();
  });
  bar.appendChild(all);
  tables.forEach((table) => {
    const chip = document.createElement("button");
    chip.className = `chip ${state.selectedTables.has(table.name) ? "selected" : ""}`;
    chip.textContent = table.name;
    chip.addEventListener("click", () => {
      if (state.selectedTables.has(table.name) && state.selectedTables.size > 1) state.selectedTables.delete(table.name);
      else state.selectedTables.add(table.name);
      state.activeTable = table.name;
      setActiveTable(table.name);
      renderScope();
      renderFiles();
    });
    bar.appendChild(chip);
  });
}

function updateCounts() {
  const files = Object.values(state.files);
  const tables = files.filter((file) => file.type === "table").length;
  const docs = files.filter((file) => file.type === "document").length;
  $("metric-tables").textContent = tables;
  $("metric-docs").textContent = docs;
  $("count-tables").textContent = tables;
  $("count-docs").textContent = docs;
  $("inventory-count").textContent = `${files.length} file${files.length === 1 ? "" : "s"}`;
}

function setActiveTable(name) {
  if (state.ws && state.connected) {
    state.ws.send(JSON.stringify({ action: "set_active", table: name }));
  }
}

function sendQuery() {
  const input = $("query-input");
  const text = input.value.trim();
  if (!text || !state.connected) return;
  $("welcome").style.display = "none";
  addMessage("user", text);
  input.value = "";
  autoSizeInput();
  $("send-btn").disabled = true;
  const targetTables = [...state.selectedTables].filter(Boolean);
  state.ws.send(JSON.stringify({ action: "query", text, target_tables: targetTables }));
}

function renderResult(message) {
  state.lastColumns = message.columns || [];
  state.lastRows = message.table_data || [];
  state.lastSql = message.sql || "";
  state.lastChartType = titleCase(message.chart_type || (message.chart ? "chart" : "table"));

  addMessage("ai", message.answer || "Query completed.", {
    badge: cleanEngine(message.engine_badge || message.mode || "Result"),
    insights: message.insights,
    sql: message.sql,
    followUps: message.follow_ups || [],
    rows: message.row_count
  });

  updateResultSummary(message);
  renderTable(message.columns || [], message.table_data || [], message.row_count || 0);
  renderSql(message.sql || "");
  if (message.chart) {
    renderChart(message.chart);
    switchTab("chart");
  } else if ((message.table_data || []).length) {
    clearChart();
    switchTab("table");
  }
}

function addMessage(role, text, options = {}) {
  const div = document.createElement("div");
  div.className = `message ${role}`;
  const avatar = role === "user" ? "YOU" : (options.error ? "!" : "AI");
  let html = `<div class="avatar">${avatar}</div><div class="bubble">`;
  if (options.badge) html += `<div class="badge">${escapeHtml(options.badge)}</div>`;
  html += formatText(text);
  if (options.insights) html += `<div class="insight">${escapeHtml(options.insights)}</div>`;
  if (options.rows) html += `<div class="badge" style="margin-top:10px">${Number(options.rows).toLocaleString()} rows returned</div>`;
  if (options.sql) {
    html += `<div class="sql-box"><div class="sql-head"><span>SQL</span><button class="chip" onclick="navigator.clipboard.writeText(state.lastSql)">Copy</button></div><pre>${escapeHtml(options.sql)}</pre></div>`;
  }
  if (options.followUps && options.followUps.length) {
    html += `<div class="follow-ups">${options.followUps.map((q) => `<button onclick="askFollowUp('${escapeAttr(q)}')">${escapeHtml(q)}</button>`).join("")}</div>`;
  }
  html += "</div>";
  div.innerHTML = html;
  $("chat").insertBefore(div, $("thinking"));
  scrollChat();
}

function updateResultSummary(message) {
  $("summary-rows").textContent = Number(message.row_count || 0).toLocaleString();
  $("summary-cols").textContent = Number((message.columns || []).length).toLocaleString();
  $("summary-chart").textContent = titleCase(message.chart_type || "None");
}

function renderTable(columns, rows, totalRows) {
  const table = $("data-table");
  if (!columns.length || !rows.length) {
    table.style.display = "none";
    $("table-empty").style.display = "grid";
    $("table-info").textContent = "No rows loaded";
    return;
  }
  $("table-empty").style.display = "none";
  table.style.display = "table";
  $("table-head").innerHTML = `<tr>${columns.map((column) => `<th title="${escapeHtml(column)}">${escapeHtml(column)}</th>`).join("")}</tr>`;
  $("table-body").innerHTML = rows.map((row) => `<tr>${columns.map((column) => {
    const value = row[column];
    const text = value === null || value === undefined || value === "" ? "-" : String(value);
    return `<td class="${typeof value === "number" ? "num" : ""}" title="${escapeHtml(text)}">${escapeHtml(text)}</td>`;
  }).join("")}</tr>`).join("");
  $("table-info").textContent = `Showing ${rows.length.toLocaleString()} of ${Number(totalRows || rows.length).toLocaleString()} rows`;
}

function renderSql(sql) {
  if (!sql) {
    $("sql-empty").style.display = "grid";
    $("sql-result").style.display = "none";
    return;
  }
  $("sql-empty").style.display = "none";
  $("sql-result").style.display = "block";
  $("sql-text").textContent = sql;
}

function renderChart(chartJson) {
  try {
    const spec = JSON.parse(chartJson);
    $("chart-empty").style.display = "none";
    $("chart").style.display = "block";
    Plotly.react("chart", spec.data || [], {
      ...(spec.layout || {}),
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "#f8fafc",
      font: { color: "#162033", size: 12, family: "Inter, Segoe UI, sans-serif" },
      margin: { l: 52, r: 22, t: 52, b: 48 },
      colorway: ["#0f7c90", "#f5a623", "#248a52", "#6b5bd3", "#c2413d", "#4f8bd6"],
      xaxis: { gridcolor: "#dce4ec", zerolinecolor: "#c5d3df" },
      yaxis: { gridcolor: "#dce4ec", zerolinecolor: "#c5d3df" }
    }, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["lasso2d", "select2d"] });
  } catch (error) {
    clearChart();
    toast(`Chart rendering failed: ${error.message}`, "error");
  }
}

function redrawChart(type) {
  if (!state.lastRows.length || !state.lastColumns.length) {
    toast("No result data available to chart", "error");
    return;
  }
  const columns = state.lastColumns;
  const rows = state.lastRows;
  const numeric = columns.filter((column) => rows.some((row) => typeof row[column] === "number"));
  const nonNumeric = columns.filter((column) => !numeric.includes(column));
  const xColumn = nonNumeric[0] || columns[0];
  const yColumn = numeric[0] || columns[1] || columns[0];
  const x = rows.map((row) => row[xColumn]);
  const y = rows.map((row) => row[yColumn]);
  let data;
  if (type === "line" || type === "area") data = [{ x, y, type: "scatter", mode: "lines+markers", fill: type === "area" ? "tozeroy" : "none", line: { color: "#0f7c90", width: 3 } }];
  else if (type === "pie") data = [{ labels: x, values: y, type: "pie", hole: 0.38 }];
  else if (type === "scatter") data = [{ x: numeric[0] ? rows.map((row) => row[numeric[0]]) : x, y: numeric[1] ? rows.map((row) => row[numeric[1]]) : y, type: "scatter", mode: "markers", marker: { color: "#0f7c90", size: 8 } }];
  else if (type === "histogram") data = [{ x: y, type: "histogram", marker: { color: "#0f7c90" } }];
  else data = [{ x, y, type: "bar", marker: { color: "#0f7c90" } }];
  renderChart(JSON.stringify({ data, layout: { title: `${titleCase(type)} chart: ${yColumn} by ${xColumn}` } }));
  $("summary-chart").textContent = titleCase(type);
  switchTab("chart");
}

function clearChart() {
  $("chart").style.display = "none";
  $("chart-empty").style.display = "grid";
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === `panel-${name}`));
  if (name === "chart" && $("chart").style.display !== "none" && window.Plotly) {
    setTimeout(() => Plotly.Plots.resize("chart"), 120);
  }
}

function askFollowUp(text) {
  $("query-input").value = text;
  autoSizeInput();
  sendQuery();
}

function clearMemory() {
  if (state.ws && state.connected) {
    state.ws.send(JSON.stringify({ action: "clear_memory" }));
  }
}

function copySql() {
  navigator.clipboard.writeText(state.lastSql || "");
  toast("SQL copied", "success");
}

function downloadCsv() {
  if (!state.lastRows.length || !state.lastColumns.length) {
    toast("No rows to download", "error");
    return;
  }
  const csv = [
    state.lastColumns.join(","),
    ...state.lastRows.map((row) => state.lastColumns.map((column) => csvCell(row[column])).join(","))
  ].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${state.activeTable || "datagrid-result"}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function updateConnection(connected) {
  $("conn-dot").classList.toggle("ok", connected);
  $("conn-label").textContent = connected ? "Online" : "Offline";
  autoSizeInput();
}

function autoSizeInput() {
  const input = $("query-input");
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
  $("send-btn").disabled = !input.value.trim() || !state.connected;
}

function firstTableName() {
  const first = Object.values(state.files).find((file) => file.type === "table");
  return first ? first.name : "";
}

function scrollChat() {
  $("chat").scrollTop = $("chat").scrollHeight;
}

function cleanEngine(value) {
  return String(value).replace(/[^\w .:;()\/+\-·]/g, "").trim() || "AI Engine";
}

function titleCase(value) {
  return String(value || "").replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatText(text) {
  return escapeHtml(text || "").split("\n").join("<br>");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));
}

function escapeAttr(value) {
  return String(value ?? "").replace(/\\/g, "\\\\").replace(/'/g, "\\'").replace(/"/g, "&quot;");
}

function csvCell(value) {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function toast(text, type = "info") {
  const item = document.createElement("div");
  item.className = `toast ${type}`;
  item.textContent = text;
  $("toast-wrap").appendChild(item);
  setTimeout(() => item.remove(), 3200);
}