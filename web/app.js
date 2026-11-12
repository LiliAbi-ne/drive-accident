const DEFAULT_VIEW = [21.88, -102.29];

const map = L.map("map", { zoomControl: true }).setView(DEFAULT_VIEW, 12);

L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · Datos: INEGI ATUS 2020',
}).addTo(map);

const statusEl = document.getElementById("status");
const subtitleEl = document.getElementById("page-subtitle");
const detailViewEl = document.getElementById("view-detail");
const detailContentEl = document.getElementById("detail-content");
const detailYearEl = document.getElementById("detail-year");
const summaryViewEl = document.getElementById("view-summary");
const summaryTableEl = document.getElementById("summary-table");
const yearFilterEl = document.getElementById("year-filter");
const tabEls = document.querySelectorAll(".tab");

const SUMMARY_COLUMNS = [
  { key: "state_name", label: "Estado", numeric: false },
  { key: "year", label: "Año", numeric: true },
  { key: "accidents", label: "Accidentes", numeric: true },
  { key: "deaths", label: "Muertos", numeric: true },
  { key: "injured", label: "Heridos", numeric: true },
];

const summaryState = {
  rows: [],
  year: "all",
  sortKey: "accidents",
  sortDir: -1,
};

function setStatus(text, state) {
  statusEl.textContent = text;
  statusEl.dataset.state = state;
}

function field(label, value) {
  const wrap = document.createElement("div");
  wrap.className = "field";
  const name = document.createElement("span");
  name.className = "label";
  name.textContent = label;
  const val = document.createElement("span");
  val.className = "value";
  val.textContent = value === null || value === undefined || value === "" ? "—" : String(value);
  wrap.append(name, val);
  return wrap;
}

function section(title) {
  const el = document.createElement("h2");
  el.className = "section-title";
  el.textContent = title;
  return el;
}

function metric(label, value) {
  const box = document.createElement("div");
  box.className = "metric";
  const num = document.createElement("span");
  num.className = "metric-value";
  num.textContent = String(value);
  const name = document.createElement("span");
  name.className = "metric-label";
  name.textContent = label;
  box.append(num, name);
  return box;
}

function formatDateTime(accident) {
  if (!accident.occurred_at) return null;
  const [date, time] = accident.occurred_at.split("T");
  return `${date} · ${time}`;
}

function describeAddress(accident) {
  const parts = [accident.street_1, accident.street_2].filter(Boolean);
  if (parts.length) return parts.join(" × ");
  return accident.highway || null;
}

function buildPopup(accident) {
  const box = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = describeAddress(accident) || "Accidente";
  const meta = document.createElement("div");
  meta.className = "popup-meta";
  meta.textContent = [formatDateTime(accident), accident.accident_type]
    .filter(Boolean)
    .join(" · ");
  box.append(title, meta);
  return box;
}

function renderPanel(accident) {
  detailContentEl.replaceChildren();

  const header = document.createElement("div");
  header.className = "panel-header";
  const title = document.createElement("h2");
  title.textContent = describeAddress(accident) || "Accidente sin dirección";
  const badge = document.createElement("span");
  badge.className = `badge badge--${accident.severity_code ?? 0}`;
  badge.textContent = accident.severity || "Sin clasificar";
  header.append(title, badge);

  const severityBlock = document.createElement("div");
  severityBlock.className = "metrics";
  severityBlock.append(
    metric("Muertos", accident.deaths ?? "—"),
    metric("Heridos", accident.injured ?? "—"),
  );

  const details = document.createElement("div");
  details.className = "fields";
  details.append(
    field("Año", accident.year),
    field("Fecha y hora", formatDateTime(accident) ?? "No especificado"),
    field("Día", accident.day_of_week ?? "No especificado"),
    field("Calle 1", accident.street_1),
    field("Calle 2", accident.street_2),
    field("Carretera", accident.highway),
    field("Tipo de accidente", accident.accident_type),
    field("Clave de tipo", accident.accident_type_code),
    field("Estado (clave)", accident.state_code),
    field("Municipio (clave)", accident.municipality_code),
    field("Latitud", accident.latitude?.toFixed(5)),
    field("Longitud", accident.longitude?.toFixed(5)),
    field("ID de registro", accident.record_key),
  );

  const note = document.createElement("p");
  note.className = "note";
  note.textContent =
    accident.latitude === null || accident.longitude === null
      ? "Este registro no tiene coordenadas. La base georreferenciada cubre solo 2019–2024."
      : "Coordenada geocodificada por INEGI a partir de la dirección (no es GPS). El círculo marca la incertidumbre aproximada.";

  detailContentEl.append(header, severityBlock, section("Detalle del registro"), details, note);
}

function showError(message) {
  setStatus("Error", "error");
  detailContentEl.replaceChildren();
  const box = document.createElement("p");
  box.className = "placeholder error";
  box.textContent = message;
  detailContentEl.append(box);
}

function setView(view, updateHash = true) {
  tabEls.forEach((tab) => {
    const active = tab.dataset.view === view;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll("[data-nav]").forEach((link) => {
    link.classList.toggle("is-active", link.dataset.nav === view);
  });
  detailViewEl.hidden = view !== "detail";
  summaryViewEl.hidden = view !== "summary";
  subtitleEl.textContent =
    view === "summary" ? "Resumen por estado y año" : lastDetailSubtitle;
  if (updateHash) {
    const url =
      view === "summary"
        ? "#resumen"
        : `${window.location.pathname}${window.location.search}`;
    window.history.replaceState(null, "", url);
  }
}

function numericText(value) {
  return Number(value).toLocaleString("es-MX");
}

function sortCaret(direction) {
  const caret = document.createElement("span");
  caret.className = "sort-caret";
  caret.textContent = direction === -1 ? " ▼" : " ▲";
  return caret;
}

function tableCell(value, numeric) {
  const cell = document.createElement("td");
  if (numeric) cell.className = "num";
  cell.textContent = numeric ? numericText(value) : String(value);
  return cell;
}

function stateCell(row) {
  const cell = document.createElement("td");
  const link = document.createElement("a");
  link.className = "table-link";
  link.href = `/heatmap/${row.state_slug}`;
  link.textContent = row.state_name;
  cell.append(link);
  return cell;
}

function summaryTotals(rows) {
  return rows.reduce(
    (acc, row) => ({
      accidents: acc.accidents + row.accidents,
      deaths: acc.deaths + row.deaths,
      injured: acc.injured + row.injured,
    }),
    { accidents: 0, deaths: 0, injured: 0 },
  );
}

function sortedSummaryRows(rows) {
  const { sortKey, sortDir } = summaryState;
  return [...rows].sort((left, right) => {
    if (typeof left[sortKey] === "string") {
      return left[sortKey].localeCompare(right[sortKey], "es") * sortDir;
    }
    return (left[sortKey] - right[sortKey]) * sortDir;
  });
}

function renderSummary() {
  const filtered =
    summaryState.year === "all"
      ? summaryState.rows
      : summaryState.rows.filter((row) => row.year === Number(summaryState.year));
  const rows = sortedSummaryRows(filtered);

  summaryTableEl.replaceChildren();

  const table = document.createElement("table");
  table.className = "summary-table";

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  SUMMARY_COLUMNS.forEach((column) => {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = column.label;
    if (column.numeric) th.classList.add("num");
    if (summaryState.sortKey === column.key) {
      th.dataset.sorted = summaryState.sortDir === -1 ? "desc" : "asc";
      th.append(sortCaret(summaryState.sortDir));
    }
    th.addEventListener("click", () => {
      if (summaryState.sortKey === column.key) {
        summaryState.sortDir *= -1;
      } else {
        summaryState.sortKey = column.key;
        summaryState.sortDir = column.numeric ? -1 : 1;
      }
      renderSummary();
    });
    headRow.append(th);
  });
  thead.append(headRow);

  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.append(
      stateCell(row),
      tableCell(row.year, true),
      tableCell(row.accidents, true),
      tableCell(row.deaths, true),
      tableCell(row.injured, true),
    );
    tbody.append(tr);
  });

  const totals = summaryTotals(filtered);
  const tfoot = document.createElement("tfoot");
  const totalsRow = document.createElement("tr");
  totalsRow.append(
    tableCell("Total", false),
    tableCell("", true),
    tableCell(totals.accidents, true),
    tableCell(totals.deaths, true),
    tableCell(totals.injured, true),
  );
  tfoot.append(totalsRow);

  table.append(thead, tbody, tfoot);
  summaryTableEl.append(table);

  if (!rows.length) {
    const empty = document.createElement("p");
    empty.className = "placeholder";
    empty.textContent = "Sin registros para el filtro seleccionado.";
    summaryTableEl.append(empty);
  }
}

function fillYearFilter(years) {
  const all = document.createElement("option");
  all.value = "all";
  all.textContent = "Todos";
  yearFilterEl.replaceChildren(all);
  years.forEach((year) => {
    const option = document.createElement("option");
    option.value = String(year);
    option.textContent = String(year);
    yearFilterEl.append(option);
  });
  yearFilterEl.value = summaryState.year;
}

async function loadSummary() {
  try {
    const response = await fetch("/api/summary");
    if (!response.ok) {
      throw new Error(`La API respondió ${response.status}`);
    }
    const data = await response.json();
    summaryState.rows = data.rows;
    fillYearFilter(data.years);
    renderSummary();
    setStatus("Listo", "ready");
  } catch (error) {
    summaryTableEl.replaceChildren();
    const box = document.createElement("p");
    box.className = "placeholder error";
    box.textContent = `No se pudo cargar el resumen: ${error.message}`;
    summaryTableEl.append(box);
  }
}

let currentMarker = null;
let currentCircle = null;
let lastDetailSubtitle = "Primer registro de la base municipal georreferenciada";

async function loadFirstAccident(year) {
  try {
    const query = year ? `?year=${encodeURIComponent(year)}` : "";
    const response = await fetch(`/api/accidents/first${query}`);
    if (!response.ok) {
      throw new Error(`La API respondió ${response.status}`);
    }
    const accident = await response.json();
    const hasLocation =
      Number.isFinite(accident.latitude) && Number.isFinite(accident.longitude);

    if (currentMarker) {
      currentMarker.remove();
      currentMarker = null;
    }
    if (currentCircle) {
      currentCircle.remove();
      currentCircle = null;
    }

    if (hasLocation) {
      const latlng = [accident.latitude, accident.longitude];

      currentCircle = L.circle(latlng, {
        radius: 50,
        color: "#ef4444",
        weight: 1,
        fillColor: "#ef4444",
        fillOpacity: 0.12,
      }).addTo(map);

      currentMarker = L.circleMarker(latlng, {
        radius: 9,
        color: "#7f1d1d",
        weight: 2,
        fillColor: "#ef4444",
        fillOpacity: 0.95,
      })
        .addTo(map)
        .bindPopup(buildPopup(accident));

      map.setView(latlng, 17);
      currentMarker.openPopup();
    } else {
      map.setView([23.6, -102.5], 5);
    }

    renderPanel(accident);

    lastDetailSubtitle = `Primer registro de ${accident.year} · Estado ${accident.state_code}, municipio ${accident.municipality_code}`;
    if (summaryViewEl.hidden) {
      subtitleEl.textContent = lastDetailSubtitle;
    }
    setStatus("Registro cargado", "ready");
  } catch (error) {
    showError(`No se pudo cargar el registro: ${error.message}`);
  }
}

async function loadYears() {
  const response = await fetch("/api/years");
  if (!response.ok) {
    throw new Error(`La API respondió ${response.status}`);
  }
  const data = await response.json();
  return data.years;
}

function fillDetailYearFilter(years, selected) {
  detailYearEl.replaceChildren();
  years.forEach((year) => {
    const option = document.createElement("option");
    option.value = String(year);
    option.textContent = String(year);
    detailYearEl.append(option);
  });
  if (selected !== undefined) {
    detailYearEl.value = String(selected);
  }
}

tabEls.forEach((tab) => tab.addEventListener("click", () => setView(tab.dataset.view)));
document.querySelectorAll("[data-nav]").forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    setView(link.dataset.nav);
  });
});
yearFilterEl.addEventListener("change", () => {
  summaryState.year = yearFilterEl.value;
  renderSummary();
});
detailYearEl.addEventListener("change", () => {
  loadFirstAccident(Number(detailYearEl.value));
});

async function init() {
  loadSummary();
  setView(window.location.hash === "#resumen" ? "summary" : "detail", false);
  try {
    const entries = await loadYears();
    const years = entries.map((entry) => entry.year);
    const locatedYears = entries
      .filter((entry) => entry.located > 0)
      .map((entry) => entry.year);
    const latest = locatedYears.length
      ? Math.max(...locatedYears)
      : years.length
        ? Math.max(...years)
        : null;
    fillDetailYearFilter(years, latest);
    if (latest !== null) {
      await loadFirstAccident(latest);
    }
  } catch (error) {
    showError(`No se pudo cargar la lista de años: ${error.message}`);
  }
}

init();
