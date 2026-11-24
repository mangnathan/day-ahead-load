"""v0.2 : quantiles et intervalles autour de la prévision, sur la validation.

Règle écrite avant le calcul (journal des choix, entrée 21). Le réentraînement mensuel de
l'ADR 0001 est appliqué à la validation (18 modèles) ; les résidus de chaque mois calibrent les
jours suivants, avec la règle M+3. Trois candidats (Q1, Q2, Q3) et la référence J-7 de
l'ADR 0001 sont jugés sur les mêmes demi-heures. La table s'arrête au 31/08/2025 : le test
n'est jamais lu. Ne lit que le cache local, aucun appel réseau. N'écrit que des chiffres
agrégés, jamais les séries.

    uv run python scripts/modelling/compare_intervals.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from day_ahead_load import assessment as ass
from day_ahead_load import diagnostics, eco2mix
from day_ahead_load import modelling as md
from day_ahead_load import table as tb
from day_ahead_load import temperature_index as ti
from day_ahead_load import uncertainty as unc
from day_ahead_load import weather_features as wf
from day_ahead_load.weather_points import POINTS

ECO2MIX = Path("data/raw/eco2mix/2026-11-14")
WEATHER = Path("data/raw/meteo")
WEIGHTS = Path("docs/v0.0-faisabilite/data/indice-temperature-poids.json")
FAMILIES = Path("docs/v0.1-prevision-ponctuelle/data/comparaison-familles.json")
SUMMARY = Path("docs/v0.2-incertitude/data/intervalles.json")
FIRST_DAY = date(2012, 1, 1)
PARIS = "Europe/Paris"
EVALUATION_FIRST = date(2024, 9, 2)
ADVANTAGE = (date(2024, 3, 15), date(2024, 6, 30))
WINTER = (date(2024, 12, 1), date(2025, 2, 28))
FULL_WINDOW = (date(2025, 6, 1), date(2025, 8, 31))
REFERENCE_HISTORY_FIRST = date(2023, 1, 1)
PREVIOUS_COMPARISONS = 10
CANDIDATES = {
    "Q1": (unc.group_q1, None),
    "Q2": (unc.group_q2, None),
    "Q3": (unc.group_q3, unc.group_q2),
}
LABELS = [
    "météo prévue en partie rejouée",
    "période de validation déjà utilisée pour choisir A17 (10 comparaisons)",
    "fenêtre de calibration réduite avant juin 2025",
]


def between(days: pd.Series, period: tuple[date, date]) -> np.ndarray:
    d = pd.to_datetime(days)
    return np.asarray((d >= pd.Timestamp(period[0])) & (d <= pd.Timestamp(period[1])))


def interval_metrics(truth: np.ndarray, quantiles: pd.DataFrame) -> dict[str, Any]:
    return {
        "demi_heures": len(truth),
        "couverture_80_pct": round(float(unc.covered(truth, quantiles, "80").mean() * 100), 2),
        "couverture_95_pct": round(float(unc.covered(truth, quantiles, "95").mean() * 100), 2),
        "largeur_80_mw": round(float(unc.width(quantiles, "80").mean()), 1),
        "largeur_95_mw": round(float(unc.width(quantiles, "95").mean()), 1),
        "pinball_moyen_mw": round(float(unc.mean_pinball(truth, quantiles).mean()), 2),
        "pinball_par_niveau_mw": {
            str(lv): round(float(unc.pinball(truth, quantiles[str(lv)].to_numpy(), lv).mean()), 2)
            for lv in unc.LEVELS
        },
    }


def by_group(truth: np.ndarray, quantiles: pd.DataFrame, labels: list[str]) -> dict[str, Any]:
    key = np.asarray(labels)
    return {
        str(g): interval_metrics(truth[key == g], quantiles[key == g]) for g in sorted(set(labels))
    }


def gap_record(gap: md.PairedGap, simple: str, complex_: str) -> dict[str, Any]:
    return {
        "retenu_jusque_la": simple,
        "candidat": complex_,
        "pinball_retenu_mw": round(gap.simple_mape, 2),
        "pinball_candidat_mw": round(gap.complex_mape, 2),
        "difference_candidat_moins_retenu_mw": round(gap.difference, 2),
        "intervalle_95_mw": [round(gap.low, 2), round(gap.high, 2)],
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

    # Lignes d'entraînement : ERA5 partout, y compris sur les jours de validation déjà passés.
    observed = wf.half_hour_features(pd.DatetimeIndex(validation.index), archive)
    train_table = table.copy()
    train_table.loc[validation.index, list(observed.columns)] = observed.to_numpy()

    # A17 figé, entraîné une fois jusqu'au 14/03/2024 : il doit retrouver sa MAPE.
    static_rows = train_table[
        (train_table["periode"] == "entrainement")
        & (pd.to_datetime(train_table["jour"]) >= pd.Timestamp(md.TRAIN_FIRST))
        & train_table[tb.TARGET].notna()
    ]
    static_model = md.fit(md.design(static_rows), static_rows[tb.TARGET])
    static = pd.Series(
        np.asarray(static_model.predict(md.design(validation)), dtype=float),
        index=validation.index,
    )
    expected = json.loads(FAMILIES.read_text(encoding="utf-8"))["modeles"]["G-niveau"]
    if (
        round(md.mape(validation[tb.TARGET], static.to_numpy()), 4)
        != (expected["mape_validation_pct"])
    ):
        raise RuntimeError("A17 figé ne retrouve pas sa MAPE de la v0.1")

    # Procédure mensuelle : 18 modèles, chacun prévoit son mois.
    monthly = pd.Series(np.nan, index=validation.index)
    trace = []
    month_of = pd.to_datetime(validation["jour"]).dt.to_period("M")
    for period in pd.period_range("2024-03", "2025-08", freq="M"):
        month = period.start_time.date()
        model = md.fit_monthly(md.monthly_training_rows(train_table, month), month)
        rows = validation[np.asarray(month_of == period)]
        monthly[rows.index] = np.asarray(model.booster.predict(md.design(rows)), dtype=float)
        trace.append(
            {
                "mois": str(period),
                "derniere_ligne_entrainement": str(model.last_training_day),
                "fin_autorisee": str(md.training_cutoff(month)),
                "lignes": model.rows,
                "sha256_configuration": model.config_sha256,
            }
        )
    if monthly.isna().any():
        raise RuntimeError("jour de validation sans prévision mensuelle")

    known = validation[tb.TARGET].notna()
    rows = validation[known]
    truth_all = rows[tb.TARGET].to_numpy(dtype=float)
    residuals = rows[tb.TARGET] - monthly[rows.index]

    calibrated = {
        name: unc.calibrate(monthly[rows.index], rows, residuals, rows, grouping, parent)
        for name, (grouping, parent) in CANDIDATES.items()
    }

    # Référence J-7 : erreurs de J-7 sur les jours publiés, dès 2023.
    with_target = table[table[tb.TARGET].notna()]
    wall_all = pd.DatetimeIndex(with_target.index).tz_convert(PARIS).tz_localize(None)
    by_wall = pd.Series(with_target[tb.TARGET].to_numpy(dtype=float), index=wall_all)
    by_wall = by_wall[~by_wall.index.duplicated(keep=False)]
    history = with_target[
        pd.to_datetime(with_target["jour"]) >= pd.Timestamp(REFERENCE_HISTORY_FIRST)
    ]
    history_wall = pd.DatetimeIndex(history.index).tz_convert(PARIS).tz_localize(None)
    j7_history = pd.Series(unc.j7_point(by_wall, history_wall), index=history.index)
    j7_errors = (history[tb.TARGET] - j7_history).dropna()
    rows_wall = pd.DatetimeIndex(rows.index).tz_convert(PARIS).tz_localize(None)
    j7_point = pd.Series(unc.j7_point(by_wall, rows_wall), index=rows.index)
    reference = unc.calibrate(j7_point, rows, j7_errors, history.loc[j7_errors.index], unc.group_q1)

    # Demi-heures jugées : communes aux candidats et à la référence.
    judged = np.asarray(calibrated["Q1"].judged) & np.asarray(reference.judged)
    for cal in (*calibrated.values(), reference):
        judged &= np.asarray(cal.quantiles.notna().all(axis=1))
    first_judged = min(rows.loc[judged, "jour"])
    if first_judged != EVALUATION_FIRST:
        raise RuntimeError(f"premier jour jugé {first_judged}, attendu {EVALUATION_FIRST}")
    ev = rows[judged]
    truth = truth_all[judged]
    days = ev["jour"].to_numpy()
    quantiles = {name: cal.quantiles[judged] for name, cal in calibrated.items()}
    quantiles["reference_j7"] = reference.quantiles[judged]

    seasons = ass.season(pd.to_datetime(ev["jour"]).dt.month.tolist())
    slot = ev["demi_heure"].to_numpy(dtype=int)
    slices = [f"{3 * (s // 6):02d}h-{3 * (s // 6) + 3:02d}h" for s in slot]
    outside_winter = ~between(ev["jour"], WINTER)
    full_window = between(ev["jour"], FULL_WINDOW)

    results: dict[str, Any] = {}
    for name, q in quantiles.items():
        overall = interval_metrics(truth, q)
        median = q["0.5"].to_numpy()
        results[name] = {
            "evaluation": overall,
            "admissible": unc.admissible(
                overall["couverture_80_pct"], overall["couverture_95_pct"]
            ),
            "par_saison": by_group(truth, q, seasons),
            "par_tranche_3h": by_group(truth, q, slices),
            "hors_hiver_2024_25_information": interval_metrics(
                truth[outside_winter], q[outside_winter]
            ),
            "juin_aout_2025_fenetre_complete_information": interval_metrics(
                truth[full_window], q[full_window]
            ),
            "mediane_information": {
                "biais_mw": round(float((median - truth).mean()), 1),
                "mape_pct": round(float(ass.ape(truth, median).mean()), 3),
            },
        }
        if name == "Q3":
            fb = pd.DataFrame(
                calibrated[name].fallbacks, columns=["mois_decision", "groupe", "position"]
            )
            fb = fb[judged[fb["position"].to_numpy(dtype=int)]]
            results[name]["repli_vers_q2"] = {
                "couples_mois_de_decision_groupe": int(
                    fb[["mois_decision", "groupe"]].drop_duplicates().shape[0]
                ),
                "demi_heures_jugees_concernees": len(fb),
            }

    # Règle de décision : admissibilité, puis pinball avec le test de bruit.
    order = [name for name in CANDIDATES if results[name]["admissible"]]
    steps = []
    losses = {name: unc.mean_pinball(truth, q) for name, q in quantiles.items()}
    retained = None
    for name in order:
        if retained is None:
            retained = name
            continue
        gap = md.paired_loss_gap(losses[retained], losses[name], days, EVALUATION_FIRST)
        steps.append(gap_record(gap, retained, name))
        if gap.complex_retained:
            retained = name
    versus_reference = None
    if retained is not None:
        gap = md.paired_loss_gap(losses["reference_j7"], losses[retained], days, EVALUATION_FIRST)
        versus_reference = {
            "etiquette": "indication sur la validation, pas le critère",
            **gap_record(gap, "reference_j7", retained),
        }

    # MAPE d'A17 figé et de la procédure mensuelle, pour information.
    static_known = static[rows.index].to_numpy()
    monthly_known = monthly[rows.index].to_numpy()

    def mape_pair(mask: np.ndarray, first: date) -> dict[str, Any]:
        gap = md.paired_gap(
            pd.Series(truth_all[mask]),
            static_known[mask],
            monthly_known[mask],
            pd.Series(rows.loc[mask, "jour"].to_numpy()),
            first,
        )
        return {
            "demi_heures": int(mask.sum()),
            "mape_a17_fige_pct": round(gap.simple_mape, 3),
            "mape_mensuelle_pct": round(gap.complex_mape, 3),
            "difference_mensuelle_moins_fige_pts": round(gap.difference, 3),
            "intervalle_95_pts": [round(gap.low, 3), round(gap.high, 3)],
        }

    everything = np.ones(len(rows), dtype=bool)
    summary = {
        "regle": "journal des choix, entrée 21",
        "etiquettes": LABELS,
        "reference_avantage": (
            "la référence J-7 dispose d'emblée de 12 mois d'erreurs, sans attendre la météo "
            "prévue : elle est avantagée au début de l'évaluation"
        ),
        "evaluation": {
            "premier_jour": str(EVALUATION_FIRST),
            "dernier_jour": str(tb.VALIDATION[1]),
            "demi_heures_jugees": int(judged.sum()),
            "jours_de_residus_min_max": [
                int(calibrated["Q1"].residual_days[judged].min()),
                int(calibrated["Q1"].residual_days[judged].max()),
            ],
        },
        "procedure_mensuelle": {
            "modeles": trace,
            "mape_information": {
                "toute_la_validation": mape_pair(everything, tb.VALIDATION[0]),
                "evaluation": mape_pair(judged, EVALUATION_FIRST),
                "avantage_de_date_15_03_au_30_06_2024": mape_pair(
                    between(rows["jour"], ADVANTAGE), ADVANTAGE[0]
                ),
            },
        },
        "candidats_et_reference": results,
        "admissibles": order,
        "etapes": steps,
        "retenu": retained,
        "retenu_face_a_la_reference": versus_reference,
        "comparaisons_sur_la_validation_cumulees": PREVIOUS_COMPARISONS + len(CANDIDATES),
    }
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"retenu : {retained} ; détail dans {SUMMARY}")


if __name__ == "__main__":
    main()
