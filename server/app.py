import csv
import unicodedata
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = (
    ROOT.parent
    / "data"
    / "ATUS_2020"
    / "conjunto_de_datos"
    / "BASE MUNICIPAL_ACCIDENTES DE TRANSITO GEORREFERENCIADOS_2020.csv"
)
CSV_ENCODING = "latin-1"
WEB_DIR = ROOT / "web"

ACCIDENT_TYPE = {
    1: "Colisión con vehículo automotor",
    2: "Colisión con peatón (atropellamiento)",
    3: "Colisión con animal",
    4: "Colisión con objeto fijo",
    5: "Volcadura",
    6: "Caída de pasajero",
    7: "Salida del camino",
    8: "Incendio",
    9: "Colisión con ferrocarril",
    10: "Colisión con motocicleta",
    11: "Colisión con ciclista",
    12: "Otro",
}
SEVERITY = {1: "Fatal", 2: "No fatal", 3: "Sólo daños"}
DAY_OF_WEEK = {
    1: "Lunes",
    2: "Martes",
    3: "Miércoles",
    4: "Jueves",
    5: "Viernes",
    6: "Sábado",
    7: "Domingo",
}
STATE_NAME = {
    1: "Aguascalientes",
    2: "Baja California",
    3: "Baja California Sur",
    4: "Campeche",
    5: "Coahuila",
    6: "Colima",
    7: "Chiapas",
    8: "Chihuahua",
    9: "Ciudad de México",
    10: "Durango",
    11: "Guanajuato",
    12: "Guerrero",
    13: "Hidalgo",
    14: "Jalisco",
    15: "Estado de México",
    16: "Michoacán",
    17: "Morelos",
    18: "Nayarit",
    19: "Nuevo León",
    20: "Oaxaca",
    21: "Puebla",
    22: "Querétaro",
    23: "Quintana Roo",
    24: "San Luis Potosí",
    25: "Sinaloa",
    26: "Sonora",
    27: "Tabasco",
    28: "Tamaulipas",
    29: "Tlaxcala",
    30: "Veracruz",
    31: "Yucatán",
    32: "Zacatecas",
}

app = FastAPI(title="ATUS Crash Explorer", version="0.1.0")


def _slug(name):
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return "-".join(ascii_name.lower().split())


STATE_SLUG = {_slug(name): code for code, name in STATE_NAME.items()}


def _resolve_state(value):
    if value is None or value == "":
        return None
    if value.isdigit():
        return int(value) if int(value) in STATE_NAME else None
    return STATE_SLUG.get(_slug(value))


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _occurred_at(row):
    year, month = _int(row["ANIO"]), _int(row["MES"])
    day, hour, minute = _int(row["DIA"]), _int(row["HORA"]), _int(row["MINUTOS"])
    if None in (year, month, day, hour, minute):
        return None
    if not (1 <= day <= 31 and 0 <= hour <= 23 and 0 <= minute <= 59 and 1 <= month <= 12):
        return None
    return datetime(year, month, day, hour, minute).isoformat(timespec="minutes")


def _build_accident(row):
    type_code = _int(row["TIPACCID"])
    severity_code = _int(row["CLASE"])
    return {
        "id": row["ID"],
        "record_key": f"{row['ANIO']}-{row['EDO']}-{row['MPIO']}-{row['ID']}",
        "occurred_at": _occurred_at(row),
        "day_of_week": DAY_OF_WEEK.get(_int(row["DIASEMANA"])),
        "state_code": _int(row["EDO"]),
        "municipality_code": _int(row["MPIO"]),
        "street_1": row["CALLE1"].strip() or None,
        "street_2": row["CALLE2"].strip() or None,
        "highway": row["CARRETERA"].strip() or None,
        "accident_type_code": type_code,
        "accident_type": ACCIDENT_TYPE.get(type_code),
        "severity_code": severity_code,
        "severity": SEVERITY.get(severity_code),
        "deaths": _int(row["TOTMUERTOS"]),
        "injured": _int(row["TOTHERIDOS"]),
        "latitude": _float(row["LATITUD"]),
        "longitude": _float(row["LONGITUD"]),
    }


@lru_cache(maxsize=1)
def first_accident():
    with CSV_PATH.open(encoding=CSV_ENCODING, newline="") as fh:
        reader = csv.DictReader(fh)
        row = next(reader, None)
    if row is None:
        raise HTTPException(status_code=404, detail="Dataset is empty")
    return _build_accident(row)


@lru_cache(maxsize=1)
def row_count():
    with CSV_PATH.open(encoding=CSV_ENCODING, newline="") as fh:
        return sum(1 for _ in fh) - 1


@lru_cache(maxsize=1)
def summary_rows():
    buckets = {}
    with CSV_PATH.open(encoding=CSV_ENCODING, newline="") as fh:
        for row in csv.DictReader(fh):
            year, state = _int(row["ANIO"]), _int(row["EDO"])
            if year is None or state is None:
                continue
            bucket = buckets.setdefault((year, state), {"accidents": 0, "deaths": 0, "injured": 0})
            bucket["accidents"] += 1
            bucket["deaths"] += _int(row["TOTMUERTOS"]) or 0
            bucket["injured"] += _int(row["TOTHERIDOS"]) or 0
    return [
        {
            "year": year,
            "state_code": state,
            "state_name": STATE_NAME.get(state, f"Estado {state}"),
            "state_slug": _slug(STATE_NAME.get(state, f"Estado {state}")),
            "accidents": values["accidents"],
            "deaths": values["deaths"],
            "injured": values["injured"],
        }
        for (year, state), values in buckets.items()
    ]


@app.get("/api/health")
def health():
    return {"status": "ok", "source": CSV_PATH.name, "rows": row_count()}


@lru_cache(maxsize=8)
def heat_cells(precision):
    factor = 10**precision
    cells = {}
    with CSV_PATH.open(encoding=CSV_ENCODING, newline="") as fh:
        for row in csv.DictReader(fh):
            lat, lng = _float(row["LATITUD"]), _float(row["LONGITUD"])
            state = _int(row["EDO"])
            if lat is None or lng is None or state is None:
                continue
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                continue
            key = (state, round(lat * factor) / factor, round(lng * factor) / factor)
            cells[key] = cells.get(key, 0) + 1
    return cells


@app.get("/api/heatmap")
def heatmap(state: str | None = None, precision: int = 2):
    precision = max(0, min(precision, 4))
    state_code = _resolve_state(state)
    if state is not None and state_code is None:
        raise HTTPException(status_code=404, detail=f"Estado desconocido: {state}")

    cells = heat_cells(precision)
    if state_code is not None:
        cells = {key: count for key, count in cells.items() if key[0] == state_code}

    points = [[lat, lng, count] for (_state, lat, lng), count in cells.items()]
    latitudes = [point[0] for point in points]
    longitudes = [point[1] for point in points]
    return {
        "precision": precision,
        "state": None
        if state_code is None
        else {
            "code": state_code,
            "name": STATE_NAME[state_code],
            "slug": _slug(STATE_NAME[state_code]),
        },
        "cells": points,
        "total": sum(point[2] for point in points),
        "max": max((point[2] for point in points), default=0),
        "bounds": [[min(latitudes), min(longitudes)], [max(latitudes), max(longitudes)]]
        if points
        else None,
    }



@app.get("/api/summary")
def summary(year: int | None = None, order: str = "desc"):
    rows = summary_rows()
    if year is not None:
        rows = [row for row in rows if row["year"] == year]
    rows = sorted(
        rows,
        key=lambda row: (row["accidents"], row["deaths"], row["injured"]),
        reverse=order != "asc",
    )
    return {
        "years": sorted({row["year"] for row in summary_rows()}),
        "totals": {
            "accidents": sum(row["accidents"] for row in rows),
            "deaths": sum(row["deaths"] for row in rows),
            "injured": sum(row["injured"] for row in rows),
        },
        "rows": rows,
    }


@lru_cache(maxsize=1)
def temporal_buckets():
    by_day = {day: {"accidents": 0, "deaths": 0, "injured": 0} for day in DAY_OF_WEEK}
    by_hour = {hour: {"accidents": 0, "deaths": 0, "injured": 0} for hour in range(24)}
    by_cell = {}
    with CSV_PATH.open(encoding=CSV_ENCODING, newline="") as fh:
        for row in csv.DictReader(fh):
            day, hour = _int(row["DIASEMANA"]), _int(row["HORA"])
            if day not in by_day or hour not in by_hour:
                continue
            deaths = _int(row["TOTMUERTOS"]) or 0
            injured = _int(row["TOTHERIDOS"]) or 0
            for bucket in (by_day[day], by_hour[hour]):
                bucket["accidents"] += 1
                bucket["deaths"] += deaths
                bucket["injured"] += injured
            cell = by_cell.setdefault((day, hour), {"accidents": 0, "deaths": 0, "injured": 0})
            cell["accidents"] += 1
            cell["deaths"] += deaths
            cell["injured"] += injured
    return by_day, by_hour, by_cell


@app.get("/api/temporal")
def temporal():
    by_day, by_hour, by_cell = temporal_buckets()
    days = [{"day": day, "name": DAY_OF_WEEK[day], **values} for day, values in sorted(by_day.items())]
    hours = [{"hour": hour, **values} for hour, values in sorted(by_hour.items())]
    cells = [
        {"day": day, "hour": hour, **values}
        for (day, hour), values in sorted(by_cell.items())
    ]
    return {
        "days": days,
        "hours": hours,
        "cells": cells,
        "totals": {
            "accidents": sum(day["accidents"] for day in days),
            "deaths": sum(day["deaths"] for day in days),
            "injured": sum(day["injured"] for day in days),
        },
        "peak_day": max(days, key=lambda day: day["accidents"]),
        "peak_hour": max(hours, key=lambda hour: hour["accidents"]),
        "peak_cell": max(cells, key=lambda cell: cell["accidents"]),
    }



@app.get("/api/accidents/first")
def get_first_accident():
    accident = first_accident()
    if accident["latitude"] is None or accident["longitude"] is None:
        raise HTTPException(status_code=422, detail="First record has no usable coordinates")
    return accident


@app.get("/heatmap", include_in_schema=False)
def national_heatmap_page():
    return FileResponse(WEB_DIR / "heatmap.html")


@app.get("/heatmap/{state}", include_in_schema=False)
def state_heatmap_page(state: str):
    if _resolve_state(state) is None:
        raise HTTPException(status_code=404, detail=f"Estado desconocido: {state}")
    return FileResponse(WEB_DIR / "heatmap.html")


@app.get("/temporal", include_in_schema=False)
def temporal_page():
    return FileResponse(WEB_DIR / "temporal.html")


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
