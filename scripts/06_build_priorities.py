#!/usr/bin/env python3
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "curated" / "atus.duckdb"
EXPORT_PATH = ROOT / "data" / "curated" / "priorities_top100.csv"

QUERY = """
    SELECT
        h.hotspot_id,
        h.crashes,
        h.deaths,
        h.injured,
        h.fatal_share,
        h.years_present,
        h.centroid_lat,
        h.centroid_lon,
        h.municipality_name,
        h.state_name,
        p.dominant_type,
        p.dominant_type_label,
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
    FROM analytics_hotspots h
    JOIN analytics_hotspot_profile p USING (hotspot_id)
"""


def place_name(row):
    if row["street_1"] and row["street_2"] and row["street_1"] != row["street_2"]:
        return f"{row['street_1']} × {row['street_2']}"
    if row["street_1"]:
        return row["street_1"]
    return row["municipality_name"] or "Ubicación sin nombre"


def primary_action(row):
    if row["pedestrian_share"] >= 0.25:
        return "Peatones: cruces a nivel, islas de refugio, iluminación y reducción de velocidad"
    if row["cyclist_share"] >= 0.15:
        return "Ciclistas: carril protegido y rediseño de intersecciones"
    if row["motorcycle_share"] >= 0.30:
        return "Motocicletas: separación de carriles, control de velocidad y uso de casco"
    if row["suburban_share"] >= 0.40 or row["unpaved_share"] >= 0.20 or row["dominant_type"] == 7:
        return "Salida del camino: acotamiento, señales preventivas y barreras"
    if row["dominant_type"] == 1:
        return "Intersecciones: semáforos, carriles de vuelta y control de velocidad"
    return "Revisión de ingeniería de detalle en el sitio"


def secondary_actions(row):
    actions = []
    if row["alcohol_share"] >= 0.08 and row["night_share"] >= 0.30:
        actions.append("Operativos nocturnos y control de alcohol")
    if row["night_share"] >= 0.40:
        actions.append("Mejorar iluminación y visibilidad")
    if row["pedestrian_share"] >= 0.15 and row["pedestrian_share"] < 0.25:
        actions.append("Revisar cruces peatonales")
    if row["cyclist_share"] >= 0.10 and row["cyclist_share"] < 0.15:
        actions.append("Revisar espacio para bicicletas")
    return "; ".join(actions) if actions else None


def confidence(row):
    if row["deaths"] >= 5:
        return "alta"
    if row["deaths"] >= 2:
        return "media"
    return "baja"


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"{DB_PATH} not found. Run scripts/01-04 first.")

    con = duckdb.connect(str(DB_PATH))
    tables = {name for (name,) in con.execute("SHOW TABLES").fetchall()}
    if "analytics_hotspots" not in tables or "analytics_hotspot_profile" not in tables:
        raise SystemExit("Run scripts/04_analyze_hotspots.py first.")

    frame = con.execute(QUERY).fetchdf()
    print(f"hotspots: {len(frame):,}")

    frame["place"] = frame.apply(place_name, axis=1)
    frame["priority_score"] = frame["deaths"] * 10 + frame["injured"] * 2
    frame["primary_action"] = frame.apply(primary_action, axis=1)
    frame["secondary_action"] = frame.apply(secondary_actions, axis=1)
    frame["confidence"] = frame.apply(confidence, axis=1)
    frame["signals"] = frame.apply(
        lambda row: (
            f"peatones {row['pedestrian_share']:.0%} · "
            f"motos {row['motorcycle_share']:.0%} · "
            f"noche {row['night_share'] or 0:.0%} · "
            f"alcohol {row['alcohol_share']:.0%}"
        ),
        axis=1,
    )

    frame = frame.sort_values(
        ["deaths", "injured", "crashes"], ascending=False
    ).reset_index(drop=True)
    frame["rank"] = frame.index + 1

    columns = [
        "rank", "hotspot_id", "place", "municipality_name", "state_name",
        "centroid_lat", "centroid_lon", "crashes", "deaths", "injured",
        "fatal_share", "years_present", "dominant_type", "dominant_type_label",
        "pedestrian_share", "cyclist_share", "motorcycle_share", "night_share",
        "weekend_share", "suburban_share", "unpaved_share", "alcohol_share",
        "peak_hour", "priority_score", "primary_action", "secondary_action",
        "confidence", "signals",
    ]
    result = frame[columns]

    con.register("priority_frame", result)
    con.execute(
        "CREATE OR REPLACE TABLE analytics_priorities AS SELECT * FROM priority_frame"
    )
    con.unregister("priority_frame")
    con.execute("CHECKPOINT")
    con.close()

    result.head(100).to_csv(EXPORT_PATH, index=False)
    print(f"priorities written: {len(result):,}")
    print(f"export: {EXPORT_PATH}")
    print("\ntop 10:")
    for row in result.head(10).itertuples():
        print(
            f"  {row.rank:>3}. {row.place} ({row.municipality_name}) "
            f"— {row.crashes} choques, {row.deaths} muertes, {row.injured} heridos "
            f"[{row.confidence}]"
        )


if __name__ == "__main__":
    main()
