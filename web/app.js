const DEFAULT_VIEW = [21.88, -102.29];

const map = L.map("map", { zoomControl: true }).setView(DEFAULT_VIEW, 12);

L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · Datos: INEGI ATUS 2020',
}).addTo(map);

const statusEl = document.getElementById("status");
const panelEl = document.getElementById("panel");

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
  panelEl.replaceChildren();

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
    "Coordenada geocodificada por INEGI a partir de la dirección (no es GPS). El círculo marca la incertidumbre aproximada.";

  panelEl.append(header, severityBlock, section("Detalle del registro"), details, note);
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

function showError(message) {
  setStatus("Error", "error");
  panelEl.replaceChildren();
  const box = document.createElement("p");
  box.className = "placeholder error";
  box.textContent = message;
  panelEl.append(box);
}

async function load() {
  try {
    const response = await fetch("/api/accidents/first");
    if (!response.ok) {
      throw new Error(`La API respondió ${response.status}`);
    }
    const accident = await response.json();
    const latlng = [accident.latitude, accident.longitude];

    L.circle(latlng, {
      radius: 50,
      color: "#ef4444",
      weight: 1,
      fillColor: "#ef4444",
      fillOpacity: 0.12,
    }).addTo(map);

    const marker = L.circleMarker(latlng, {
      radius: 9,
      color: "#7f1d1d",
      weight: 2,
      fillColor: "#ef4444",
      fillOpacity: 0.95,
    })
      .addTo(map)
      .bindPopup(buildPopup(accident));

    map.setView(latlng, 17);
    marker.openPopup();
    renderPanel(accident);
    setStatus("Registro cargado", "ready");
  } catch (error) {
    showError(`No se pudo cargar el registro: ${error.message}`);
  }
}

load();
