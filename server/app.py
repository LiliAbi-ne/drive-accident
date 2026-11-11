import csv
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = (
    ROOT
    / "data"
    / "atus_2020_shp"
    / "ATUS_2020"
    / "conjunto_de_datos"
    / "BASE MUNICIPAL_ACCIDENTES DE TRANSITO GEORREFERENCIADOS_2020.csv"
)
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

app = FastAPI(title="ATUS Crash Explorer", version="0.1.0")


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
    with CSV_PATH.open(encoding="cp1252", newline="") as fh:
        reader = csv.DictReader(fh)
        row = next(reader, None)
    if row is None:
        raise HTTPException(status_code=404, detail="Dataset is empty")
    return _build_accident(row)


@lru_cache(maxsize=1)
def row_count():
    with CSV_PATH.open(encoding="cp1252", newline="") as fh:
        return sum(1 for _ in fh) - 1


@app.get("/api/health")
def health():
    return {"status": "ok", "source": CSV_PATH.name, "rows": row_count()}


@app.get("/api/accidents/first")
def get_first_accident():
    accident = first_accident()
    if accident["latitude"] is None or accident["longitude"] is None:
        raise HTTPException(status_code=422, detail="First record has no usable coordinates")
    return accident


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
