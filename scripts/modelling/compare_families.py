"""v0.1 : familles de modèles et variantes du niveau, sur la grille complète.

Règle écrite avant le calcul (journal des choix, entrée 12). Six modèles (régression linéaire
ou LightGBM, sans niveau, niveau en variable ou rapport), ERA5 à l'entraînement depuis le
01/01/2017. Ordre total de simplicité, la famille avant le niveau ; chaque modèle est opposé
au modèle retenu jusque-là avec le test de bruit de l'entrée 4. LightGBM avec le niveau est le
modèle A17 de l'entrée 6 : sa MAPE doit être retrouvée à l'identique. La table s'arrête au
31/08/2025 : le test n'est jamais lu. Ne lit que le cache local, aucun appel réseau. N'écrit
que des erreurs agrégées, jamais les séries.

    uv run python scripts/modelling/compare_families.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from day_ahead_load import diagnostics, eco2mix
from day_ahead_load import modelling as md
from day_ahead_load import table as tb
from day_ahead_load import temperature_index as ti
from day_ahead_load import weather_features as wf
from day_ahead_load.weather_points import POINTS

ECO2MIX = Path("data/raw/eco2mix/2026-11-14")
WEATHER = Path("data/raw/meteo")
WEIGHTS = Path("docs/v0.0-faisabilite/data/indice-temperature-poids.json")
SOURCES = Path("docs/v0.1-prevision-ponctuelle/data/comparaison-sources.json")
SUMMARY = Path("docs/v0.1-prevision-ponctuelle/data/comparaison-familles.json")
FIRST_DAY = date(2012, 1, 1)
PREVIOUS_COMPARISONS = 5
# Rang de simplicité -> (nom, famille, niveau) ; G-niveau est A17, déjà évalué (entrée 6).
GRID = (
    ("L-sans", "lineaire", "sans"),
    ("L-niveau", "lineaire", "niveau"),
    ("L-rapport", "lineaire", "rapport"),
    ("G-sans", "lightgbm", "sans"),
    ("G-niveau", "lightgbm", "niveau"),
    ("G-rapport", "lightgbm", "rapport"),
)
ALREADY_EVALUATED = {"G-niveau": "A17"}


def gap_record(gap: md.PairedGap, simple: str, complex_: str) -> dict[str, Any]:
    return {
        "retenu_jusque_la": simple,
        "candidat": complex_,
        "mape_retenu_pct": round(gap.simple_mape, 4),
        "mape_candidat_pct": round(gap.complex_mape, 4),
        "difference_candidat_moins_retenu_pts": round(gap.difference, 4),
        "intervalle_95_pts": [round(gap.low, 4), round(gap.high, 4)],
        "gain_relatif": round(gap.relative_gain, 4),
        "candidat_retenu": gap.complex_retained,
    }


def main() -> None:
    paths = [ECO2MIX / f"{name}.parquet" for name in eco2mix.DATASETS]
    instants, _ = diagnostics.with_local_instants(diagnostics.read_raw(paths))
    stored = json.loads(WEIGHTS.read_text(encoding="utf-8"))
    weights = ti.normalize(stored["resultats"]["consommation"]["poids_sur_2016_2023"])
    archive = wf.archive_index(WEATHER, "era5", POINTS, weights)
    runs = wf.runs_index(WEATHER, POINTS, weights)
    table = tb.build(instants, archive, runs, FIRST_DAY, tb.VALIDATION[1]).table
    validation = table[table["periode"] == "validation"]
    truth = validation[tb.TARGET]
    days = validation["jour"]

    forecasts = {}
    models: dict[str, Any] = {}
    count = PREVIOUS_COMPARISONS
    for rank, (name, family, level) in enumerate(GRID, start=1):
        result = md.grid_forecast(table, family, level)
        forecasts[name] = result.forecast.reindex(validation.index).to_numpy()
        record: dict[str, Any] = {
            "rang_de_simplicite": rank,
            "famille": family,
            "niveau": level,
            "lignes_entrainement": result.train_rows,
            "mape_validation_pct": round(md.mape(truth, forecasts[name]), 4),
        }
        if result.columns is not None:
            record["colonnes"] = result.columns
            record["rang_de_la_matrice"] = result.rank
        if name in ALREADY_EVALUATED:
            record["deja_evalue"] = ALREADY_EVALUATED[name]
        else:
            count += 1
            record["comparaisons_cumulees"] = count
        models[name] = record

    previous = json.loads(SOURCES.read_text(encoding="utf-8"))["modeles"]["A17"]
    if models["G-niveau"]["mape_validation_pct"] != previous["mape_validation_pct"]:
        raise RuntimeError("G-niveau ne retrouve pas la MAPE de A17")

    steps = []
    retained = GRID[0][0]
    for name, _, _ in GRID[1:]:
        gap = md.paired_gap(truth, forecasts[retained], forecasts[name], days, tb.VALIDATION[0])
        steps.append(gap_record(gap, retained, name))
        if gap.complex_retained:
            retained = name

    summary = {
        "regle": "journal des choix, entrée 12",
        "entrainement": {
            "meteo": "ERA5",
            "premier_jour": str(md.TRAIN_FIRST),
            "dernier_jour": str(tb.TRAIN_LAST),
        },
        "regression_lineaire": {
            "chauffage_sous_degres": md.HEATING_BASE,
            "climatisation_au_dessus_degres": md.COOLING_BASE,
            "tranches_horaires": 48 // md.SLICE_HALF_HOURS,
            "manquants": "remplacés par la moyenne de l'entraînement",
        },
        "validation": {
            "premier_jour": str(tb.VALIDATION[0]),
            "dernier_jour": str(tb.VALIDATION[1]),
            "demi_heures_jugees": int(truth.notna().sum()),
            "tirages_bootstrap": md.REPLICATES,
            "graine": md.SEED,
        },
        "modeles": models,
        "etapes": steps,
        "retenu": retained,
        "comparaisons_sur_la_validation_cumulees": count,
    }
    SUMMARY.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"retenu : {retained} ; détail dans {SUMMARY}")


if __name__ == "__main__":
    main()
