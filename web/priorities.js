const NATIONAL_VIEW = { center: [23.6, -102.5], zoom: 5 };

const map = L.map("priority-map", { zoomControl: true }).setView(
  NATIONAL_VIEW.center,
  NATIONAL_VIEW.zoom,
);

L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · Datos: INEGI ATUS',
}).addTo(map);

const statusEl = document.getElementById("status");
const subtitleEl = document.getElementById("priority-subtitle");
const summaryEl = document.getElementById("priority-summary");
const listEl = document.getElementById("priority-list");
const stateEl = document.getElementById("state-filter");
const deathsEl = document.getElementById("deaths-filter");
const severityEl = document.getElementById("severity-list");

const TYPE_COLORS = {
  1: "#2563eb",
  2: "#dc2626",
  3: "#6b7280",
  4: "#7c3aed",
  5: "#ea580c",
  6: "#0891b2",
  7: "#92400e",
  8: "#b91c1c",
  9: "#0f172a",
  10: "#f59e0b",
  11: "#16a34a",
  12: "#475569",
};

let allRows = [];
let markers = [];

function number(value) {
  return Number(value || 0).toLocaleString("es-MX");
}

function setStatus(text, state) {
  statusEl.textContent = text;
  statusEl.dataset.state = state;
}

function color(row) {
  return TYPE_COLORS[row.dominant_type] || "#6b7280";
}

function radius(row) {
  return 7 + Math.min(18, Math.sqrt(Number(row.deaths) || 0) * 4);
}

function popup(row) {
  const box = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = row.place;
  const meta = document.createElement("div");
  meta.className = "popup-meta";
  meta.textContent = `${row.municipality_name || ""} · ${number(row.deaths)} muertes · ${number(
    row.injured,
  )} heridos · ${number(row.crashes)} choques`;
  const action = document.createElement("div");
  action.className = "popup-meta";
  action.textContent = row.primary_action;
  box.append(title, meta, action);
  return box;
}

function clearMarkers() {
  markers.forEach((marker) => marker.remove());
  markers = [];
}

function renderList(rows) {
  listEl.replaceChildren();
  rows.forEach((row) => {
    const card = document.createElement("article");
    card.className = "priority-card";
    card.dataset.hotspot = row.hotspot_id;

    const head = document.createElement("div");
    head.className = "priority-card-head";
    const rank = document.createElement("span");
    rank.className = "priority-rank";
    rank.textContent = `#${row.rank}`;
    const badge = document.createElement("span");
    badge.className = `badge badge--${row.confidence}`;
    badge.textContent = row.confidence;
    head.append(rank, badge);

    const place = document.createElement("p");
    place.className = "priority-place";
    place.textContent = row.place;

    const meta = document.createElement("p");
    meta.className = "priority-meta";
    meta.textContent = [row.municipality_name, row.state_name].filter(Boolean).join(", ");

    const metrics = document.createElement("p");
    metrics.className = "priority-metrics";
    metrics.textContent = `${number(row.deaths)} muertes · ${number(
      row.injured,
    )} heridos · ${number(row.crashes)} choques`;

    const action = document.createElement("p");
    action.className = "priority-action";
    action.textContent = row.primary_action;

    card.append(head, place, meta, metrics, action);
    card.addEventListener("click", () => focus(row, card));
    listEl.append(card);
  });
}

function focus(row, card) {
  document.querySelectorAll(".priority-card.is-active").forEach((element) => {
    element.classList.remove("is-active");
  });
  card?.classList.add("is-active");

  const position = [row.centroid_lat, row.centroid_lon];
  map.setView(position, 15);
  markers.forEach((marker) => {
    if (marker.options.hotspotId === row.hotspot_id) {
      marker.openPopup();
    }
  });
}

function render() {
  const state = stateEl.value;
  const minDeaths = Number(deathsEl.value) || 0;

  const rows = allRows.filter(
    (row) =>
      (state === "all" || row.state_name === state) &&
      (Number(row.deaths) || 0) >= minDeaths,
  );

  clearMarkers();
  rows.forEach((row) => {
    const marker = L.circleMarker([row.centroid_lat, row.centroid_lon], {
      radius: radius(row),
      color: "#1f2937",
      weight: 1,
      fillColor: color(row),
      fillOpacity: 0.75,
    })
      .addTo(map)
      .bindPopup(popup(row));

    marker.options.hotspotId = row.hotspot_id;
    marker.on("click", () => {
      document.querySelectorAll(".priority-card.is-active").forEach((element) => {
        element.classList.remove("is-active");
      });
      document
        .querySelector(`.priority-card[data-hotspot="${row.hotspot_id}"]`)
        ?.classList.add("is-active");
    });
    markers.push(marker);
  });

  if (rows.length) {
    map.fitBounds(
      L.latLngBounds(rows.map((row) => [row.centroid_lat, row.centroid_lon])),
      { padding: [30, 30], maxZoom: 11 },
    );
  }

  const deaths = rows.reduce((total, row) => total + (Number(row.deaths) || 0), 0);
  const injured = rows.reduce((total, row) => total + (Number(row.injured) || 0), 0);

  summaryEl.textContent = `${rows.length} prioridades · ${number(deaths)} muertes · ${number(
    injured,
  )} heridos`;
  subtitleEl.textContent = `${rows.length} ubicaciones priorizadas · ordenadas por muertes`;
  renderList(rows);
}

async function loadSeverity() {
  try {
    const response = await fetch("/api/severity?model=all");
    if (!response.ok) {
      throw new Error(`La API respondió ${response.status}`);
    }
    const data = await response.json();
    severityEl.replaceChildren();
    data.rows.slice(0, 7).forEach((row) => {
      const line = document.createElement("div");
      line.className = "severity-row";
      const label = document.createElement("span");
      label.textContent = row.feature_label;
      const value = document.createElement("span");
      value.className = "severity-value";
      value.textContent = `OR ${Number(row.odds_ratio).toFixed(2)}`;
      line.append(label, value);
      severityEl.append(line);
    });
  } catch (error) {
    severityEl.replaceChildren();
    const message = document.createElement("p");
    message.className = "placeholder error";
    message.textContent = error.message;
    severityEl.append(message);
  }
}

async function load() {
  try {
    const response = await fetch("/api/priorities");
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      throw new Error(detail?.detail ?? `La API respondió ${response.status}`);
    }
    const data = await response.json();
    allRows = data.rows;

    const all = document.createElement("option");
    all.value = "all";
    all.textContent = "Todos";
    stateEl.replaceChildren(all);
    data.states.forEach((state) => {
      const option = document.createElement("option");
      option.value = state;
      option.textContent = state;
      stateEl.append(option);
    });

    render();
    loadSeverity();
    setStatus("Listo", "ready");
  } catch (error) {
    setStatus("Error", "error");
    subtitleEl.textContent = `No se pudieron cargar las prioridades: ${error.message}`;
    listEl.replaceChildren();
    const message = document.createElement("p");
    message.className = "placeholder error";
    message.textContent = error.message;
    listEl.append(message);
  }
}

stateEl.addEventListener("change", render);
deathsEl.addEventListener("change", render);

load();
