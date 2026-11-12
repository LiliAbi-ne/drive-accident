#!/usr/bin/env python3
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "curated" / "atus.duckdb"

FEATURE_COLUMNS = [
    "year", "type_code", "urban_code", "suburban_code", "road_code",
    "alcohol_code", "seatbelt_code", "hour", "day_of_week", "driver_age",
    "automovil", "campasaj", "microbus", "pascamion", "omnibus", "tranvia",
    "camioneta", "camion", "tractor", "ferrocarril", "motocicleta",
    "bicicleta", "otrovehiculo", "severity_code",
]
SELECT_COLUMNS = ", ".join(FEATURE_COLUMNS)

TRAIN_SQL = f"""
    SELECT {SELECT_COLUMNS}
    FROM accidents
    WHERE year <= 2023 AND severity_code IS NOT NULL
      AND (severity_code = 1 OR hash(accident_id) % 20 = 0)
"""

TEST_SQL = f"""
    SELECT {SELECT_COLUMNS}
    FROM accidents
    WHERE year = 2024 AND severity_code IS NOT NULL
"""

TYPE_LABELS = {
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
URBAN_LABELS = {0: "Sin accidente en esta zona", 1: "Intersección", 2: "No intersección"}
SUBURBAN_LABELS = {
    0: "Sin accidente en esta zona",
    1: "Camino rural",
    2: "Carretera estatal",
    3: "Otro camino",
}
ROAD_LABELS = {0: "Certificado cero", 1: "Pavimentada", 2: "No pavimentada"}
ALCOHOL_LABELS = {0: "Certificado cero", 4: "Sí", 5: "No", 6: "Se ignora"}
SEATBELT_LABELS = {0: "Certificado cero", 7: "Sí", 8: "No", 9: "Se ignora"}
AGE_BANDS = ["<18", "18-24", "25-34", "35-44", "45-54", "55-64", "65+", "unknown"]
HOUR_BANDS = ["00-05", "06-11", "12-17", "18-23", "unknown"]

VEHICLE_COLUMNS = [
    "automovil", "campasaj", "microbus", "pascamion", "omnibus", "tranvia",
    "camioneta", "camion", "tractor", "ferrocarril", "motocicleta",
    "bicicleta", "otrovehiculo",
]
HEAVY_COLUMNS = ["camion", "camioneta", "pascamion", "omnibus", "tractor", "ferrocarril"]


def band(value, limits, labels):
    if value is None or pd.isna(value):
        return "unknown"
    for low, high, label in limits:
        if low <= value <= high:
            return label
    return "unknown"


def build_features(df, include_type):
    df = df.reset_index(drop=True)
    out = pd.DataFrame(index=df.index)

    if include_type:
        type_cat = pd.Categorical(df["type_code"], categories=list(TYPE_LABELS))
        out = pd.concat(
            [out, pd.get_dummies(type_cat, prefix="type", drop_first=True, dtype=float)],
            axis=1,
        )

    urban = pd.Categorical(df["urban_code"], categories=[1, 2, 0])
    suburban = pd.Categorical(df["suburban_code"], categories=[1, 2, 3, 0])
    road = pd.Categorical(df["road_code"], categories=[1, 2, 0])
    alcohol = pd.Categorical(df["alcohol_code"], categories=[5, 4, 6, 0])
    seatbelt = pd.Categorical(df["seatbelt_code"], categories=[7, 8, 9, 0])

    out = pd.concat(
        [
            out,
            pd.get_dummies(urban, prefix="urban", drop_first=True, dtype=float),
            pd.get_dummies(suburban, prefix="suburban", drop_first=True, dtype=float),
            pd.get_dummies(road, prefix="road", drop_first=True, dtype=float),
            pd.get_dummies(alcohol, prefix="alcohol", drop_first=True, dtype=float),
            pd.get_dummies(seatbelt, prefix="seatbelt", drop_first=True, dtype=float),
        ],
        axis=1,
    )

    age_band = df["driver_age"].map(
        lambda value: band(
            value,
            [(12, 17, "<18"), (18, 24, "18-24"), (25, 34, "25-34"),
             (35, 44, "35-44"), (45, 54, "45-54"), (55, 64, "55-64"),
             (65, 120, "65+")],
            AGE_BANDS,
        )
    )
    age_band = pd.Categorical(age_band, categories=AGE_BANDS)
    out = pd.concat(
        [out, pd.get_dummies(age_band, prefix="age", drop_first=True, dtype=float)],
        axis=1,
    )

    hour_band = df["hour"].map(
        lambda value: band(
            value,
            [(0, 5, "00-05"), (6, 11, "06-11"), (12, 17, "12-17"), (18, 23, "18-23")],
            HOUR_BANDS,
        )
    )
    hour_band = pd.Categorical(hour_band, categories=HOUR_BANDS)
    out = pd.concat(
        [out, pd.get_dummies(hour_band, prefix="hour", drop_first=True, dtype=float)],
        axis=1,
    )

    out["is_weekend"] = df["day_of_week"].isin([6, 7]).astype(float)
    out["has_heavy_vehicle"] = (df[HEAVY_COLUMNS].fillna(0).sum(axis=1) > 0).astype(float)
    out["multiple_vehicles"] = (df[VEHICLE_COLUMNS].fillna(0).sum(axis=1) > 1).astype(float)

    return out.fillna(0.0)


def pretty(feature):
    if feature.startswith("type_"):
        return f"Tipo: {TYPE_LABELS.get(int(feature.split('_')[1]), feature)}"
    if feature.startswith("urban_"):
        return f"Zona urbana: {URBAN_LABELS.get(int(feature.split('_')[1]), feature)}"
    if feature.startswith("suburban_"):
        return f"Zona suburbana: {SUBURBAN_LABELS.get(int(feature.split('_')[1]), feature)}"
    if feature.startswith("road_"):
        return f"Superficie: {ROAD_LABELS.get(int(feature.split('_')[1]), feature)}"
    if feature.startswith("alcohol_"):
        return f"Aliento alcohólico: {ALCOHOL_LABELS.get(int(feature.split('_')[1]), feature)}"
    if feature.startswith("seatbelt_"):
        return f"Cinturón: {SEATBELT_LABELS.get(int(feature.split('_')[1]), feature)}"
    if feature.startswith("age_"):
        return f"Edad del conductor: {feature.split('_', 1)[1]}"
    if feature.startswith("hour_"):
        return f"Hora: {feature.split('_', 1)[1]}"
    if feature == "is_weekend":
        return "Fin de semana"
    if feature == "has_heavy_vehicle":
        return "Vehículo pesado involucrado"
    if feature == "multiple_vehicles":
        return "Más de un vehículo"
    return feature


def fit_and_export(name, train, test, include_type):
    X_train = build_features(train, include_type)
    y_train = (train["severity_code"] == 1).astype(int).to_numpy()

    model = LogisticRegression(C=np.inf, solver="lbfgs", max_iter=2000)
    model.fit(X_train, y_train)

    X_test = build_features(test, include_type)
    X_test = X_test.reindex(columns=X_train.columns, fill_value=0.0)
    y_test = (test["severity_code"] == 1).astype(int).to_numpy()
    auc = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])

    coefficients = model.coef_[0]
    intercept = model.intercept_[0]

    design = np.column_stack([np.ones(len(X_train)), X_train.to_numpy()])
    theta = np.concatenate([[intercept], coefficients])
    probability = 1 / (1 + np.exp(-(design @ theta)))
    weights = probability * (1 - probability)
    hessian = design.T @ (design * weights[:, None])
    covariance = np.linalg.pinv(hessian)
    standard_error = np.sqrt(np.maximum(np.diag(covariance), 1e-12))[1:]

    odds_ratio = np.exp(coefficients)
    z_values = coefficients / standard_error
    p_values = 2 * (1 - norm.cdf(np.abs(z_values)))

    rows = [
        {
            "model": name,
            "feature": feature,
            "feature_label": pretty(feature),
            "odds_ratio": float(odds_ratio[index]),
            "ci_low": float(np.exp(coefficients[index] - 1.96 * standard_error[index])),
            "ci_high": float(np.exp(coefficients[index] + 1.96 * standard_error[index])),
            "p_value": float(p_values[index]),
            "observations": int(len(X_train)),
            "sample_fatal_rate": float(y_train.mean()),
            "test_auc": float(auc),
            "quality_flag": bool(feature.endswith("_unknown")),
        }
        for index, feature in enumerate(X_train.columns)
    ]

    print(
        f"{name}: observations={len(X_train):,}  fatal_rate={y_train.mean():.3f}  "
        f"test_auc={auc:.3f}"
    )
    return rows


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"{DB_PATH} not found. Run scripts/01-03 first.")

    con = duckdb.connect(str(DB_PATH))
    train = con.execute(TRAIN_SQL).fetchdf()
    test = con.execute(TEST_SQL).fetchdf()
    print(f"train rows: {len(train):,}  test rows: {len(test):,}")

    rows = []
    rows += fit_and_export("all", train, test, include_type=True)
    rows += fit_and_export(
        "pedestrian", train[train["type_code"] == 2], test[test["type_code"] == 2], include_type=False
    )
    rows += fit_and_export(
        "motorcycle", train[train["type_code"] == 10], test[test["type_code"] == 10], include_type=False
    )

    result = pd.DataFrame(rows)
    con.register("severity_frame", result)
    con.execute("CREATE OR REPLACE TABLE analytics_severity AS SELECT * FROM severity_frame")
    con.unregister("severity_frame")
    con.execute("CHECKPOINT")

    print("\nstrongest associations (all crashes):")
    all_model = result[(result["model"] == "all") & (~result["quality_flag"])].copy()
    all_model["distance"] = (np.log(all_model["odds_ratio"])).abs()
    for row in all_model.sort_values("distance", ascending=False).head(8).itertuples():
        print(
            f"  OR={row.odds_ratio:.2f} "
            f"[{row.ci_low:.2f}, {row.ci_high:.2f}]  {row.feature_label}"
        )

    con.close()


if __name__ == "__main__":
    main()
