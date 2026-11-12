const NATIONAL_VIEW = { center: [23.6, -102.5], zoom: 5 };

const CONFIDENCE_COLORS = {
  alta: "#d64550",
  media: "#f2c811",
  baja: "#8a8886",
};

const CONFIDENCE_INK = {
  alta: "#8a1c25",
  media: "#6b4e00",
  baja: "#3b3a39",
};

const COLUMNS = [
  { key: "rank", label: "#", numeric: true, sortable: true },
  { key: "place", label: "Punto crítico", numeric: false, sortable: true },
  { key: "municipality_name", label: "Municipio", numeric: false, sortable: true },
  { key: "state_name", label: "Estado", numeric: false, sortable: true },
  { key: "dominant_type_label", label: "Tipo dominante", numeric: false, sortable: true },
  { key: "crashes", label: "Choques", numeric: true, sortable: true },
  { key: "deaths", label: "Muertes", numeric: true, sortable: true },
  { key: "injured", label: "Heridos", numeric: true, sortable: true },
  { key: "fatal_share", label: "Letalidad", numeric: true, sortable: true },
  { key: "peak_hour", label: "Hora pico", numeric: true, sortable: true },
  { key: "confidence", label: "Confianza", numeric: false, sortable: true },
  { key: "primary_action", label: "Acción principal", numeric: false, sortable: false },
];

const NUMERIC_KEYS = new Set(COLUMNS.filter((column) => column.numeric).map((column) => column.key));

const state = {
  rows: [],
  filtered: [],
  selectedId: null,
  sortKey: "rank",
  sortDir: 1,
  filters: { state: "all", type: "all", confidence: "all", search: "" },
};

const els = {
  status: document.getElementById("status"),
  subtitle: document.getElementById("report-subtitle"),
  stateFilter: document.getElementById("filter-state"),
  typeFilter: document.getElementById("filter-type"),
  confidenceFilter: document.getElementById("filter-confidence"),
  search: document.getElementById("filter-search"),
  reset: document.getElementById("reset-filters"),
  note: document.getElementById("filter-note"),
  kpiCount: document.getElementById("kpi-count"),
  kpiCountMeta: document.getElementById("kpi-count-meta"),
  kpiDeaths: document.getElementById("kpi-deaths"),
  kpiDeathsMeta: document.getElementById("kpi-deaths-meta"),
  kpiInjured: document.getElementById("kpi-injured"),
  kpiInjuredMeta: document.getElementById("kpi-injured-meta"),
  kpiCrashes: document.getElementById("kpi-crashes"),
  kpiCrashesMeta: document.getElementById("kpi-crashes-meta"),
  kpiRate: document.getElementById("kpi-rate"),
  stateBars: document.getElementById("state-bars"),
  confidenceChips: document.getElementById("confidence-chips"),
  tableHead: document.getElementById("table-head"),
  tableBody: document.getElementById("table-body"),
  tableHint: document.getElementById("table-hint"),
};

const numberFormat = new Intl.NumberFormat("es-MX");
const decimalFormat = new Intl.NumberFormat("es-MX", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const map = L.map("report-map", { zoomControl: true, scrollWheelZoom: true }).setView(
  NATIONAL_VIEW.center,
  NATIONAL_VIEW.zoom,
);

L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · Datos: INEGI ATUS',
}).addTo(map);

const markerLayer = L.layerGroup().addTo(map);
const markerIndex = new Map();

function parseCsv(text) {
  const source = text.replace(/^\uFEFF/, "");
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;

  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];

    if (quoted) {
      if (character === '"') {
        if (source[index + 1] === '"') {
          field += '"';
          index += 1;
        } else {
          quoted = false;
        }
      } else {
        field += character;
      }
      continue;
    }

    if (character === '"') {
      quoted = true;
    } else if (character === ",") {
      row.push(field);
      field = "";
    } else if (character === "\n" || character === "\r") {
      if (character === "\r" && source[index + 1] === "\n") {
        index += 1;
      }
      row.push(field);
      field = "";
      if (row.length > 1 || row[0] !== "") {
        rows.push(row);
      }
      row = [];
    } else {
      field += character;
    }
  }

  if (field !== "" || row.length) {
    row.push(field);
    rows.push(row);
  }

  const [header, ...records] = rows;
  if (!header) {
    return [];
  }

  return records
    .filter((record) => record.length && record.some((value) => value !== ""))
    .map((record) => {
      const item = {};
      header.forEach((key, index) => {
        item[key] = record[index] ?? "";
      });
      return item;
    });
}

function toNumber(value) {
  if (value === null || value === undefined || value === "") {
    return 0;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function normalize(row) {
  const item = { ...row };
  NUMERIC_KEYS.forEach((key) => {
    if (key === "fatal_share" || key === "peak_hour") {
      item[key] = toNumber(row[key]);
    } else {
      item[key] = toNumber(row[key]);
    }
  });
  item.lat = toNumber(row.centroid_lat);
  item.lon = toNumber(row.centroid_lon);
  item.confidence = (row.confidence || "baja").trim().toLowerCase();
  return item;
}

function setStatus(text, status) {
  els.status.textContent = text;
  els.status.dataset.state = status;
}

function formatInteger(value) {
  return numberFormat.format(Math.round(value));
}

function formatShare(value) {
  return `${(value * 100).toLocaleString("es-MX", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })}%`;
}

function sortValue(row, key) {
  if (NUMERIC_KEYS.has(key)) {
    return toNumber(row[key]);
  }
  return String(row[key] ?? "").toLocaleLowerCase("es-MX");
}

function compareRows(left, right) {
  const { sortKey, sortDir } = state;
  const a = sortValue(left, sortKey);
  const b = sortValue(right, sortKey);

  if (typeof a === "number" && typeof b === "number") {
    return (a - b) * sortDir;
  }

  return String(a).localeCompare(String(b), "es-MX") * sortDir;
}

function applyFilters() {
  const { state: stateName, type, confidence, search } = state.filters;
  const needle = search.trim().toLocaleLowerCase("es-MX");

  state.filtered = state.rows.filter((row) => {
    if (stateName !== "all" && row.state_name !== stateName) {
      return false;
    }
    if (type !== "all" && row.dominant_type_label !== type) {
      return false;
    }
    if (confidence !== "all" && row.confidence !== confidence) {
      return false;
    }
    if (needle) {
      const haystack = `${row.place} ${row.municipality_name} ${row.state_name}`.toLocaleLowerCase(
        "es-MX",
      );
      if (!haystack.includes(needle)) {
        return false;
      }
    }
    return true;
  });

  state.filtered.sort(compareRows);

  if (state.selectedId && !state.filtered.some((row) => row.hotspot_id === state.selectedId)) {
    state.selectedId = null;
  }
}

function updateKpis() {
  const rows = state.filtered;
  const deaths = rows.reduce((total, row) => total + toNumber(row.deaths), 0);
  const injured = rows.reduce((total, row) => total + toNumber(row.injured), 0);
  const crashes = rows.reduce((total, row) => total + toNumber(row.crashes), 0);
  const fatalShare = rows.length
    ? rows.reduce((total, row) => total + toNumber(row.fatal_share), 0) / rows.length
    : 0;

  els.kpiCount.textContent = formatInteger(rows.length);
  els.kpiCountMeta.textContent = `de ${formatInteger(state.rows.length)} en el archivo`;
  els.kpiDeaths.textContent = formatInteger(deaths);
  els.kpiDeathsMeta.textContent = rows.length
    ? `${decimalFormat.format(deaths / rows.length)} por punto`
    : "sin selección";
  els.kpiInjured.textContent = formatInteger(injured);
  els.kpiInjuredMeta.textContent = rows.length
    ? `${decimalFormat.format(injured / rows.length)} por punto`
    : "sin selección";
  els.kpiCrashes.textContent = formatInteger(crashes);
  els.kpiCrashesMeta.textContent = rows.length
    ? `${decimalFormat.format(crashes / rows.length)} por punto`
    : "sin selección";
  els.kpiRate.textContent = formatShare(fatalShare);
}

function renderBars() {
  const totals = new Map();
  state.filtered.forEach((row) => {
    const name = row.state_name || "Sin estado";
    totals.set(name, (totals.get(name) || 0) + toNumber(row.deaths));
  });

  const entries = [...totals.entries()].sort((a, b) => b[1] - a[1]);
  const max = entries.length ? entries[0][1] : 0;

  els.stateBars.replaceChildren();

  if (!entries.length) {
    const empty = document.createElement("p");
    empty.className = "pbi-empty";
    empty.textContent = "Sin datos para los filtros actuales.";
    els.stateBars.append(empty);
    return;
  }

  entries.forEach(([name, deaths]) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "pbi-bar-row";
    row.setAttribute("aria-pressed", String(state.filters.state === name));
    row.title = `${name}: ${formatInteger(deaths)} muertes`;

    const label = document.createElement("span");
    label.className = "pbi-bar-label";
    label.textContent = name;

    const track = document.createElement("span");
    track.className = "pbi-bar-track";
    const fill = document.createElement("span");
    fill.className = "pbi-bar-fill";
    fill.style.width = `${max ? (deaths / max) * 100 : 0}%`;
    track.append(fill);

    const value = document.createElement("span");
    value.className = "pbi-bar-value";
    value.textContent = formatInteger(deaths);

    row.append(label, track, value);
    row.addEventListener("click", () => {
      state.filters.state = state.filters.state === name ? "all" : name;
      els.stateFilter.value = state.filters.state;
      refresh();
    });

    els.stateBars.append(row);
  });
}

function renderConfidence() {
  const totals = { alta: 0, media: 0, baja: 0 };
  state.filtered.forEach((row) => {
    if (totals[row.confidence] !== undefined) {
      totals[row.confidence] += 1;
    }
  });

  els.confidenceChips.replaceChildren();

  ["alta", "media", "baja"].forEach((level) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "pbi-chip";
    chip.setAttribute("aria-pressed", String(state.filters.confidence === level));

    const dot = document.createElement("i");
    dot.className = "pbi-dot";
    dot.style.background = CONFIDENCE_COLORS[level];

    const count = document.createElement("strong");
    count.textContent = formatInteger(totals[level]);

    const caption = document.createElement("span");
    caption.textContent = level;

    chip.append(dot, count, caption);
    chip.addEventListener("click", () => {
      state.filters.confidence = state.filters.confidence === level ? "all" : level;
      els.confidenceFilter.value = state.filters.confidence;
      refresh();
    });

    els.confidenceChips.append(chip);
  });
}

function renderMap() {
  markerLayer.clearLayers();
  markerIndex.clear();

  const rows = state.filtered;
  if (!rows.length) {
    map.setView(NATIONAL_VIEW.center, NATIONAL_VIEW.zoom);
    return;
  }

  rows.forEach((row) => {
    const radius = 5 + Math.min(16, Math.sqrt(toNumber(row.deaths)) * 4);
    const marker = L.circleMarker([row.lat, row.lon], {
      radius,
      color: "#ffffff",
      weight: 1.5,
      fillColor: CONFIDENCE_COLORS[row.confidence] || CONFIDENCE_COLORS.baja,
      fillOpacity: 0.85,
    });

    marker.bindTooltip(
      `<strong>#${row.rank} · ${row.place}</strong><br>${row.municipality_name}, ${row.state_name}<br>` +
        `${formatInteger(toNumber(row.deaths))} muertes · ${formatInteger(
          toNumber(row.injured),
        )} heridos · ${formatInteger(toNumber(row.crashes))} choques`,
      { direction: "top", sticky: true },
    );

    marker.on("click", () => selectRow(row.hotspot_id, { pan: false }));
    marker.addTo(markerLayer);
    markerIndex.set(row.hotspot_id, marker);
  });

  const bounds = L.latLngBounds(rows.map((row) => [row.lat, row.lon]));
  map.fitBounds(bounds, { padding: [24, 24], maxZoom: 11 });

  if (state.selectedId && markerIndex.has(state.selectedId)) {
    const selected = state.filtered.find((row) => row.hotspot_id === state.selectedId);
    if (selected) {
      map.setView([selected.lat, selected.lon], 14);
    }
  }
}

function renderTableHead() {
  els.tableHead.replaceChildren();

  COLUMNS.forEach((column) => {
    const cell = document.createElement("th");
    cell.textContent = column.label;
    if (column.numeric) {
      cell.classList.add("num");
    }
    if (!column.sortable) {
      cell.style.cursor = "default";
    }

    if (column.key === state.sortKey) {
      cell.dataset.sorted = "true";
      const caret = document.createElement("span");
      caret.className = "pbi-sort";
      caret.textContent = state.sortDir > 0 ? "▲" : "▼";
      cell.append(caret);
    }

    if (column.sortable) {
      cell.addEventListener("click", () => {
        if (state.sortKey === column.key) {
          state.sortDir *= -1;
        } else {
          state.sortKey = column.key;
          state.sortDir = column.numeric && column.key !== "rank" ? -1 : 1;
        }
        applyFilters();
        renderTableHead();
        renderTableBody();
      });
    }

    els.tableHead.append(cell);
  });
}

function cellFor(row, column) {
  const cell = document.createElement("td");
  if (column.numeric) {
    cell.classList.add("num");
  }

  switch (column.key) {
    case "rank": {
      cell.classList.add("pbi-rank");
      cell.textContent = row.rank;
      break;
    }
    case "place": {
      cell.classList.add("pbi-place");
      cell.textContent = row.place;
      cell.title = row.place;
      break;
    }
    case "municipality_name":
    case "state_name": {
      cell.classList.add("pbi-muted-cell");
      cell.textContent = row[column.key] || "—";
      break;
    }
    case "dominant_type_label": {
      cell.classList.add("pbi-muted-cell");
      cell.textContent = row.dominant_type_label || "—";
      cell.title = row.dominant_type_label || "";
      break;
    }
    case "deaths": {
      const maxDeaths = Math.max(...state.rows.map((item) => toNumber(item.deaths)), 1);
      const bar = document.createElement("span");
      bar.className = "pbi-databar";
      const fill = document.createElement("span");
      fill.className = "pbi-databar-fill";
      fill.style.width = `${(toNumber(row.deaths) / maxDeaths) * 100}%`;
      const text = document.createElement("span");
      text.textContent = formatInteger(toNumber(row.deaths));
      bar.append(fill, text);
      cell.append(bar);
      break;
    }
    case "fatal_share": {
      cell.textContent = formatShare(toNumber(row.fatal_share));
      break;
    }
    case "peak_hour": {
      const hour = toNumber(row.peak_hour);
      cell.textContent = row.peak_hour === "" ? "—" : `${String(hour).padStart(2, "0")}:00`;
      break;
    }
    case "confidence": {
      const pill = document.createElement("span");
      pill.className = `pbi-pill pbi-pill--${row.confidence}`;
      pill.textContent = row.confidence;
      pill.style.background = `${CONFIDENCE_COLORS[row.confidence] || "#edebe9"}22`;
      pill.style.color = CONFIDENCE_INK[row.confidence] || "#3b3a39";
      cell.append(pill);
      break;
    }
    case "primary_action": {
      cell.classList.add("pbi-action");
      cell.textContent = row.primary_action || "—";
      cell.title = [row.primary_action, row.secondary_action].filter(Boolean).join(" · ");
      break;
    }
    default: {
      cell.textContent = row[column.key] ?? "—";
      cell.classList.add("num");
    }
  }

  return cell;
}

function renderTableBody() {
  els.tableBody.replaceChildren();

  if (!state.filtered.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = COLUMNS.length;
    td.className = "pbi-empty";
    td.textContent = "Ningún punto crítico coincide con los filtros.";
    tr.append(td);
    els.tableBody.append(tr);
    return;
  }

  state.filtered.forEach((row) => {
    const tr = document.createElement("tr");
    tr.dataset.hotspot = row.hotspot_id;
    if (row.hotspot_id === state.selectedId) {
      tr.classList.add("is-selected");
    }

    COLUMNS.forEach((column) => tr.append(cellFor(row, column)));

    tr.addEventListener("click", () => selectRow(row.hotspot_id, { pan: true }));
    els.tableBody.append(tr);
  });
}

function updateTableHint() {
  const sortedLabel =
    COLUMNS.find((column) => column.key === state.sortKey)?.label ?? "rango";
  els.tableHint.textContent = `${formatInteger(state.filtered.length)} resultados · ordenado por ${
    sortedLabel.toLowerCase()
  } ${state.sortDir > 0 ? "ascendente" : "descendente"} · clic en una fila para ubicarla`;
}

function updateFilterNote() {
  const active = [];
  if (state.filters.state !== "all") {
    active.push(`estado: ${state.filters.state}`);
  }
  if (state.filters.type !== "all") {
    active.push(`tipo: ${state.filters.type}`);
  }
  if (state.filters.confidence !== "all") {
    active.push(`confianza: ${state.filters.confidence}`);
  }
  if (state.filters.search.trim()) {
    active.push(`búsqueda: “${state.filters.search.trim()}”`);
  }

  const total = state.rows.length;
  els.note.textContent = active.length
    ? `Mostrando ${formatInteger(state.filtered.length)} de ${formatInteger(
        total,
      )} puntos · ${active.join(" · ")}`
    : `Mostrando los ${formatInteger(total)} puntos críticos de priorities_top100.csv`;
}

function selectRow(hotspotId, { pan }) {
  state.selectedId = hotspotId;

  document.querySelectorAll(".pbi-table tbody tr.is-selected").forEach((element) => {
    element.classList.remove("is-selected");
  });
  const row = document.querySelector(`.pbi-table tbody tr[data-hotspot="${hotspotId}"]`);
  row?.classList.add("is-selected");

  const marker = markerIndex.get(hotspotId);
  if (marker) {
    if (pan) {
      const position = marker.getLatLng();
      map.setView(position, Math.max(map.getZoom(), 14));
    }
    marker.openTooltip();
  }
}

function refresh() {
  applyFilters();
  updateKpis();
  renderBars();
  renderConfidence();
  renderMap();
  renderTableBody();
  updateTableHint();
  updateFilterNote();
}

function populateSelect(select, values, allLabel) {
  select.replaceChildren();
  const all = document.createElement("option");
  all.value = "all";
  all.textContent = allLabel;
  select.append(all);

  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.append(option);
  });
}

function attachEvents() {
  els.stateFilter.addEventListener("change", () => {
    state.filters.state = els.stateFilter.value;
    refresh();
  });
  els.typeFilter.addEventListener("change", () => {
    state.filters.type = els.typeFilter.value;
    refresh();
  });
  els.confidenceFilter.addEventListener("change", () => {
    state.filters.confidence = els.confidenceFilter.value;
    refresh();
  });
  els.search.addEventListener("input", () => {
    state.filters.search = els.search.value;
    refresh();
  });
  els.reset.addEventListener("click", () => {
    state.filters = { state: "all", type: "all", confidence: "all", search: "" };
    els.stateFilter.value = "all";
    els.typeFilter.value = "all";
    els.confidenceFilter.value = "all";
    els.search.value = "";
    refresh();
  });
}

async function load() {
  try {
    const response = await fetch("/api/priorities/export");
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      throw new Error(detail?.detail ?? `La API respondió ${response.status}`);
    }

    const text = await response.text();
    state.rows = parseCsv(text)
      .map(normalize)
      .filter((row) => row.hotspot_id);

    if (!state.rows.length) {
      throw new Error("El archivo priorities_top100.csv está vacío.");
    }

    const states = [...new Set(state.rows.map((row) => row.state_name).filter(Boolean))].sort(
      (a, b) => a.localeCompare(b, "es-MX"),
    );
    const types = [
      ...new Set(state.rows.map((row) => row.dominant_type_label).filter(Boolean)),
    ].sort((a, b) => a.localeCompare(b, "es-MX"));

    populateSelect(els.stateFilter, states, "Todos");
    populateSelect(els.typeFilter, types, "Todos");

    els.subtitle.textContent = `Top ${state.rows.length} de puntos críticos por muertes · priorities_top100.csv`;

    renderTableHead();
    attachEvents();
    refresh();

    setStatus(`${state.rows.length} registros`, "ready");
  } catch (error) {
    setStatus("Error", "error");
    els.note.textContent = `No se pudo leer priorities_top100.csv: ${error.message}`;

    els.tableBody.replaceChildren();
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = COLUMNS.length;
    td.className = "pbi-empty pbi-empty--error";
    td.textContent = error.message;
    tr.append(td);
    els.tableBody.append(tr);
  }
}

renderTableHead();
load();
