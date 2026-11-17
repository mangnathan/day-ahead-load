"""v0.1 : construit la table de données à la demi-heure (variante A, ERA5 à l'entraînement).

Lit seulement le cache local : éCO2mix du 14/11/2026, ERA5 et calculs ECMWF de 00 UTC aux
12 points, poids de l'indice national fixés en v0.0. Aucun appel réseau. La cible du test reste
masquée. Écrit la table dans `data/processed/` (hors dépôt) et un résumé de comptages, sans
aucune valeur de la série, dans `docs/v0.1-prevision-ponctuelle/data/`.

    uv run python scripts/modelling/build_table.py
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from day_ahead_load import diagnostics, eco2mix
from day_ahead_load import table as tb
from day_ahead_load import temperature_index as ti
from day_ahead_load import weather_features as wf
from day_ahead_load.weather_points import POINTS

ECO2MIX = Path("data/raw/eco2mix/2026-11-14")
WEATHER = Path("data/raw/meteo")
WEIGHTS = Path("docs/v0.0-faisabilite/data/indice-temperature-poids.json")
OUTPUT = Path("data/processed/table-demi-heure-A.parquet")
SUMMARY = Path("docs/v0.1-prevision-ponctuelle/data/table-resume.json")
FIRST_DAY = date(2012, 1, 1)
# Dernier calcul ECMWF en cache : 13/11/2026, qui couvre le jour livré du 14/11/2026.
LAST_DAY = date(2026, 11, 14)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(table: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, rows in table.groupby("periode", sort=False):
        days = rows["jour"]
        out[str(name)] = {
            "premier_jour": str(days.min()),
            "dernier_jour": str(days.max()),
            "demi_heures": len(rows),
            "manquants_par_colonne": {
                c: int(rows[c].isna().sum()) for c in table.columns if rows[c].isna().any()
            },
        }
    return out


def main() -> None:
    paths = [ECO2MIX / f"{name}.parquet" for name in eco2mix.DATASETS]
    instants, dropped = diagnostics.with_local_instants(diagnostics.read_raw(paths))
    stored = json.loads(WEIGHTS.read_text(encoding="utf-8"))
    weights = ti.normalize(stored["resultats"]["consommation"]["poids_sur_2016_2023"])
    archive = wf.archive_index(WEATHER, "era5", POINTS, weights)
    runs = wf.runs_index(WEATHER, POINTS, weights)

    table = tb.build(instants, archive, runs, FIRST_DAY, LAST_DAY)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(OUTPUT)

    summary = {
        "variante": "A : ERA5 à l'entraînement, calculs ECMWF de 00 UTC ensuite",
        "entrees": {
            **{p.name: {"sha256": sha256(p)} for p in paths},
            "poids_indice": str(WEIGHTS),
            "points": len(POINTS),
            "calculs_ecmwf_en_cache": int(runs.index.get_level_values("calcul").nunique()),
            "holidays": importlib.metadata.version("holidays"),
        },
        "lignes_ecartees_eco2mix": dropped,
        "colonnes": list(table.columns),
        "cible_du_test": "masquée",
        "par_periode": summarize(table),
    }
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(summary["par_periode"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
