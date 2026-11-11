const NATIONAL_VIEW = { center: [23.6, -102.5], zoom: 5 };

const map = L.map("heat-map", { zoomControl: true, preferCanvas: true }).setView(
  NATIONAL_VIEW.center,
  NATIONAL_VIEW.zoom,
);

L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · Datos: INEGI ATUS 2020',
}).addTo(map);

const statusEl = document.getElementById("status");
const titleEl = document.getElementById("heat-title");
const subtitleEl = document.getElementById("heat-subtitle");
const backEl = document.getElementById("heat-back");

const GRADIENT = {
  0.2: "#93c5fd",
  0.4: "#60a5fa",
  0.6: "#fbbf24",
  0.8: "#f97316",
  1: "#b91c1c",
};

function setStatus(text, state) {
  statusEl.textContent = text;
  statusEl.dataset.state = state;
}

function currentStateParam() {
  const match = window.location.pathname.match(/^\/heatmap\/([^/]+)\/?$/);
  return match ? decodeURIComponent(match[1]) : null;
}

function number(value) {
  return Number(value).toLocaleString("es-MX");
}

async function load() {
  const stateParam = currentStateParam();
  const url = stateParam
    ? `/api/heatmap?state=${encodeURIComponent(stateParam)}`
    : "/api/heatmap";

  try {
    const response = await fetch(url);
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      throw new Error(detail?.detail ?? `La API respondió ${response.status}`);
    }
    const data = await response.json();

    if (data.state) {
      titleEl.textContent = `ATUS 2020 · Mapa de calor · ${data.state.name}`;
      document.title = `ATUS 2020 · ${data.state.name}`;
      backEl.hidden = false;
    }

    subtitleEl.textContent = `${number(data.total)} accidentes · ${number(
      data.cells.length,
    )} celdas de ${data.precision} decimales`;

    const bounds = data.bounds
      ? L.latLngBounds([data.bounds[0], data.bounds[1]])
      : null;

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

    L.heatLayer(points, {
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

load();
