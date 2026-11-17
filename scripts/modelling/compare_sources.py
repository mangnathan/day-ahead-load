"""v0.1 : comparaison des sources météo et de la durée de l'entraînement (A / B / C).

Règle écrite avant le calcul (journal des choix, entrée 4). Cinq modèles, même LightGBM figé,
même convention ; seuls la météo de l'entraînement et son premier jour changent. Validation :
calculs ECMWF de 00 UTC vus à midi la veille. Test de bruit : différence appariée de MAPE,
intervalle à 95 % par bootstrap par blocs d'une semaine. La table s'arrête au 31/08/2025 : le
test n'est jamais lu. Ne lit que le cache local, aucun appel réseau. N'écrit que des erreurs
agrégées, jamais les séries.

    uv run python scripts/modelling/compare_sources.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from day_ahead_load import diagnostics, eco2mix
from day_ahead_load import modelling as md
from day_ahead_load import table as tb
from day_ahead_load import temperature_index as ti
from day_ahead_load import weather_compare as wc
from day_ahead_load import weather_correction as wcor
from day_ahead_load import weather_features as wf
from day_ahead_load.weather_points import POINTS

ECO2MIX = Path("data/raw/eco2mix/2026-11-14")
WEATHER = Path("data/raw/meteo")
WEIGHTS = Path("docs/v0.0-faisabilite/data/indice-temperature-poids.json")
SUMMARY = Path("docs/v0.1-prevision-ponctuelle/data/comparaison-sources.json")
FIRST_DAY = date(2012, 1, 1)
START = {"12": date(2012, 1, 1), "17": date(2017, 1, 1)}
MODELS = {"A12": ("A", "12"), "A17": ("A", "17"), "C12": ("C", "12"), "C17": ("C", "17")}
MODELS["B17"] = ("B", "17")
SOURCES = {
    "A": "ERA5",
    "B": "IFS historique",
    "C": "ERA5 corrigé de l'écart moyen IFS − ERA5 (point, mois, heure UTC)",
}


def correction_summary(
    era5: dict[Any, pd.DataFrame], fixed: dict[Any, pd.DataFrame], gaps: dict[Any, pd.DataFrame]
) -> dict[str, Any]:
    """Taille moyenne de la correction et part des valeurs ramenées dans les bornes."""
    out: dict[str, Any] = {}
    for name, (low, high) in wcor.BOUNDS.items():
        clipped = total = 0
        for p in era5:
            raw = era5[p][name] + wcor.shift_for(era5[p], gaps[p])[name]
            known = raw.notna()
            clipped += int((known & (fixed[p][name] != raw)).sum())
            total += int(known.sum())
        out[name] = {
            "bornes": [low, high],
            "ecart_moyen_absolu_par_point_mois_heure": round(
                float(np.mean([g[name].abs().mean() for g in gaps.values()])), 4
            ),
            "part_ramenee_dans_les_bornes": round(clipped / total, 6),
        }
    out["non_corrigees"] = wcor.NOT_CORRECTED
    return out


def gap_record(gap: md.PairedGap, simple: str, complex_: str) -> dict[str, Any]:
    return {
        "simple": simple,
        "complexe": complex_,
        "mape_simple_pct": round(gap.simple_mape, 4),
        "mape_complexe_pct": round(gap.complex_mape, 4),
        "difference_complexe_moins_simple_pts": round(gap.difference, 4),
        "intervalle_95_pts": [round(gap.low, 4), round(gap.high, 4)],
        "gain_relatif": round(gap.relative_gain, 4),
        "complexe_retenue": gap.complex_retained,
    }


def main() -> None:
    paths = [ECO2MIX / f"{name}.parquet" for name in eco2mix.DATASETS]
    instants, _ = diagnostics.with_local_instants(diagnostics.read_raw(paths))
    stored = json.loads(WEIGHTS.read_text(encoding="utf-8"))
    weights = ti.normalize(stored["resultats"]["consommation"]["poids_sur_2016_2023"])
    runs = wf.runs_index(WEATHER, POINTS, weights)

    era5 = {p: wc.archive_series(WEATHER, "era5", p) for p in POINTS}
    ifs = {p: wc.archive_series(WEATHER, "ifs_historique_entrainement", p) for p in POINTS}
    gaps = {p: wcor.mean_gap(era5[p], ifs[p]) for p in POINTS}
    fixed = {p: wcor.corrected(era5[p], gaps[p]) for p in POINTS}
    archives = {"A": wf.national(era5, weights), "B": wf.national(ifs, weights)}
    archives["C"] = wf.national(fixed, weights)

    last = tb.VALIDATION[1]
    tables = {s: tb.build(instants, a, runs, FIRST_DAY, last).table for s, a in archives.items()}
    validation = tables["A"][tables["A"]["periode"] == "validation"]
    weather_columns = wf.feature_names()
    for source, table in tables.items():
        same = table.loc[validation.index, weather_columns].equals(validation[weather_columns])
        if not same:
            raise RuntimeError(f"météo de validation différente pour la source {source}")

    truth = validation[tb.TARGET]
    days = validation["jour"]
    forecasts: dict[str, np.ndarray] = {}
    models: dict[str, Any] = {}
    for count, (name, (source, length)) in enumerate(MODELS.items(), start=1):
        table = tables[source]
        forecast, rows = md.validation_forecast(table, START[length])
        forecasts[name] = forecast.reindex(validation.index).to_numpy()
        train = table[
            (table["periode"] == "entrainement")
            & (pd.to_datetime(table["jour"]) >= pd.Timestamp(START[length]))
            & table[tb.TARGET].notna()
        ]
        models[name] = {
            "source": SOURCES[source],
            "entrainement_depuis": str(START[length]),
            "lignes_entrainement": rows,
            "meteo_manquante_entrainement": {
                c: int(train[c].isna().sum()) for c in weather_columns if train[c].isna().any()
            },
            "mape_validation_pct": round(md.mape(truth, forecasts[name]), 4),
            "comparaisons_cumulees": count,
        }

    def compare(simple: str, complex_: str) -> md.PairedGap:
        return md.paired_gap(truth, forecasts[simple], forecasts[complex_], days, tb.VALIDATION[0])

    steps = []
    current = "A17"
    for challenger in ("C17", "B17"):
        gap = compare(current, challenger)
        steps.append({"decision": "source", **gap_record(gap, current, challenger)})
        if gap.complex_retained:
            current = challenger
    source = MODELS[current][0]
    if source == "B":
        retained = "B17"
        length_note = "source B : 2017 faute de données IFS avant"
    else:
        reference, candidate = f"{source}12", f"{source}17"
        gap = compare(reference, candidate)
        steps.append({"decision": "duree", **gap_record(gap, reference, candidate)})
        retained = candidate if gap.complex_retained else reference
        length_note = "2012 de référence ; 2017 seulement si la règle du test de bruit passe"

    scored = int(truth.notna().sum())
    summary = {
        "regle": "journal des choix, entrée 4",
        "validation": {
            "premier_jour": str(tb.VALIDATION[0]),
            "dernier_jour": str(tb.VALIDATION[1]),
            "demi_heures_jugees": scored,
            "blocs_de_7_jours": int(
                (pd.Timestamp(tb.VALIDATION[1]) - pd.Timestamp(tb.VALIDATION[0])).days // 7 + 1
            ),
            "tirages_bootstrap": md.REPLICATES,
            "graine": md.SEED,
        },
        "correction_C": correction_summary(era5, fixed, gaps),
        "modeles": models,
        "etapes": steps,
        "duree": length_note,
        "retenu": retained,
        "comparaisons_sur_la_validation_cumulees": len(MODELS),
    }
    SUMMARY.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {k: summary[k] for k in ("modeles", "etapes", "retenu")}, indent=2, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
