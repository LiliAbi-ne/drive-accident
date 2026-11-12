import unicodedata
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import duckdb
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "curated" / "atus.duckdb"
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

app = FastAPI(title="ATUS Crash Explorer", version="0.2.0")


def _slug(name):
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return "-".join(ascii_name.lower().split())


STATE_SLUG = {_slug(name): code for code, name in STATE_NAME.items()}


@contextmanager
def database():
    if not DB_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail="Base curada no encontrada. Ejecuta scripts/01, 02 y 03.",
        )
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        yield connection
    finally:
        connection.close()


def _resolve_state(value):
    if value is None or value == "":
        return None
    if value.isdigit():
        return int(value) if int(value) in STATE_NAME else None
    return STATE_SLUG.get(_slug(value))


def available_years():
    with database() as con:
        rows = con.execute("SELECT DISTINCT year FROM accidents ORDER BY year").fetchall()
    return [row[0] for row in rows]


def _occurred_at(year, month, day, hour, minute):
    if None in (year, month, day, hour, minute):
        return None
    try:
        return datetime(year, month, day, hour, minute).isoformat(timespec="minutes")
    except ValueError:
        return None


FIRST_ACCIDENT_SQL = """
    SELECT
        accident_id, year, month, day, hour, minute, day_of_week,
        cve_ent, cve_mun, type_code, severity_code,
        street_1, street_2, highway,
        deaths_total, injured_total, latitude, longitude
    FROM accidents
    WHERE (? IS NULL OR year = ?)
    ORDER BY
        has_location DESC,
        coalesce(month, 99), coalesce(day, 99),
        coalesce(hour, 99), coalesce(minute, 99),
        accident_id
    LIMIT 1
"""


def _build_accident(row):
    (
        accident_id,
        year,
        month,
        day,
        hour,
        minute,
        day_of_week,
        cve_ent,
        cve_mun,
        type_code,
        severity_code,
        street_1,
        street_2,
        highway,
        deaths,
        injured,
        latitude,
        longitude,
    ) = row

    return {
        "id": accident_id,
        "year": year,
        "record_key": accident_id,
        "occurred_at": _occurred_at(year, month, day, hour, minute),
        "day_of_week": DAY_OF_WEEK.get(day_of_week),
        "state_code": cve_ent,
        "municipality_code": cve_mun,
        "street_1": street_1,
        "street_2": street_2,
        "highway": highway,
        "accident_type_code": type_code,
        "accident_type": ACCIDENT_TYPE.get(type_code),
        "severity_code": severity_code,
        "severity": SEVERITY.get(severity_code),
        "deaths": deaths,
        "injured": injured,
        "latitude": latitude,
        "longitude": longitude,
    }


@app.get("/api/health")
def health():
    with database() as con:
        total = con.execute("SELECT count(*) FROM accidents").fetchone()[0]
        counts = dict(
            con.execute("SELECT year, count(*) FROM accidents GROUP BY year ORDER BY year").fetchall()
        )
    return {
        "status": "ok",
        "source": DB_PATH.name,
        "sources": 1,
        "years": list(counts),
        "rows": total,
        "rows_by_year": counts,
    }


@app.get("/api/years")
def years():
    with database() as con:
        rows = con.execute(
            """
            SELECT year, count(*) AS rows,
                   sum(CASE WHEN has_location THEN 1 ELSE 0 END) AS located
            FROM accidents
            GROUP BY year
            ORDER BY year
            """
        ).fetchall()
    return {
        "years": [
            {"year": year, "rows": row_count, "located": located}
            for year, row_count, located in rows
        ],
        "total": sum(row_count for _, row_count, _ in rows),
    }


@app.get("/api/heatmap")
def heatmap(state: str | None = None, precision: int = 2, year: int | None = None):
    precision = max(0, min(precision, 4))
    state_code = _resolve_state(state)
    if state is not None and state_code is None:
        raise HTTPException(status_code=404, detail=f"Estado desconocido: {state}")
    if year is not None and year not in available_years():
        raise HTTPException(status_code=404, detail=f"Año no disponible: {year}")

    with database() as con:
        rows = con.execute(
            f"""
            SELECT round(latitude, {precision}) AS lat,
                   round(longitude, {precision}) AS lon,
                   count(*) AS accidents
            FROM accidents
            WHERE has_location
              AND (? IS NULL OR year = ?)
              AND (? IS NULL OR cve_ent = ?)
            GROUP BY 1, 2
            """,
            [year, year, state_code, state_code],
        ).fetchall()

    points = [[lat, lon, count] for lat, lon, count in rows]
    latitudes = [point[0] for point in points]
    longitudes = [point[1] for point in points]

    return {
        "precision": precision,
        "year": year,
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
    direction = "ASC" if order == "asc" else "DESC"
    with database() as con:
        rows = con.execute(
            f"""
            SELECT year, cve_ent, state_name, accidents, deaths, injured
            FROM mart_year_state
            WHERE (? IS NULL OR year = ?)
            ORDER BY accidents {direction}, deaths {direction}, injured {direction}
            """,
            [year, year],
        ).fetchall()
        years = [row[0] for row in con.execute(
            "SELECT DISTINCT year FROM mart_year_state ORDER BY year"
        ).fetchall()]

    result = [
        {
            "year": row_year,
            "state_code": cve_ent,
            "state_name": state_name,
            "state_slug": _slug(state_name),
            "accidents": accidents,
            "deaths": deaths,
            "injured": injured,
        }
        for row_year, cve_ent, state_name, accidents, deaths, injured in rows
    ]

    return {
        "years": years,
        "totals": {
            "accidents": sum(row["accidents"] for row in result),
            "deaths": sum(row["deaths"] for row in result),
            "injured": sum(row["injured"] for row in result),
        },
        "rows": result,
    }


@app.get("/api/temporal")
def temporal(year: int | None = None):
    if year is not None and year not in available_years():
        raise HTTPException(status_code=404, detail=f"Año no disponible: {year}")

    with database() as con:
        rows = con.execute(
            """
            SELECT day_of_week, hour, accidents, deaths, injured
            FROM mart_temporal
            WHERE (? IS NULL OR year = ?)
            """,
            [year, year],
        ).fetchall()

    by_day = {day: {"accidents": 0, "deaths": 0, "injured": 0} for day in DAY_OF_WEEK}
    by_hour = {hour: {"accidents": 0, "deaths": 0, "injured": 0} for hour in range(24)}
    by_cell = {}

    for day, hour, accidents, deaths, injured in rows:
        for bucket in (by_day.get(day), by_hour.get(hour)):
            if bucket is None:
                continue
            bucket["accidents"] += accidents
            bucket["deaths"] += deaths
            bucket["injured"] += injured
        cell = by_cell.setdefault((day, hour), {"accidents": 0, "deaths": 0, "injured": 0})
        cell["accidents"] += accidents
        cell["deaths"] += deaths
        cell["injured"] += injured

    days = [{"day": day, "name": DAY_OF_WEEK[day], **values} for day, values in sorted(by_day.items())]
    hours = [{"hour": hour, **values} for hour, values in sorted(by_hour.items())]
    cells = [{"day": day, "hour": hour, **values} for (day, hour), values in sorted(by_cell.items())]
    totals = {
        "accidents": sum(day["accidents"] for day in days),
        "deaths": sum(day["deaths"] for day in days),
        "injured": sum(day["injured"] for day in days),
    }

    return {
        "year": year,
        "days": days,
        "hours": hours,
        "cells": cells,
        "totals": totals,
        "peak_day": max(days, key=lambda day: day["accidents"]) if totals["accidents"] else None,
        "peak_hour": max(hours, key=lambda hour: hour["accidents"]) if totals["accidents"] else None,
        "peak_cell": max(cells, key=lambda cell: cell["accidents"]) if cells else None,
    }


@app.get("/api/accidents/first")
def get_first_accident(year: int | None = None):
    if year is not None and year not in available_years():
        raise HTTPException(status_code=404, detail=f"Año no disponible: {year}")
    with database() as con:
        row = con.execute(FIRST_ACCIDENT_SQL, [year, year]).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Sin registros para el año {year}")
    return _build_accident(row)


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
