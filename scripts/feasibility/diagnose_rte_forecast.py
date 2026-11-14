"""Étude de faisabilité : alignement, changements d'heure et biais de la prévision J-1 de RTE.

Relit les exports éCO2mix déjà téléchargés par measure_eco2mix.py et écrit un résumé JSON
versionnable (agrégats seulement).

    uv run python scripts/feasibility/diagnose_rte_forecast.py --date 2026-11-14
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from day_ahead_load import diagnostics, eco2mix

RAW_ROOT = Path("data/raw/eco2mix")
SUMMARY = Path("docs/v0.0-faisabilite/data/diagnostic-prevision-rte.json")
ALIGNMENT_YEARS = [2015, 2019, 2022, 2024, 2025]
BIAS_START = "2020-01-01"
# Le consolidé de septembre-octobre 2026 n'est pas encore publié au téléchargement : la
# comparaison temps réel / consolidé sur ces mois est à refaire à cette date.
CHECK_DATE = "2026-12-15"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="date du téléchargement (AAAA-MM-JJ)")
    args = parser.parse_args()

    directory = RAW_ROOT / args.date
    paths = [directory / f"{name}.parquet" for name in eco2mix.DATASETS]
    raw = diagnostics.read_raw(paths)
    df, dropped = diagnostics.with_local_instants(raw)
    # L'alignement est mesuré sur les seules données définitives, de même nature d'une année
    # à l'autre.
    definitive = df[df["nature"] == "Données définitives"]

    summary = {
        "source": "RTE, éCO2mix national, via ODRÉ (Licence Ouverte 2.0)",
        "fichiers": [{"jeu": p.stem, "sha256": eco2mix.sha256_of(p)} for p in paths],
        "lignes_ecartees": dropped,
        "alignement_prevision_consommation": diagnostics.alignment_table(
            definitive, ALIGNMENT_YEARS
        ),
        "changement_heure_octobre": diagnostics.october_jumps(raw),
        "biais_mensuel_par_tranche": diagnostics.monthly_bias(df, BIAS_START),
        "verification_temps_reel_consolide": {
            "date_prevue": CHECK_DATE,
            "objet": (
                "comparer la consommation temps réel de septembre-octobre 2026 (fichier "
                "eco2mix-national-tr ci-dessus) au consolidé des mêmes mois une fois publié"
            ),
        },
    }
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    with SUMMARY.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"résumé écrit : {SUMMARY}")


if __name__ == "__main__":
    main()
