"""Étude de faisabilité : complétude de la météo d'archive aux 12 points.

Condition du go/no-go (partie C) : moins de 1 % de trous dans la météo. Compte, par source,
point et variable, les heures absentes de la grille horaire attendue et les valeurs vides.
Ne fait aucun appel réseau : lit le cache de `download_weather.py`.

    uv run python scripts/feasibility/measure_weather_completeness.py
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from day_ahead_load import weather as w
from day_ahead_load import weather_compare as wc
from day_ahead_load.weather_points import POINTS

RAW_ROOT = Path("data/raw/meteo")
SUMMARY = Path("docs/v0.0-faisabilite/data/meteo-completude.json")
THRESHOLD_PCT = 1.0
ARCHIVE_SOURCES = ("era5", "ifs_historique")


def completeness(source: str) -> dict[str, Any]:
    spec = w.SOURCES[source]
    grid = pd.date_range(
        pd.Timestamp(spec.start, tz="UTC"),
        pd.Timestamp(spec.end + timedelta(days=1), tz="UTC"),
        freq="1h",
        inclusive="left",
    )
    points: dict[str, Any] = {}
    worst = 0.0
    for point in POINTS:
        series = wc.archive_series(RAW_ROOT, source, point).reindex(grid)
        per_variable = {}
        for variable in w.VARIABLES:
            missing = int(series[variable].isna().sum())
            pct = 100 * missing / len(grid)
            worst = max(worst, pct)
            per_variable[variable] = {"heures_manquantes": missing, "pct": round(pct, 4)}
        points[point.nom] = per_variable
    return {
        "periode_utc": {"debut": str(grid[0]), "fin": str(grid[-1])},
        "heures_attendues_par_point": len(grid),
        "pire_pct": round(worst, 4),
        "condition_moins_de_1_pct": worst < THRESHOLD_PCT,
        "par_point": points,
    }


def main() -> None:
    results = {source: completeness(source) for source in ARCHIVE_SOURCES}
    summary = {
        "regle": "Moins de 1 % d'heures manquantes par point et par variable (partie C).",
        "sources": results,
    }
    SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for source, result in results.items():
        print(
            source,
            result["heures_attendues_par_point"],
            "heures par point,",
            "pire",
            result["pire_pct"],
            "% ->",
            result["condition_moins_de_1_pct"],
        )


if __name__ == "__main__":
    main()
