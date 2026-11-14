"""Étude de faisabilité : erreur des références simples et critère de go/no-go.

Critère fixé avant toute mesure (règles de go/no-go, 14 novembre 2026) : la MAPE du naïf
saisonnier sur les demi-heures doit valoir au moins deux fois celle de la meilleure version
de RTE corrigé dont la correction n'utilise que du consolidé publié. Ces versions restent
avantagées : la prévision J-1 elle-même est publiée après midi la veille. Le critère compare
donc le naïf à la meilleure prévision connue, disponible à l'heure de la décision ou non. Le
naïf retenu est J-7 : plus fort que les naïfs réalistes, il rend le critère plus difficile à
remplir.

Comparaison principale de RTE : moyenne f(t-15), f(t) (figée le 14 novembre 2026) ; f(t) et
f(t-15) en analyse de sensibilité.

    uv run python scripts/feasibility/measure_references.py --date 2026-11-14
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from day_ahead_load import diagnostics, eco2mix
from day_ahead_load import references as refs

RAW_ROOT = Path("data/raw/eco2mix")
SUMMARY = Path("docs/v0.0-faisabilite/data/references-mesures.json")
# Jours livrés jugés : la météo prévue (calcul ECMWF de 00 h UTC la veille) existe à partir du
# 14 mars 2024 ; la cible consolidée s'arrête fin août 2026.
FIRST_DAY = "2024-03-15"
LAST_DAY = "2026-08-31"
NAIVE = "naif_j7"
CORRECTED_RTE = ("rte_corrige_retard_reel", "rte_corrige_meme_mois_an_dernier")
THRESHOLD = 2.0
ALIGNMENTS = {"moyenne f(t-15), f(t)": (-1, 0), "f(t)": (0,), "f(t-15)": (-1,)}


def judged_targets(conso: pd.Series) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(conso.index)
    start = pd.Timestamp(FIRST_DAY)
    end = pd.Timestamp(LAST_DAY) + pd.Timedelta(days=1)
    return index[(index >= start) & (index < end)]


def criterion(errors: dict[str, dict[str, float | int]]) -> dict[str, Any]:
    best = min(CORRECTED_RTE, key=lambda name: errors[name]["mape_pct"])
    ratio = float(errors[NAIVE]["mape_pct"]) / float(errors[best]["mape_pct"])
    return {
        "naif": NAIVE,
        "meilleur_rte_corrige": best,
        "categorie_du_meilleur_rte_corrige": "avantagée : publiée après la décision",
        "rapport_mape": round(ratio, 2),
        "seuil": THRESHOLD,
        "rempli": ratio >= THRESHOLD,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="date du téléchargement (AAAA-MM-JJ)")
    args = parser.parse_args()

    paths = [RAW_ROOT / args.date / f"{name}.parquet" for name in eco2mix.DATASETS]
    df, _ = diagnostics.with_local_instants(diagnostics.read_raw(paths))
    conso = refs.target_series(df)
    forecast = refs.forecast_series(df)
    targets = judged_targets(conso)

    results: dict[str, Any] = {}
    for label, offsets in ALIGNMENTS.items():
        values = refs.compute(conso, forecast, targets, offsets)
        overall = refs.errors(conso, values)
        by_year = {
            str(year): refs.errors(conso, values[pd.DatetimeIndex(values.index).year == year])
            for year in sorted(set(pd.DatetimeIndex(values.index).year))
        }
        results[label] = {
            "periode": overall,
            "par_annee": by_year,
            "critere": criterion(overall),
            "demi_heures_manquantes_par_cause": refs.missing_by_cause(
                conso, values, FIRST_DAY, LAST_DAY
            ),
        }

    main_label = next(iter(ALIGNMENTS))
    ratios = [results[label]["critere"]["rapport_mape"] for label in ALIGNMENTS]
    summary = {
        "source": "RTE, éCO2mix national, via ODRÉ (Licence Ouverte 2.0)",
        "fichiers": [{"jeu": p.stem, "sha256": eco2mix.sha256_of(p)} for p in paths],
        "jours_juges": {"premier": FIRST_DAY, "dernier": LAST_DAY},
        "regles": {
            "decision": "midi la veille, heure de Paris",
            "consolide_publie": (
                f"mois M disponible le 1er du mois M+{refs.CONSOLIDATED_LAG_MONTHS}"
            ),
            "consolide_publie_justification": refs.CONSOLIDATED_LAG_JUSTIFICATION,
            "prevision_rte_j1": (
                "publiée après la décision : vers 14 h 30 selon le portail de RTE, à interroger "
                "vers 19 h 30 selon le guide de son API ; toute référence qui la lit est "
                "avantagée, même corrigée avec du consolidé publié"
            ),
            "mesure": "MAPE sur les demi-heures, échantillon commun à toutes les références",
        },
        "references": [
            {
                "nom": r.name,
                "categorie": r.category,
                "description": r.description,
                "ne_lit_que_du_consolide_publie": r.published_consolidated_only,
            }
            for r in refs.REFERENCES
        ],
        "alignement_principal": main_label,
        "resultats": results,
        "sensibilite_alignement": {
            "rapport_mape_min": min(ratios),
            "rapport_mape_max": max(ratios),
            "conclusion_identique": len(
                {results[label]["critere"]["rempli"] for label in ALIGNMENTS}
            )
            == 1,
        },
    }
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    with SUMMARY.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"résumé écrit : {SUMMARY}")


if __name__ == "__main__":
    main()
