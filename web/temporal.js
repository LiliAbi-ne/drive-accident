const statusEl = document.getElementById("status");
const subtitleEl = document.getElementById("temporal-subtitle");
const dayBarsEl = document.getElementById("day-bars");
const hourBarsEl = document.getElementById("hour-bars");
const matrixEl = document.getElementById("matrix");

const DAY_NAME = {
  1: "Lunes",
  2: "Martes",
  3: "Miércoles",
  4: "Jueves",
  5: "Viernes",
  6: "Sábado",
  7: "Domingo",
};

function number(value) {
  return Number(value).toLocaleString("es-MX");
}

function setStatus(text, state) {
  statusEl.textContent = text;
  statusEl.dataset.state = state;
}

function renderBars(container, items, labelOf, max) {
  container.replaceChildren();
  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "bar-row";
    row.title = `${labelOf(item)} · ${number(item.accidents)} accidentes · ${number(
      item.deaths,
    )} muertos · ${number(item.injured)} heridos`;

    const label = document.createElement("span");
    label.className = "bar-label";
    label.textContent = labelOf(item);

    const track = document.createElement("span");
    track.className = "bar-track";
    const fill = document.createElement("span");
    fill.className = "bar-fill";
    fill.style.width = `${Math.max(1.5, (item.accidents / max) * 100)}%`;
    track.append(fill);

    const value = document.createElement("span");
    value.className = "bar-value";
    value.textContent = number(item.accidents);

    row.append(label, track, value);
    container.append(row);
  });
}

function matrixLabel(text, className) {
  const label = document.createElement("span");
  label.className = className;
  label.textContent = text;
  return label;
}

function renderMatrix(cells, maxCell) {
  matrixEl.replaceChildren();
  const top = Math.log1p(Math.max(1, maxCell));
  const byKey = new Map(cells.map((cell) => [`${cell.day}-${cell.hour}`, cell]));

  const head = document.createElement("div");
  head.className = "matrix-row matrix-row--head";
  head.append(matrixLabel("", "matrix-label"));
  for (let hour = 0; hour < 24; hour += 1) {
    head.append(matrixLabel(String(hour).padStart(2, "0"), "matrix-label matrix-label--hour"));
  }
  matrixEl.append(head);

  for (let day = 1; day <= 7; day += 1) {
    const row = document.createElement("div");
    row.className = "matrix-row";
    row.append(matrixLabel(DAY_NAME[day], "matrix-label"));

    for (let hour = 0; hour < 24; hour += 1) {
      const cell = byKey.get(`${day}-${hour}`);
      const count = cell ? cell.accidents : 0;
      const box = document.createElement("span");
      box.className = "matrix-cell";
      if (count) {
        const intensity = Math.log1p(count) / top;
        box.style.background = `rgba(185, 28, 28, ${(0.08 + 0.92 * intensity).toFixed(3)})`;
      }
      box.title = `${DAY_NAME[day]} ${String(hour).padStart(2, "0")}:00 · ${number(
        count,
      )} accidentes`;
      row.append(box);
    }
    matrixEl.append(row);
  }
}

async function load() {
  try {
    const response = await fetch("/api/temporal");
    if (!response.ok) {
      throw new Error(`La API respondió ${response.status}`);
    }
    const data = await response.json();

    const maxDay = Math.max(...data.days.map((day) => day.accidents));
    const maxHour = Math.max(...data.hours.map((hour) => hour.accidents));

    renderBars(dayBarsEl, data.days, (day) => day.name, maxDay);
    renderBars(hourBarsEl, data.hours, (hour) => `${String(hour.hour).padStart(2, "0")}:00`, maxHour);
    renderMatrix(data.cells, data.peak_cell.accidents);

    subtitleEl.textContent = `${number(data.totals.accidents)} accidentes · pico ${data.peak_day.name} a las ${String(
      data.peak_cell.hour,
    ).padStart(2, "0")}:00 (${number(data.peak_cell.accidents)}) · hora más crítica ${String(
      data.peak_hour.hour,
    ).padStart(2, "0")}:00`;

    setStatus("Listo", "ready");
  } catch (error) {
    setStatus("Error", "error");
    subtitleEl.textContent = `No se pudo cargar el análisis temporal: ${error.message}`;
  }
}

load();
