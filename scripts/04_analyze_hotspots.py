#!/usr/bin/env python3
from math import cos, radians
from pathlib import Path

import duckdb
import numpy as np
from sklearn.neighbors import BallTree

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "curated" / "atus.duckdb"

GRID = 3
RADIUS_METERS = 300.0
MIN_SEPARATION_METERS = 600.0
MAX_HOTSPOTS = 200
MIN_CENTER_CRASHES = 5
MIN_YEARS_PRESENT = 3
MIN_CLUSTER_CRASHES = 10

CELL_SQL = f"""
    SELECT
        year,
        round(latitude, {GRID}) AS lat,
        round(longitude, {GRID}) AS lon,
        count(*) AS crashes,
        sum(coalesce(deaths_total, 0)) AS deaths,
        sum(coalesce(injured_total, 0)) AS injured
    FROM accidents
    WHERE has_location AND year BETWEEN 2019 AND 2024
    GROUP BY 1, 2, 3
"""

STATS_SQL = """
    SELECT
        c.hotspot_id,
        count(*) AS crashes,
        sum(coalesce(a.deaths_total, 0)) AS deaths,
        sum(coalesce(a.injured_total, 0)) AS injured,
        sum(CASE WHEN a.severity_code = 1 THEN 1 ELSE 0 END) AS fatal_crashes,
        count(DISTINCT a.year) AS years_present,
        min(a.year) AS first_year,
        max(a.year) AS last_year,
        avg(a.latitude) AS centroid_lat,
        avg(a.longitude) AS centroid_lon,
        min(a.latitude) AS min_lat,
        max(a.latitude) AS max_lat,
        min(a.longitude) AS min_lon,
        max(a.longitude) AS max_lon,
        mode(a.cvegeo) AS cvegeo
    FROM accidents a
    JOIN _cell_hotspot c
      ON round(a.latitude, 3) = c.lat AND round(a.longitude, 3) = c.lon
    WHERE a.has_location AND a.year BETWEEN 2019 AND 2024
    GROUP BY 1
"""

PROFILE_SQL = """
    SELECT
        c.hotspot_id,
        mode(a.type_code) AS dominant_type,
        avg(CASE WHEN a.type_code = 2 THEN 1.0 ELSE 0.0 END) AS pedestrian_share,
        avg(CASE WHEN a.type_code = 11 THEN 1.0 ELSE 0.0 END) AS cyclist_share,
        avg(CASE WHEN a.type_code = 10 THEN 1.0 ELSE 0.0 END) AS motorcycle_share,
        avg(CASE WHEN a.hour IS NULL THEN NULL
                 WHEN a.hour >= 20 OR a.hour < 6 THEN 1.0 ELSE 0.0 END) AS night_share,
        avg(CASE WHEN a.day_of_week IN (6, 7) THEN 1.0 ELSE 0.0 END) AS weekend_share,
        avg(CASE WHEN a.suburban_code > 0 THEN 1.0 ELSE 0.0 END) AS suburban_share,
        avg(CASE WHEN a.road_code = 2 THEN 1.0 ELSE 0.0 END) AS unpaved_share,
        avg(CASE WHEN a.alcohol_code = 4 THEN 1.0 ELSE 0.0 END) AS alcohol_share,
        mode(a.street_1) FILTER (WHERE a.street_1 IS NOT NULL) AS street_1,
        mode(a.street_2) FILTER (WHERE a.street_2 IS NOT NULL) AS street_2,
        mode(a.hour) AS peak_hour
    FROM accidents a
    JOIN _cell_hotspot c
      ON round(a.latitude, 3) = c.lat AND round(a.longitude, 3) = c.lon
    WHERE a.has_location AND a.year BETWEEN 2019 AND 2024
    GROUP BY 1
"""


def project(lat, lon, mean_lat):
    x = lon * 111_320.0 * cos(radians(mean_lat))
    y = lat * 110_540.0
    return x, y


def select_hotspots(cells):
    mean_lat = float(cells["lat"].mean())
    x, y = project(cells["lat"].to_numpy(), cells["lon"].to_numpy(), mean_lat)
    coords = np.column_stack([x, y])
    tree = BallTree(coords)

    score = (
        cells["deaths"].to_numpy() * 10
        + cells["injured"].to_numpy() * 2
        + cells["crashes"].to_numpy()
    )
    candidate_index = np.where(cells["crashes"].to_numpy() >= MIN_CENTER_CRASHES)[0]
    order = candidate_index[np.argsort(-score[candidate_index])]

    assignment = np.full(len(cells), -1, dtype=int)
    suppressed = np.zeros(len(cells), dtype=bool)
    hotspot_count = 0

    for index in order:
        if suppressed[index]:
            continue
        if hotspot_count >= MAX_HOTSPOTS:
            break

        members = tree.query_radius(coords[index:index + 1], r=RADIUS_METERS)[0]
        unassigned = members[assignment[members] < 0]
        if len(unassigned) == 0:
            continue

        assignment[unassigned] = hotspot_count
        hotspot_count += 1

        nearby = tree.query_radius(
            coords[index:index + 1], r=MIN_SEPARATION_METERS
        )[0]
        suppressed[nearby] = True

    return assignment


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"{DB_PATH} not found. Run scripts/01-03 first.")

    con = duckdb.connect(str(DB_PATH))
    cells = con.execute(CELL_SQL).fetchdf()
    print(f"grid cells by year: {len(cells):,}")

    pooled = (
        cells.groupby(["lat", "lon"], as_index=False)
        .agg(crashes=("crashes", "sum"), deaths=("deaths", "sum"), injured=("injured", "sum"))
    )
    print(f"distinct cells: {len(pooled):,}")

    assignment = select_hotspots(pooled)
    mapped = pooled.assign(hotspot_index=assignment)
    mapped = mapped[mapped["hotspot_index"] >= 0]
    mapped["hotspot_id"] = mapped["hotspot_index"].map(lambda index: f"h{index:04d}")
    print(f"cells assigned to hotspots: {len(mapped):,}")
    print(f"hotspots selected: {mapped['hotspot_id'].nunique():,}")

    con.execute("DROP TABLE IF EXISTS _cell_hotspot")
    con.execute("CREATE TEMP TABLE _cell_hotspot (lat DOUBLE, lon DOUBLE, hotspot_id VARCHAR)")
    con.append(
        "_cell_hotspot",
        mapped[["lat", "lon", "hotspot_id"]].reset_index(drop=True),
    )

    con.execute("DROP TABLE IF EXISTS _cluster_stats")
    con.execute(f"CREATE TEMP TABLE _cluster_stats AS {STATS_SQL}")
    con.execute("DROP TABLE IF EXISTS _cluster_profile")
    con.execute(f"CREATE TEMP TABLE _cluster_profile AS {PROFILE_SQL}")

    con.execute(
        """
        CREATE OR REPLACE TABLE analytics_hotspots AS
        SELECT
            s.hotspot_id,
            row_number() OVER (
                ORDER BY s.deaths DESC, s.injured DESC, s.crashes DESC
            ) AS rank,
            s.centroid_lat,
            s.centroid_lon,
            s.min_lat,
            s.max_lat,
            s.min_lon,
            s.max_lon,
            s.crashes,
            s.deaths,
            s.injured,
            s.fatal_crashes,
            CASE WHEN s.crashes > 0
                 THEN round(s.fatal_crashes::DOUBLE / s.crashes, 4) ELSE 0 END AS fatal_share,
            s.years_present,
            s.first_year,
            s.last_year,
            s.cvegeo,
            m.cve_ent,
            m.name AS municipality_name,
            e.name AS state_name
        FROM _cluster_stats s
        LEFT JOIN dim_municipio m ON m.cvegeo = s.cvegeo
        LEFT JOIN dim_entidad e ON e.cve_ent = m.cve_ent
        WHERE s.years_present >= ? AND s.crashes >= ?
        """,
        [MIN_YEARS_PRESENT, MIN_CLUSTER_CRASHES],
    )

    con.execute(
        """
        CREATE OR REPLACE TABLE analytics_hotspot_profile AS
        SELECT
            p.hotspot_id,
            p.dominant_type,
            d.label AS dominant_type_label,
            p.pedestrian_share,
            p.cyclist_share,
            p.motorcycle_share,
            p.night_share,
            p.weekend_share,
            p.suburban_share,
            p.unpaved_share,
            p.alcohol_share,
            p.street_1,
            p.street_2,
            p.peak_hour
        FROM _cluster_profile p
        LEFT JOIN dim_codes d
          ON d.domain = 'accident_type' AND d.code = p.dominant_type
        WHERE p.hotspot_id IN (SELECT hotspot_id FROM analytics_hotspots)
        """
    )

    con.execute("CHECKPOINT")

    kept = con.execute("SELECT count(*) FROM analytics_hotspots").fetchone()[0]
    top = con.execute(
        """
        SELECT h.rank, h.municipality_name, h.crashes, h.deaths, h.injured,
               round(h.fatal_share * 100, 1), p.street_1
        FROM analytics_hotspots h
        LEFT JOIN analytics_hotspot_profile p USING (hotspot_id)
        ORDER BY h.rank LIMIT 10
        """
    ).fetchall()

    con.close()

    print(f"hotspots kept: {kept:,}")
    print("top hotspots:")
    for row in top:
        print("  ", row)


if __name__ == "__main__":
    main()
