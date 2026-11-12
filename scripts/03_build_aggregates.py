#!/usr/bin/env python3
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "curated" / "atus.duckdb"


def main():
    if not OUTPUT.exists():
        raise SystemExit(f"{OUTPUT} not found. Run scripts/01_normalize_data.py first.")

    con = duckdb.connect(str(OUTPUT))
    tables = {name for (name,) in con.execute("SHOW TABLES").fetchall()}
    if "accidents" not in tables:
        raise SystemExit("Table 'accidents' not found. Run scripts/01_normalize_data.py first.")

    con.execute(
        """
        CREATE OR REPLACE TABLE mart_year_state AS
        SELECT
            a.year,
            a.cve_ent,
            coalesce(e.name, 'Estado ' || a.cve_ent) AS state_name,
            count(*) AS accidents,
            sum(coalesce(a.deaths_total, 0)) AS deaths,
            sum(coalesce(a.injured_total, 0)) AS injured
        FROM accidents a
        LEFT JOIN dim_entidad e ON e.cve_ent = a.cve_ent
        GROUP BY a.year, a.cve_ent, e.name
        ORDER BY a.year, a.cve_ent
        """
    )

    con.execute(
        """
        CREATE OR REPLACE TABLE mart_heatmap AS
        SELECT
            year,
            round(latitude, 2) AS lat_cell,
            round(longitude, 2) AS lon_cell,
            count(*) AS accidents
        FROM accidents
        WHERE has_location
        GROUP BY year, lat_cell, lon_cell
        ORDER BY year, accidents DESC
        """
    )

    con.execute(
        """
        CREATE OR REPLACE TABLE mart_temporal AS
        SELECT
            year,
            day_of_week,
            hour,
            count(*) AS accidents,
            sum(coalesce(deaths_total, 0)) AS deaths,
            sum(coalesce(injured_total, 0)) AS injured
        FROM accidents
        WHERE day_of_week IS NOT NULL AND hour IS NOT NULL
        GROUP BY year, day_of_week, hour
        ORDER BY year, day_of_week, hour
        """
    )

    con.execute("CHECKPOINT")

    for table in ("accidents", "dim_entidad", "dim_municipio", "dim_codes",
                  "mart_year_state", "mart_heatmap", "mart_temporal"):
        count = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count:,} rows")

    con.close()
    print(f"database: {OUTPUT}")


if __name__ == "__main__":
    main()
