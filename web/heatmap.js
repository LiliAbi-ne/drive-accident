const NATIONAL_VIEW = { center: [23.6, -102.5], zoom: 5 };

const map = L.map("heat-map", { zoomControl: true, preferCanvas: true }).setView(
  NATIONAL_VIEW.center,
  NATIONAL_VIEW.zoom,
);

L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · Datos: INEGI ATUS',
}).addTo(map);

const statusEl = document.getElementById("status");
const titleEl = document.getElementById("heat-title");
const subtitleEl = document.getElementById("heat-subtitle");
const backEl = document.getElementById("heat-back");
const yearFilterEl = document.getElementById("year-filter");

const GRADIENT = {
  0.2: "#93c5fd",
  0.4: "#60a5fa",
  0.6: "#fbbf24",
  0.8: "#f97316",
  1: "#b91c1c",
};

let currentYear = null;
let availableYears = [];
let heatLayer = null;

function setStatus(text, state) {
  statusEl.textContent = text;
  statusEl.dataset.state = state;
}

function currentStateParam() {
  const match = window.location.pathname.match(/^\/heatmap\/([^/]+)\/?$/);
  return match ? decodeURIComponent(match[1]) : null;
}

function currentYearParam() {
  const value = new URLSearchParams(window.location.search).get("year");
  return value && /^\d{4}$/.test(value) ? Number(value) : null;
}

function yearLabel() {
  if (currentYear) return String(currentYear);
  if (!availableYears.length) return "todos los años";
  return `${availableYears[0]}–${availableYears[availableYears.length - 1]}`;
}

function number(value) {
  return Number(value).toLocaleString("es-MX");
}

function fillYearFilter() {
  const all = document.createElement("option");
  all.value = "all";
  all.textContent = "Todos los años";
  yearFilterEl.replaceChildren(all);

  availableYears.forEach((year) => {
    const option = document.createElement("option");
    option.value = String(year);
    option.textContent = String(year);
    yearFilterEl.append(option);
  });

  yearFilterEl.value = currentYear ? String(currentYear) : "all";
}

async function loadYears() {
  const response = await fetch("/api/years");
  if (!response.ok) {
    throw new Error(`La API respondió ${response.status}`);
  }
  const data = await response.json();
  availableYears = data.years.map((entry) => entry.year);
}

async function load() {
  const stateParam = currentStateParam();
  const params = new URLSearchParams();
  if (stateParam) params.set("state", stateParam);
  if (currentYear) params.set("year", String(currentYear));
  const query = params.toString();
  const url = `/api/heatmap${query ? `?${query}` : ""}`;

  try {
    const response = await fetch(url);
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      throw new Error(detail?.detail ?? `La API respondió ${response.status}`);
    }
    const data = await response.json();

    if (data.state) {
      titleEl.textContent = `ATUS · Mapa de calor · ${data.state.name}`;
      document.title = `ATUS · ${data.state.name}`;
      backEl.hidden = false;
    } else {
      titleEl.textContent = "ATUS · Mapa de calor del país";
      document.title = "ATUS · Mapa de calor";
    }

    if (!data.total) {
      if (heatLayer) {
        heatLayer.remove();
        heatLayer = null;
      }
      subtitleEl.textContent = `Sin coordenadas para ${yearLabel()}. La base georreferenciada cubre 2019–2024.`;
      setStatus("Sin coordenadas", "ready");
      return;
    }

    subtitleEl.textContent = `${number(data.total)} accidentes · ${yearLabel()} · ${number(
      data.cells.length,
    )} celdas de ${data.precision} decimales`;

    const bounds = data.bounds ? L.latLngBounds([data.bounds[0], data.bounds[1]]) : null;

    if (bounds) {
      map.fitBounds(bounds, {
        padding: [30, 30],
        maxZoom: data.state ? 11 : 6,
      });
    }

    const top = Math.log1p(Math.max(1, data.max));
    const points = data.cells.map(([lat, lng, count]) => [
      lat,
      lng,
      Math.log1p(count) / top,
    ]);

    if (heatLayer) heatLayer.remove();
    heatLayer = L.heatLayer(points, {
      radius: data.state ? 24 : 16,
      blur: data.state ? 26 : 20,
      max: 1,
      minOpacity: 0.25,
      gradient: GRADIENT,
    }).addTo(map);

    setStatus("Listo", "ready");
  } catch (error) {
    setStatus("Error", "error");
    subtitleEl.textContent = `No se pudo cargar el mapa de calor: ${error.message}`;
  }
}

yearFilterEl.addEventListener("change", () => {
  const value = yearFilterEl.value;
  const url = new URL(window.location.href);
  if (value === "all") {
    url.searchParams.delete("year");
    currentYear = null;
  } else {
    url.searchParams.set("year", value);
    currentYear = Number(value);
  }
  window.history.replaceState(null, "", url);
  load();
});

async function init() {
  currentYear = currentYearParam();
  try {
    await loadYears();
    fillYearFilter();
  } catch (error) {
    setStatus("Error", "error");
  }
  load();
}

init();
