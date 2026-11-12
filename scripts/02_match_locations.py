#!/usr/bin/env python3
import csv
import re
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUTPUT = ROOT / "data" / "curated" / "atus.duckdb"

BATCH_SIZE = 50_000
YEAR_PATTERN = re.compile(r"(\d{4})\.csv$", re.IGNORECASE)

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
]

GEO_COLUMNS = [
    ("year", "INTEGER"),
    ("cvegeo", "VARCHAR"),
    ("month", "INTEGER"),
    ("day", "INTEGER"),
    ("hour", "INTEGER"),
    ("minute", "INTEGER"),
    ("type_code", "INTEGER"),
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
    ("latitude", "DOUBLE"),
    ("longitude", "DOUBLE"),
    ("street_1", "VARCHAR"),
    ("street_2", "VARCHAR"),
    ("highway", "VARCHAR"),
]

INT_COLUMNS = [name for name, kind in GEO_COLUMNS if kind == "INTEGER"]
FLOAT_COLUMNS = [name for name, kind in GEO_COLUMNS if kind == "DOUBLE"]
TEXT_COLUMNS = [name for name, kind in GEO_COLUMNS if kind == "VARCHAR"]

KEY_COLUMNS = [
    "year",
    "cvegeo",
    "type_code",
    "k_month",
    "k_day",
    "k_hour",
    "k_minute",
    "cond_muerto",
    "cond_herido",
    "pasa_muerto",
    "pasa_herido",
    "peat_muerto",
    "peat_herido",
    "cicl_muerto",
    "cicl_herido",
    "otro_muerto",
    "otro_herido",
]

JOIN_CLAUSE = " AND ".join(f"a.{name} = g.{name}" for name in KEY_COLUMNS)


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


def _float(value):
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def repair(value):
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    raw = text.encode("latin-1", "replace")
    for encoding in ("utf-8", "cp1252"):
        try:
            return raw.decode(encoding).strip() or None
        except UnicodeDecodeError:
            continue
    return raw.decode("cp1252", errors="replace").strip() or None


def transform(row):
    latitude = _float(row["LATITUD"])
    longitude = _float(row["LONGITUD"])
    if latitude is None or longitude is None:
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None

    return (
        _int(row["ANIO"]),
        f"{int(row['EDO']):02d}{int(row['MPIO']):03d}",
        _int(row["MES"]),
        _int(row["DIA"], (0, 32)),
        _int(row["HORA"], (99,)),
        _int(row["MINUTOS"], (99,)),
        _int(row["TIPACCID"]),
        *[_int(row[name]) for name in VICTIM_SOURCES],
        latitude,
        longitude,
        repair(row["CALLE1"]),
        repair(row["CALLE2"]),
        repair(row["CARRETERA"]),
    )


def frame(rows):
    columns = [name for name, _ in GEO_COLUMNS]
    df = pd.DataFrame(rows, columns=columns)
    for name in INT_COLUMNS:
        df[name] = df[name].astype("Int64")
    for name in FLOAT_COLUMNS:
        df[name] = df[name].astype("Float64")
    for name in TEXT_COLUMNS:
        df[name] = df[name].astype("string")
    return df


def create_geo_table(con):
    schema = ", ".join(f"{name} {kind}" for name, kind in GEO_COLUMNS)
    con.execute("DROP TABLE IF EXISTS _geo_raw")
    con.execute(f"CREATE TEMP TABLE _geo_raw ({schema})")


def key_select(source, extra_column=""):
    prefix = f"{extra_column}, " if extra_column else ""
    partition = (
        "year, cvegeo, type_code, COALESCE(month, -1), COALESCE(day, -1), "
        "COALESCE(hour, -1), COALESCE(minute, -1), "
        "cond_muerto, cond_herido, pasa_muerto, pasa_herido, peat_muerto, "
        "peat_herido, cicl_muerto, cicl_herido, otro_muerto, otro_herido"
    )
    return f"""
        SELECT
            {prefix}
            year,
            cvegeo,
            type_code,
            COALESCE(month, -1) AS k_month,
            COALESCE(day, -1) AS k_day,
            COALESCE(hour, -1) AS k_hour,
            COALESCE(minute, -1) AS k_minute,
            cond_muerto, cond_herido, pasa_muerto, pasa_herido,
            peat_muerto, peat_herido, cicl_muerto, cicl_herido,
            otro_muerto, otro_herido,
            row_number() OVER (PARTITION BY {partition} ORDER BY {{order}}) AS dup
        FROM {source}
    """


def match(con):
    con.execute(
        """
        UPDATE accidents SET
            latitude = NULL,
            longitude = NULL,
            street_1 = NULL,
            street_2 = NULL,
            highway = NULL,
            has_location = FALSE
        """
    )

    con.execute("DROP TABLE IF EXISTS _acc_keys")
    con.execute(
        "CREATE TEMP TABLE _acc_keys AS "
        + key_select("accidents", "accident_id").format(order="accident_id")
        + " WHERE year BETWEEN 2019 AND 2024"
    )

    con.execute("DROP TABLE IF EXISTS _geo_keys")
    con.execute(
        "CREATE TEMP TABLE _geo_keys AS "
        + key_select("_geo_raw", "rowid AS geo_rowid").format(
            order="latitude, longitude, street_1, street_2"
        )
    )

    con.execute("DROP TABLE IF EXISTS _matches")
    con.execute(
        f"""
        CREATE TEMP TABLE _matches AS
        SELECT
            a.accident_id,
            g.geo_rowid,
            g.year,
            r.latitude,
            r.longitude,
            r.street_1,
            r.street_2,
            r.highway
        FROM _acc_keys a
        JOIN _geo_keys g ON {JOIN_CLAUSE} AND a.dup = g.dup
        JOIN _geo_raw r ON r.rowid = g.geo_rowid
        """
    )

    con.execute(
        """
        UPDATE accidents SET
            latitude = m.latitude,
            longitude = m.longitude,
            street_1 = m.street_1,
            street_2 = m.street_2,
            highway = m.highway,
            has_location = TRUE
        FROM _matches m
        WHERE accidents.accident_id = m.accident_id
        """
    )


def main():
    if not OUTPUT.exists():
        raise SystemExit(f"{OUTPUT} not found. Run scripts/01_normalize_data.py first.")

    con = duckdb.connect(str(OUTPUT))
    tables = {name for (name,) in con.execute("SHOW TABLES").fetchall()}
    if "accidents" not in tables:
        raise SystemExit("Table 'accidents' not found. Run scripts/01_normalize_data.py first.")

    create_geo_table(con)

    files = sorted(RAW.glob("atus_*_shp/**/*.csv"))
    if not files:
        raise SystemExit(f"No shapefile CSVs found under {RAW}")

    batch = []
    skipped = 0
    for path in files:
        file_rows = 0
        with path.open(encoding="latin-1", newline="") as fh:
            for row in csv.DictReader(fh):
                record = transform(row)
                if record is None:
                    skipped += 1
                    continue
                batch.append(record)
                file_rows += 1
                if len(batch) >= BATCH_SIZE:
                    con.append("_geo_raw", frame(batch))
                    batch.clear()
        print(f"  {YEAR_PATTERN.search(path.name).group(1)} {path.parent.parent.name}: {file_rows:,} rows")

    if batch:
        con.append("_geo_raw", frame(batch))

    match(con)

    total = con.execute("SELECT count(*) FROM _geo_raw").fetchone()[0]
    matched = con.execute("SELECT count(*) FROM _matches").fetchone()[0]

    print()
    for year, geo_rows, year_matched in con.execute(
        """
        SELECT g.year, count(*) AS geo_rows, count(m.geo_rowid) AS matched
        FROM _geo_raw g
        LEFT JOIN _matches m ON g.rowid = m.geo_rowid
        GROUP BY g.year
        ORDER BY g.year
        """
    ).fetchall():
        rate = 100 * year_matched / geo_rows if geo_rows else 0
        print(f"  {year}: {year_matched:,} / {geo_rows:,} matched ({rate:.2f}%)")

    con.execute("CHECKPOINT")
    con.close()

    rate = 100 * matched / total if total else 0
    print()
    print(f"shapefile rows: {total:,}")
    print(f"skipped invalid coordinates: {skipped:,}")
    print(f"matched: {matched:,} ({rate:.2f}%)")
    print(f"unmatched: {total - matched:,}")


if __name__ == "__main__":
    main()
