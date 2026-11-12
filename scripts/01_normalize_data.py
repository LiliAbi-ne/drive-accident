#!/usr/bin/env python3
import csv
import hashlib
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
ANNUAL_DIR = RAW / "conjunto_de_datos_atus_anual_csv" / "conjunto_de_datos"
CATALOG_DIR = RAW / "conjunto_de_datos_atus_anual_csv" / "catalogos"
OUTPUT = ROOT / "data" / "curated" / "atus.duckdb"

BATCH_SIZE = 50_000

ACCIDENT_TYPE = {
    "Colisión con vehículo automotor": 1,
    "Colisión con peatón (atropellamiento)": 2,
    "Colisión con animal": 3,
    "Colisión con objeto fijo": 4,
    "Volcadura": 5,
    "Caída de pasajero": 6,
    "Salida del camino": 7,
    "Incendio": 8,
    "Colisión con ferrocarril": 9,
    "Colisión con motocicleta": 10,
    "Colisión con ciclista": 11,
    "Otro": 12,
}
SEVERITY = {"Fatal": 1, "No fatal": 2, "Sólo daños": 3}
URBAN = {
    "Accidente en intersección": 1,
    "Accidente en no intersección": 2,
    "Sin accidente en esta zona": 0,
}
SUBURBAN = {
    "Accidente en camino rural": 1,
    "Accidente en carretera estatal": 2,
    "Accidentes en otro camino": 3,
    "Sin accidente en esta zona": 0,
}
CAUSE = {
    "Conductor": 1,
    "Peatón o pasajero": 2,
    "Falla del vehículo": 3,
    "Mala condición del camino": 4,
    "Otra": 5,
    "Certificado cero": 0,
}
ROAD_SURFACE = {"Pavimentada": 1, "No Pavimentada": 2, "Certificado cero": 0}
SEX = {"Se fugó": 1, "Hombre": 2, "Mujer": 3, "Certificado cero": 0}
ALCOHOL = {"Sí": 4, "No": 5, "Se ignora": 6, "Certificado cero": 0}
SEATBELT = {"Sí": 7, "No": 8, "Se ignora": 9, "Certificado cero": 0}
DAY_OF_WEEK = {
    "Lunes": 1,
    "Martes": 2,
    "Miércoles": 3,
    "Jueves": 4,
    "Viernes": 5,
    "Sábado": 6,
    "Domingo": 7,
}

VEHICLE_SOURCES = [
    "AUTOMOVIL",
    "CAMPASAJ",
    "MICROBUS",
    "PASCAMION",
    "OMNIBUS",
    "TRANVIA",
    "CAMIONETA",
    "CAMION",
    "TRACTOR",
    "FERROCARRI",
    "MOTOCICLET",
    "BICICLETA",
    "OTROVEHIC",
]
VICTIM_SOURCES = [
    "CONDMUERTO",
    "CONDHERIDO",
    "PASAMUERTO",
    "PASAHERIDO",
    "PEATMUERTO",
    "PEATHERIDO",
    "CICLMUERTO",
    "CICLHERIDO",
    "OTROMUERTO",
    "OTROHERIDO",
    "NEMUERTO",
    "NEHERIDO",
]

VALUE_COLUMNS = [
    ("year", "INTEGER"),
    ("month", "INTEGER"),
    ("day", "INTEGER"),
    ("hour", "INTEGER"),
    ("minute", "INTEGER"),
    ("day_of_week", "INTEGER"),
    ("cvegeo", "VARCHAR"),
    ("cve_ent", "INTEGER"),
    ("cve_mun", "INTEGER"),
    ("type_code", "INTEGER"),
    ("severity_code", "INTEGER"),
    ("urban_code", "INTEGER"),
    ("suburban_code", "INTEGER"),
    ("cause_code", "INTEGER"),
    ("road_code", "INTEGER"),
    ("sex_code", "INTEGER"),
    ("alcohol_code", "INTEGER"),
    ("seatbelt_code", "INTEGER"),
    ("driver_age", "INTEGER"),
    ("automovil", "INTEGER"),
    ("campasaj", "INTEGER"),
    ("microbus", "INTEGER"),
    ("pascamion", "INTEGER"),
    ("omnibus", "INTEGER"),
    ("tranvia", "INTEGER"),
    ("camioneta", "INTEGER"),
    ("camion", "INTEGER"),
    ("tractor", "INTEGER"),
    ("ferrocarril", "INTEGER"),
    ("motocicleta", "INTEGER"),
    ("bicicleta", "INTEGER"),
    ("otrovehiculo", "INTEGER"),
    ("cond_muerto", "INTEGER"),
    ("cond_herido", "INTEGER"),
    ("pasa_muerto", "INTEGER"),
    ("pasa_herido", "INTEGER"),
    ("peat_muerto", "INTEGER"),
    ("peat_herido", "INTEGER"),
    ("cicl_muerto", "INTEGER"),
    ("cicl_herido", "INTEGER"),
    ("otro_muerto", "INTEGER"),
    ("otro_herido", "INTEGER"),
    ("ne_muerto", "INTEGER"),
    ("ne_herido", "INTEGER"),
    ("deaths_total", "INTEGER"),
    ("injured_total", "INTEGER"),
    ("estatus", "VARCHAR"),
]

INT_COLUMNS = [name for name, kind in VALUE_COLUMNS if kind == "INTEGER"]
TEXT_COLUMNS = [name for name, kind in VALUE_COLUMNS if kind == "VARCHAR"]


def _lookup(mapping):
    return {label.strip().casefold(): code for label, code in mapping.items()}


TYPE_CODES = _lookup(ACCIDENT_TYPE)
SEVERITY_CODES = _lookup(SEVERITY)
URBAN_CODES = _lookup(URBAN)
SUBURBAN_CODES = _lookup(SUBURBAN)
CAUSE_CODES = _lookup(CAUSE)
ROAD_CODES = _lookup(ROAD_SURFACE)
SEX_CODES = _lookup(SEX)
ALCOHOL_CODES = _lookup(ALCOHOL)
SEATBELT_CODES = _lookup(SEATBELT)
DAY_CODES = _lookup(DAY_OF_WEEK)


def _code(mapping, value):
    if not value:
        return None
    return mapping.get(value.strip().casefold())


def _int(value, nulls=()):
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        number = int(value)
    except ValueError:
        return None
    return None if number in nulls else number


def transform(row):
    victims = [_int(row[name]) for name in VICTIM_SOURCES]
    deaths = sum(victims[index] or 0 for index in (0, 2, 4, 6, 8, 10))
    injured = sum(victims[index] or 0 for index in (1, 3, 5, 7, 9, 11))

    values = [
        _int(row["ANIO"]),
        _int(row["MES"]),
        _int(row["ID_DIA"], (0, 32)),
        _int(row["ID_HORA"], (99,)),
        _int(row["ID_MINUTO"], (99,)),
        _code(DAY_CODES, row["DIASEMANA"]),
        (row["CVEGEO"] or "").strip() or None,
        _int(row["CVE_ENT"]),
        _int(row["CVE_MUN"]),
        _code(TYPE_CODES, row["TIPACCID"]),
        _code(SEVERITY_CODES, row["CLASACC"]),
        _code(URBAN_CODES, row["URBANA"]),
        _code(SUBURBAN_CODES, row["SUBURBANA"]),
        _code(CAUSE_CODES, row["CAUSAACCI"]),
        _code(ROAD_CODES, row["CAPAROD"]),
        _code(SEX_CODES, row["SEXO"]),
        _code(ALCOHOL_CODES, row["ALIENTO"]),
        _code(SEATBELT_CODES, row["CINTURON"]),
        _int(row["ID_EDAD"], (0, 99)),
        *[_int(row[name]) for name in VEHICLE_SOURCES],
        *victims,
        deaths,
        injured,
        (row["ESTATUS"] or "").strip() or None,
    ]

    canonical = "|".join("" if value is None else str(value) for value in values)
    digest = hashlib.md5(canonical.encode("utf-8")).hexdigest()
    return (digest, *values)


def frame(rows):
    columns = ["base_hash"] + [name for name, _ in VALUE_COLUMNS]
    df = pd.DataFrame(rows, columns=columns)
    for name in INT_COLUMNS:
        df[name] = df[name].astype("Int64")
    for name in TEXT_COLUMNS + ["base_hash"]:
        df[name] = df[name].astype("string")
    return df


def create_tables(con):
    schema = ", ".join(f"{name} {kind}" for name, kind in VALUE_COLUMNS)
    con.execute(f"CREATE OR REPLACE TABLE accidents_raw (base_hash VARCHAR, {schema})")

    con.execute("CREATE OR REPLACE TABLE dim_entidad (cve_ent INTEGER, name VARCHAR)")
    with (CATALOG_DIR / "tc_entidad.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = [(int(row["CVE_ENT"]), row["NOM_ENTIDAD"].strip()) for row in csv.DictReader(fh)]
    con.executemany("INSERT INTO dim_entidad VALUES (?, ?)", rows)

    con.execute(
        "CREATE OR REPLACE TABLE dim_municipio "
        "(cvegeo VARCHAR, cve_ent INTEGER, cve_mun INTEGER, name VARCHAR)"
    )
    with (CATALOG_DIR / "tc_municipio.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = [
            (
                row["CVEGEO"].strip(),
                int(row["CVE_ENT"]),
                int(row["CVE_MUN"]),
                row["NOM_MUNICIPIO"].strip(),
            )
            for row in csv.DictReader(fh)
        ]
    con.executemany("INSERT INTO dim_municipio VALUES (?, ?, ?, ?)", rows)

    con.execute("CREATE OR REPLACE TABLE dim_codes (domain VARCHAR, code INTEGER, label VARCHAR)")
    codes = []
    for domain, mapping in (
        ("accident_type", ACCIDENT_TYPE),
        ("severity", SEVERITY),
        ("urban", URBAN),
        ("suburban", SUBURBAN),
        ("cause", CAUSE),
        ("road_surface", ROAD_SURFACE),
        ("sex", SEX),
        ("alcohol", ALCOHOL),
        ("seatbelt", SEATBELT),
        ("day_of_week", DAY_OF_WEEK),
    ):
        for label, code in mapping.items():
            codes.append((domain, code, label))
    con.executemany("INSERT INTO dim_codes VALUES (?, ?, ?)", codes)


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT.exists():
        OUTPUT.unlink()

    con = duckdb.connect(str(OUTPUT))
    create_tables(con)

    files = sorted(ANNUAL_DIR.glob("atus_anual_*.csv"))
    if not files:
        raise SystemExit(f"No annual files found in {ANNUAL_DIR}")

    batch = []
    total = 0
    for path in files:
        file_rows = 0
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                batch.append(transform(row))
                file_rows += 1
                if len(batch) >= BATCH_SIZE:
                    con.append("accidents_raw", frame(batch))
                    batch.clear()
        total += file_rows
        print(f"  {path.stem}: {file_rows:,} rows")

    if batch:
        con.append("accidents_raw", frame(batch))

    duplicates = con.execute(
        "SELECT count(*) - count(DISTINCT base_hash) FROM accidents_raw"
    ).fetchone()[0]

    con.execute(
        """
        CREATE OR REPLACE TABLE accidents AS
        SELECT
            md5(base_hash || ':' || row_number() OVER (PARTITION BY base_hash)) AS accident_id,
            * EXCLUDE (base_hash),
            CAST(NULL AS DOUBLE) AS latitude,
            CAST(NULL AS DOUBLE) AS longitude,
            CAST(NULL AS VARCHAR) AS street_1,
            CAST(NULL AS VARCHAR) AS street_2,
            CAST(NULL AS VARCHAR) AS highway,
            FALSE AS has_location
        FROM accidents_raw
        """
    )
    con.execute("DROP TABLE accidents_raw")
    con.execute("CHECKPOINT")

    written = con.execute("SELECT count(*) FROM accidents").fetchone()[0]
    con.close()

    print(f"rows read: {total:,}")
    print(f"rows written: {written:,}")
    print(f"duplicate rows: {duplicates:,}")
    print(f"database: {OUTPUT}")


if __name__ == "__main__":
    main()
