"""Étude de faisabilité : mesure de la qualité de l'historique éCO2mix national.

Télécharge (une seule fois par date) les exports Parquet des jeux définitif/consolidé et temps
réel, puis écrit un résumé JSON versionnable : aucune donnée brute n'y figure, seulement des
comptes et des agrégats.

    uv run python scripts/feasibility/measure_eco2mix.py --date 2026-11-14
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from day_ahead_load import eco2mix

RAW_ROOT = Path("data/raw/eco2mix")
SUMMARY = Path("docs/v0.0-faisabilite/data/eco2mix-mesures.json")


def measure(df: pd.DataFrame, now: pd.Timestamp) -> dict[str, Any]:
    # Le jeu temps réel contient déjà les prévisions du lendemain, sans consommation : on
    # mesure la consommation jusqu'à l'heure du téléchargement seulement.
    past = df[df["date_heure"] <= now]
    half_hours = past[past["date_heure"].dt.minute.isin([0, 30])]
    return {
        "periodes": eco2mix.periods_by_nature(df),
        "raccords": eco2mix.seams(df),
        "doublons": eco2mix.duplicates(df),
        "horodatages_absents": eco2mix.missing_timestamps(df),
        "jours_par_nombre_de_lignes": eco2mix.local_day_sizes(df),
        "jours_irreguliers": eco2mix.irregular_days(df),
        "consommation_renseignee_par_minute": eco2mix.fill_by_minute(past, "consommation"),
        "prevision_j1_renseignee_par_minute": eco2mix.fill_by_minute(df, "prevision_j1"),
        "consommation_min_mediane_max": eco2mix.consumption_range_by_year(past),
        "erreur_prevision_j1_rte_demi_heures": eco2mix.j1_error_by_year(half_hours),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="date du téléchargement (AAAA-MM-JJ)")
    args = parser.parse_args()

    directory = RAW_ROOT / args.date
    downloads = [eco2mix.download(name, directory) for name in eco2mix.DATASETS]
    now = pd.Timestamp(max(d.path.stat().st_mtime for d in downloads), unit="s", tz="UTC")
    df = eco2mix.load([d.path for d in downloads])

    summary = {
        "source": "RTE, éCO2mix national, via ODRÉ (Licence Ouverte 2.0)",
        "telechargement_utc": now.isoformat(),
        "fichiers": [{"jeu": d.dataset, "octets": d.size, "sha256": d.sha256} for d in downloads],
        "mesures": measure(df, now),
    }
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    with SUMMARY.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"résumé écrit : {SUMMARY}")


if __name__ == "__main__":
    main()
