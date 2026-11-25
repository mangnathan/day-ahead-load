"""v0.3 : quantile d'achat du vendeur de journaux et coût des écarts, sur la validation.

Règles écrites avant le calcul (journal des choix, entrées 24 et 25). La prévision ponctuelle
est la procédure mensuelle de la v0.2 : le script vérifie qu'il retrouve sa MAPE de 2,667 %.
Les quantiles suivent Q1 (entrée 21). Les prix des écarts viennent du cache d'ENTSO-E. La
table s'arrête au 31/08/2025 : la cible du test n'est jamais lue. N'écrit que des chiffres
agrégés, jamais les séries.

    uv run python scripts/decision/compute_purchase.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from day_ahead_load import decision as dec
from day_ahead_load import diagnostics, eco2mix, entsoe
from day_ahead_load import modelling as md
from day_ahead_load import table as tb
from day_ahead_load import temperature_index as ti
from day_ahead_load import uncertainty as unc
from day_ahead_load import weather_features as wf
from day_ahead_load.weather_points import POINTS

ECO2MIX = Path("data/raw/eco2mix/2026-11-14")
WEATHER = Path("data/raw/meteo")
PRICES = Path("data/raw/entsoe/prix-des-ecarts")
WEIGHTS = Path("docs/v0.0-faisabilite/data/indice-temperature-poids.json")
INTERVALS = Path("docs/v0.2-incertitude/data/intervalles.json")
SUMMARY = Path("docs/v0.3-decision/data/decision-achat.json")
FIRST_DAY = date(2012, 1, 1)
ESTIMATION = (date(2025, 1, 1), date(2025, 8, 31))
REFERENCE = 61.1
SENSITIVITY = (40.0, 100.0)
SHARE = 0.01
CURVE = tuple(round(0.05 * k, 2) for k in range(1, 20))
LABELS = [
    "météo prévue en partie rejouée",
    "période de validation déjà utilisée pour choisir A17 et Q1 (13 comparaisons)",
    "q estimé et jugé sur la même période : indication optimiste",
]


def between(days: pd.Series, period: tuple[date, date]) -> np.ndarray:
    d = pd.to_datetime(days)
    return np.asarray((d >= pd.Timestamp(period[0])) & (d <= pd.Timestamp(period[1])))


def missing_quarters(grid: pd.DataFrame, first: date, last: date) -> dict[str, Any]:
    """Quarts d'heure sans prix pour les demi-heures des jours livrés de `first` à `last`."""
    halves = tb.half_hour_grid(first, last)
    a, b = dec.half_hour_quarters(pd.DatetimeIndex(halves.index))
    starts = a.append(b)
    days = np.concatenate([halves["jour"].to_numpy(), halves["jour"].to_numpy()])
    absent = ~starts.isin(grid.index)
    dates = sorted({str(d) for d in days[absent]})
    return {"quarts_d_heure": int(absent.sum()), "sur": len(starts), "jours": dates}


def costs_for(quarters: pd.DataFrame, purchase: str, reference: float) -> np.ndarray:
    return dec.cost(
        quarters["consommation"].to_numpy(),
        quarters[purchase].to_numpy(),
        quarters[dec.LONG].to_numpy(),
        quarters[dec.SHORT].to_numpy(),
        reference,
        SHARE,
    )


def strategy_record(cost: np.ndarray, consumed_mwh: float) -> dict[str, Any]:
    return {
        "cout_total_eur_pour_s_1pct": round(float(cost.sum()), 0),
        "cout_eur_par_mwh_consomme": round(float(cost.sum() / consumed_mwh), 4),
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
    observed = wf.half_hour_features(pd.DatetimeIndex(validation.index), archive)
    train_table = table.copy()
    train_table.loc[validation.index, list(observed.columns)] = observed.to_numpy()

    # Prévision ponctuelle : procédure mensuelle de la v0.2, qui doit retrouver sa MAPE.
    monthly = pd.Series(np.nan, index=validation.index)
    month_of = pd.to_datetime(validation["jour"]).dt.to_period("M")
    for period in pd.period_range("2024-03", "2025-08", freq="M"):
        month = period.start_time.date()
        model = md.fit_monthly(md.monthly_training_rows(train_table, month), month)
        part = validation[np.asarray(month_of == period)]
        monthly[part.index] = np.asarray(model.booster.predict(md.design(part)), dtype=float)
    expected = json.loads(INTERVALS.read_text(encoding="utf-8"))["procedure_mensuelle"]
    official = expected["mape_information"]["toute_la_validation"]["mape_mensuelle_pct"]
    if round(md.mape(validation[tb.TARGET], monthly.to_numpy()), 3) != official:
        raise RuntimeError("la procédure mensuelle ne retrouve pas sa MAPE de la v0.2")

    rows = validation[validation[tb.TARGET].notna()]
    residuals = rows[tb.TARGET] - monthly[rows.index]

    # Prix au quart d'heure.
    raw = pd.concat(
        [entsoe.parse_prices(p.read_bytes()) for p in sorted(PRICES.glob("prix-ecarts-*.bin"))]
    ).sort_index()
    grid = dec.quarter_prices(raw)

    # q sur la période d'estimation, formule B, et sensibilité au prix de référence.
    est = rows[between(rows["jour"], ESTIMATION)].copy()
    est["consommation"] = est[tb.TARGET]
    est["prevision"] = monthly[est.index]
    base = dec.expand(est, grid, ["consommation", "prevision"])
    error = (base.frame["consommation"] - base.frame["prevision"]).to_numpy()
    long_p, short_p = base.frame[dec.LONG].to_numpy(), base.frame[dec.SHORT].to_numpy()
    penalties = {
        ref: dec.penalties_by_sign(error, long_p, short_p, ref) for ref in (REFERENCE, *SENSITIVITY)
    }
    quantiles = {ref: pen.quantile for ref, pen in penalties.items()}

    # Quantiles d'achat (Q1) aux niveaux utiles, sur les demi-heures de la période d'estimation.
    levels = sorted({*CURVE, 0.5, *(q for q in quantiles.values() if q is not None)})
    calibrated = unc.calibrate(
        monthly[est.index], est, residuals, rows, unc.group_q1, levels=levels
    )
    if not calibrated.judged.all():
        raise RuntimeError("jour de la période d'estimation sans fenêtre de résidus suffisante")
    q_table = calibrated.quantiles
    purchases = est[["jour", "consommation", "prevision"]].copy()
    for level in levels:
        purchases[f"q{level}"] = q_table[str(level)]
    expanded = dec.expand(purchases, grid, [c for c in purchases.columns if c != "jour"])
    quarters = expanded.frame
    if len(quarters) != len(base.frame):
        raise RuntimeError("les deux stratégies ne portent pas sur les mêmes quarts d'heure")
    consumed = float(dec.energy(quarters["consommation"].to_numpy(), SHARE).sum())
    days = quarters["jour"].to_numpy()

    def compare(ref: float) -> dict[str, Any]:
        q = quantiles[ref]
        pen = penalties[ref]
        record: dict[str, Any] = {
            "prix_de_reference_eur_mwh": ref,
            "penalite_courte_cu": round(pen.short, 3),
            "penalite_longue_co": round(pen.long, 3),
            "quarts_d_heure_courts": pen.short_periods,
            "quarts_d_heure_longs": pen.long_periods,
            "q": None if q is None else round(q, 4),
        }
        point_cost = costs_for(quarters, "prevision", ref)
        record["achat_prevision_ponctuelle"] = strategy_record(point_cost, consumed)
        if q is None:
            record["regle"] = "Cu ou Co non positif : achat à la prévision ponctuelle"
            return record
        q_cost = costs_for(quarters, f"q{q}", ref)
        gap = md.paired_loss_gap(point_cost, q_cost, days, ESTIMATION[0])
        record["achat_au_quantile_q"] = strategy_record(q_cost, consumed)
        record["difference_quantile_moins_prevision_eur"] = round(
            float(q_cost.sum() - point_cost.sum()), 0
        )
        record["difference_par_quart_d_heure_ic95_eur"] = [
            round(gap.difference, 4),
            round(gap.low, 4),
            round(gap.high, 4),
        ]
        record["quantile_moins_cher"] = bool(gap.high < 0)
        return record

    results = {str(ref): compare(ref) for ref in (REFERENCE, *SENSITIVITY)}

    # Information, sans choix possible.
    q_main = quantiles[REFERENCE]
    halves = est.index
    info: dict[str, Any] = {}
    formula_a = dec.penalties_all(long_p, short_p, REFERENCE)
    info["formule_a"] = {
        "penalite_courte": round(formula_a.short, 3),
        "penalite_longue": round(formula_a.long, 3),
        "q": None if formula_a.quantile is None else round(formula_a.quantile, 4),
    }
    info["courbe_du_cout_n_est_pas_une_option"] = {
        str(level): strategy_record(costs_for(quarters, f"q{level}", REFERENCE), consumed)
        for level in CURVE
    }
    if q_main is not None:
        achat = q_table[str(q_main)].to_numpy()
        info["couverture_empirique_de_q_pct"] = round(
            float((est["consommation"].to_numpy() <= achat).mean() * 100), 2
        )
        bias = float((q_table["0.5"].to_numpy() - est["consommation"].to_numpy()).mean())
        quarters_shift = quarters.copy()
        quarters_shift["corrige"] = quarters[f"q{q_main}"] - bias
        info["biais"] = {
            "etiquette": "borne informative, biais connu après coup, impossible en pratique",
            "biais_moyen_de_q05_mw": round(bias, 1),
            "achat_au_quantile_q_moins_le_biais": strategy_record(
                costs_for(quarters_shift, "corrige", REFERENCE), consumed
            ),
        }
    monthly_q = {}
    month_q = pd.to_datetime(base.frame["jour"]).dt.to_period("M").astype(str).to_numpy()
    for m in sorted(set(month_q)):
        sel = month_q == m
        monthly_q[m] = dec.penalties_by_sign(
            error[sel], long_p[sel], short_p[sel], REFERENCE
        ).quantile
    info["q_par_mois"] = {m: None if q is None else round(q, 4) for m, q in monthly_q.items()}
    full = rows.copy()
    full["consommation"] = full[tb.TARGET]
    full["prevision"] = monthly[full.index]
    whole = dec.expand(full, grid, ["consommation", "prevision"]).frame
    whole_pen = dec.penalties_by_sign(
        (whole["consommation"] - whole["prevision"]).to_numpy(),
        whole[dec.LONG].to_numpy(),
        whole[dec.SHORT].to_numpy(),
        REFERENCE,
    )
    info["q_toute_la_validation"] = (
        None if whole_pen.quantile is None else round(whole_pen.quantile, 4)
    )

    summary = {
        "regle": "journal des choix, entrées 24 et 25",
        "etiquettes": LABELS,
        "source_des_prix": (
            "ENTSO-E Transparency Platform, Imbalance Prices [17.1.G], France, CC BY 4.0"
        ),
        "part_de_marche": SHARE,
        "periode_d_estimation": {
            "premier_jour": str(ESTIMATION[0]),
            "dernier_jour": str(ESTIMATION[1]),
            "demi_heures": len(halves),
            "quarts_d_heure_juges": len(quarters),
            "energie_consommee_mwh_pour_s_1pct": round(consumed, 0),
        },
        "periodes_sans_prix": {
            "estimation": missing_quarters(grid, *ESTIMATION),
            "validation": missing_quarters(grid, *tb.VALIDATION),
            "test": missing_quarters(grid, *tb.TEST),
        },
        "resultats": results,
        "information": info,
        "comparaisons_sur_la_validation": 13,
    }
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"q = {results[str(REFERENCE)]['q']} ; détail dans {SUMMARY}")


if __name__ == "__main__":
    main()
