"""Étude de faisabilité : écart entre ERA5, IFS historique et la prévision ECMWF de 00 UTC.

Sur la validation (15/03/2024 → 31/08/2025), aux 12 points et pour l'indice national de
température (poids par la consommation sur 2016-2023), mesure l'écart de la prévision vue au
moment de la décision face à ERA5 et face à IFS historique, et l'écart entre les deux sources
d'archive. Ne fait aucun appel réseau : lit le cache de `download_weather.py`.

Étiquette : sur cette période, les calculs ECMWF sont des calculs rejoués (cycle 49R1).

    uv run python scripts/feasibility/compare_weather_sources.py
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from day_ahead_load import temperature_index as ti
from day_ahead_load import weather as w
from day_ahead_load import weather_compare as wc
from day_ahead_load.weather_points import POINTS, Point

RAW_ROOT = Path("data/raw/meteo")
WEIGHTS = Path("docs/v0.0-faisabilite/data/indice-temperature-poids.json")
SUMMARY = Path("docs/v0.0-faisabilite/data/meteo-ecart-sources.json")
FIRST_DAY = date(2024, 3, 15)
LAST_DAY = date(2025, 8, 31)
LABEL = (
    "Prévision ECMWF de 00 UTC de la veille : calculs rejoués (cycle 49R1) sur toute la "
    "validation ; avantage possible face à la prévision émise à l'époque, surtout avant le "
    "12/11/2024 (cycle opérationnel 48r1)."
)


def days() -> list[date]:
    return [FIRST_DAY + timedelta(days=i) for i in range((LAST_DAY - FIRST_DAY).days + 1)]


def in_validation(frame: pd.DataFrame) -> pd.DataFrame:
    local = pd.DatetimeIndex(frame.index).tz_convert(wc.PARIS)
    keep = (local.date >= FIRST_DAY) & (local.date <= LAST_DAY)
    return frame[keep]


def main() -> None:
    stored = json.loads(WEIGHTS.read_text(encoding="utf-8"))
    weights = ti.normalize(stored["resultats"]["consommation"]["poids_sur_2016_2023"])
    validation_days = days()

    per_point: dict[str, Any] = {}
    temperature: dict[str, dict[Point, pd.Series]] = {"ecmwf": {}, "era5": {}, "ifs": {}}
    for point in POINTS:
        forecast = wc.forecast_series(RAW_ROOT, point, validation_days)
        era5 = in_validation(wc.archive_series(RAW_ROOT, "era5", point))
        ifs = in_validation(wc.archive_series(RAW_ROOT, "ifs_historique", point))
        per_point[point.nom] = {
            variable: {
                "ecmwf_face_a_era5": wc.gap(forecast[variable], era5[variable]),
                "ecmwf_face_a_ifs_historique": wc.gap(forecast[variable], ifs[variable]),
                "era5_face_a_ifs_historique": wc.gap(era5[variable], ifs[variable]),
            }
            for variable in w.VARIABLES
        }
        per_point[point.nom]["jours_avec_prevision"] = int(
            pd.DatetimeIndex(forecast.index).tz_convert(wc.PARIS).normalize().nunique()
        )
        temperature["ecmwf"][point] = forecast["temperature_2m"]
        temperature["era5"][point] = era5["temperature_2m"]
        temperature["ifs"][point] = ifs["temperature_2m"]

    index = {k: wc.weighted_index(v, weights) for k, v in temperature.items()}
    summary = {
        "periode": {"debut": str(FIRST_DAY), "fin": str(LAST_DAY), "heure": "Paris"},
        "etiquette": LABEL,
        "lecture": (
            "IFS historique est assemblé à partir de calculs du même modèle que la prévision : "
            "plus proche veut dire plus cohérent avec l'entrée du modèle, pas plus juste."
        ),
        "indice_national_temperature": {
            "ecmwf_face_a_era5": wc.gap(index["ecmwf"], index["era5"]),
            "ecmwf_face_a_ifs_historique": wc.gap(index["ecmwf"], index["ifs"]),
            "era5_face_a_ifs_historique": wc.gap(index["era5"], index["ifs"]),
            "par_mois_ecmwf_face_a_era5": wc.monthly_gap(index["ecmwf"], index["era5"]),
            "par_mois_ecmwf_face_a_ifs_historique": wc.monthly_gap(index["ecmwf"], index["ifs"]),
        },
        "par_point": per_point,
    }
    SUMMARY.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(summary["indice_national_temperature"], indent=2, ensure_ascii=False)[:2000])


if __name__ == "__main__":
    main()
