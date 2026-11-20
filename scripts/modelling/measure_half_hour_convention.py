"""v0.1 : convention de la demi-heure, mesurée dans l'entraînement seulement.

Règle écrite avant le calcul (journal des choix, entrée 3) : (t − 30, t] contre (t − 15, t + 15],
même LightGBM figé, chaque année de 2019 à 2023 mise de côté à tour de rôle, moyenne des MAPE ;
l'option la plus basse gagne, sauf écart relatif inférieur à 1 %, auquel cas (t − 30, t] reste.
Ne lit que le cache local, aucun appel réseau, aucune ligne de validation.

    uv run python scripts/modelling/measure_half_hour_convention.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from day_ahead_load import diagnostics, eco2mix
from day_ahead_load import modelling as md
from day_ahead_load import table as tb
from day_ahead_load import temperature_index as ti
from day_ahead_load import weather_features as wf
from day_ahead_load.weather_points import POINTS

ECO2MIX = Path("data/raw/eco2mix/2026-11-14")
WEATHER = Path("data/raw/meteo")
WEIGHTS = Path("docs/v0.0-faisabilite/data/indice-temperature-poids.json")
SUMMARY = Path("docs/v0.1-prevision-ponctuelle/data/convention-demi-heure.json")
TIE_RELATIVE = 0.01
FIRST_DAY = date(2012, 1, 1)
INTERVALS = {"fin": "(t − 30 min, t]", "centre": "(t − 15 min, t + 15 min]"}


def main() -> None:
    paths = [ECO2MIX / f"{name}.parquet" for name in eco2mix.DATASETS]
    instants, _ = diagnostics.with_local_instants(diagnostics.read_raw(paths))
    stored = json.loads(WEIGHTS.read_text(encoding="utf-8"))
    weights = ti.normalize(stored["resultats"]["consommation"]["poids_sur_2016_2023"])
    archive = wf.archive_index(WEATHER, "era5", POINTS, weights)
    no_runs = pd.DataFrame()  # entraînement seulement : aucun calcul ECMWF lu

    results: dict[str, Any] = {}
    for convention in (wf.END_LABEL, wf.CENTRED):
        table = tb.build(
            instants, archive, no_runs, FIRST_DAY, tb.TRAIN_LAST, convention=convention
        ).table
        folds = md.cross_validate(table)
        results[convention.name] = {
            "intervalle": INTERVALS[convention.name],
            "par_annee": {
                str(f.year): {
                    "lignes_entrainement": f.train_rows,
                    "lignes_jugees": f.scored_rows,
                    "mape_pct": round(f.mape_pct, 4),
                }
                for f in folds
            },
            "mape_moyenne_pct": round(sum(f.mape_pct for f in folds) / len(folds), 4),
        }
    end, centre = (results[c]["mape_moyenne_pct"] for c in ("fin", "centre"))
    gap = (centre - end) / end
    winner = "fin" if abs(gap) < TIE_RELATIVE or end <= centre else "centre"
    summary = {
        "regle": (
            "plus faible MAPE moyenne sur 2019-2023 (entraînement seulement) ; écart relatif "
            "inférieur à 1 % : (t − 30, t] conservé"
        ),
        "options": results,
        "ecart_relatif_centre_moins_fin": round(gap, 4),
        "retenue": winner,
    }
    SUMMARY.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
