"""v0.1 : bilan du modèle retenu (A17) sur la validation, sans rien choisir.

Règle écrite avant le calcul (journal des choix, entrée 19). Le modèle est entraîné comme en
entrée 6 ; le script vérifie qu'il retrouve sa MAPE de 2,617 %. La table s'arrête au
31/08/2025 : le test n'est jamais lu. Ne lit que le cache local, aucun appel réseau. N'écrit
que des erreurs agrégées, jamais les séries, ni celles de RTE.

    uv run python scripts/modelling/assess_v0_1.py
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
from day_ahead_load import references as refs
from day_ahead_load import table as tb
from day_ahead_load import temperature_index as ti
from day_ahead_load import weather_features as wf
from day_ahead_load.weather_points import POINTS

ECO2MIX = Path("data/raw/eco2mix/2026-11-14")
WEATHER = Path("data/raw/meteo")
WEIGHTS = Path("docs/v0.0-faisabilite/data/indice-temperature-poids.json")
FAMILIES = Path("docs/v0.1-prevision-ponctuelle/data/comparaison-familles.json")
SUMMARY = Path("docs/v0.1-prevision-ponctuelle/data/bilan-v0-1.json")
FIRST_DAY = date(2012, 1, 1)
PARIS = "Europe/Paris"
NAIVE = "naif_j7"
THRESHOLDS = {"reussite_au_plus": 0.5, "echec_au_dessus_de": 0.75}
OPTIMISM = [
    "10 comparaisons faites sur cette période",
    "météo prévue rejouée (cycle 49R1)",
    "J-7 lui-même étiqueté « optimiste »",
]
COLD_HOT_GAP = 5.0  # °C, écart à la moyenne du mois civil sur l'entraînement 2017-2024
WEATHER_ERROR = 2.0  # °C, moyenne des écarts absolus du jour, prévue contre ERA5
WORST_DAYS = 10
DAY_TYPES = {0: "ouvre", 1: "samedi", 2: "dimanche_ou_ferie"}


def rounded(frame: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, row in frame.iterrows():
        out[str(key)] = {
            "demi_heures": int(row["demi_heures"]),
            "mape_pct": round(float(row["mape_pct"]), 3),
            "biais_mw": round(float(row["biais_mw"]), 1),
            "biais_pct": round(float(row["biais_pct"]), 3),
        }
    return out


def gap_record(gap: md.PairedGap) -> dict[str, Any]:
    return {
        "mape_reference_pct": round(gap.simple_mape, 3),
        "mape_modele_pct": round(gap.complex_mape, 3),
        "difference_modele_moins_reference_pts": round(gap.difference, 3),
        "intervalle_95_pts": [round(gap.low, 3), round(gap.high, 3)],
    }


def main() -> None:
    paths = [ECO2MIX / f"{name}.parquet" for name in eco2mix.DATASETS]
    instants, _ = diagnostics.with_local_instants(diagnostics.read_raw(paths))
    stored = json.loads(WEIGHTS.read_text(encoding="utf-8"))
    weights = ti.normalize(stored["resultats"]["consommation"]["poids_sur_2016_2023"])
    archive = wf.archive_index(WEATHER, "era5", POINTS, weights)
    runs = wf.runs_index(WEATHER, POINTS, weights)
    built = tb.build(instants, archive, runs, FIRST_DAY, tb.VALIDATION[1])
    table = built.table

    # Modèle retenu, entraîné comme en entrée 6.
    day = pd.Series(pd.to_datetime(table["jour"]).to_numpy(), index=table.index)
    train = table[
        (table["periode"] == "entrainement")
        & (day >= pd.Timestamp(md.TRAIN_FIRST))
        & table[tb.TARGET].notna()
    ]
    booster = md.fit(md.design(train), train[tb.TARGET])
    validation = table[(table["periode"] == "validation") & table[tb.TARGET].notna()]
    model = np.asarray(booster.predict(md.design(validation)), dtype=float)
    expected = json.loads(FAMILIES.read_text(encoding="utf-8"))["modeles"]["G-niveau"]
    if round(md.mape(validation[tb.TARGET], model), 4) != expected["mape_validation_pct"]:
        raise RuntimeError("le modèle ne retrouve pas la MAPE de A17")

    # Météo observée (ERA5) à la place de la prévision, lissages compris.
    observed = wf.half_hour_features(pd.DatetimeIndex(validation.index), archive)
    perfect_x = md.design(validation.drop(columns=observed.columns).join(observed))
    perfect = np.asarray(booster.predict(perfect_x), dtype=float)

    # Références de la v0.0 sur la grille en heure murale de Paris.
    wall = pd.DatetimeIndex(validation.index).tz_convert(PARIS).tz_localize(None)
    conso = refs.target_series(instants)
    if not np.allclose(conso.reindex(wall).to_numpy(), validation[tb.TARGET].to_numpy()):
        raise RuntimeError("cible du modèle et des références différentes")
    values = refs.compute(conso, refs.forecast_series(instants), wall)
    common = np.asarray(values.notna().all(axis=1)) & ~np.isnan(model)

    truth = validation[tb.TARGET].to_numpy(dtype=float)[common]
    days = list(validation["jour"].to_numpy()[common])
    first = tb.VALIDATION[0]
    forecast = model[common]
    rows = validation[common]

    def paired(other: np.ndarray) -> md.PairedGap:
        return md.paired_gap(pd.Series(truth), other, forecast, pd.Series(days), first)

    category = {r.name: r.category for r in refs.REFERENCES}
    references = {
        name: {"categorie": category[name], **gap_record(paired(values[name].to_numpy()[common]))}
        for name in values.columns
    }
    ratio, low, high = ass.ratio_interval(
        truth, forecast, values[NAIVE].to_numpy()[common], days, first
    )

    perfect_gap = md.paired_gap(pd.Series(truth), forecast, perfect[common], pd.Series(days), first)

    # Découpages.
    stamps = pd.to_datetime(rows["jour"])
    era5_temperature = observed.loc[rows.index, wf.TEMPERATURE].to_numpy()
    slot = rows["demi_heure"].to_numpy(dtype=int)
    groups = {
        "trimestre": [f"{d.year}-T{(d.month - 1) // 3 + 1}" for d in stamps],
        "saison": ass.season(stamps.dt.month.tolist()),
        "temperature_indice_era5": ass.temperature_band(era5_temperature),
        "tranche_3h": [f"{3 * (s // 6):02d}h-{3 * (s // 6) + 3:02d}h" for s in slot],
        "type_de_jour": [DAY_TYPES[int(k)] for k in md.day_type(rows)],
        "pont": ["pont" if p else "autre" for p in rows["pont"]],
        "noel": ["noel" if n else "autre" for n in rows["noel"]],
    }
    breakdowns = {k: rounded(ass.breakdown(truth, forecast, g)) for k, g in groups.items()}

    # Pires jours et constats vérifiables dans nos données.
    seen_temperature = rows[wf.TEMPERATURE].to_numpy()
    daily = pd.DataFrame(
        {
            "jour": days,
            "ape": ass.ape(truth, forecast),
            "ecart": forecast - truth,
            "t_era5": era5_temperature,
            "ecart_meteo": np.abs(seen_temperature - era5_temperature),
        }
    ).groupby("jour")
    per_day = daily.agg(
        mape_pct=("ape", "mean"),
        biais_mw=("ecart", "mean"),
        t_era5=("t_era5", "mean"),
        ecart_meteo=("ecart_meteo", "mean"),
    )
    training = table[(table["periode"] == "entrainement") & (day >= pd.Timestamp(md.TRAIN_FIRST))]
    train_daily = training.groupby("jour")[wf.TEMPERATURE].mean()
    normal = train_daily.groupby(pd.to_datetime(train_daily.index).month).mean()
    calendar = table.groupby("jour").agg(
        ferie=("ferie", "max"),
        lundi_pentecote=("lundi_pentecote", "max"),
        pont=("pont", "max"),
        noel=("noel", "max"),
        demi_heures=("demi_heure", "size"),
    )
    worst = []
    for jour, row in per_day.sort_values("mape_pct", ascending=False).head(WORST_DAYS).iterrows():
        facts = [
            label
            for label, flag in (
                ("férié", calendar.at[jour, "ferie"]),
                ("lundi de Pentecôte", calendar.at[jour, "lundi_pentecote"]),
                ("pont", calendar.at[jour, "pont"]),
                ("période de Noël", calendar.at[jour, "noel"]),
                ("changement d'heure", calendar.at[jour, "demi_heures"] != 48),
            )
            if flag
        ]
        month_normal = float(normal[pd.Timestamp(str(jour)).month])
        if row["t_era5"] < month_normal - COLD_HOT_GAP:
            facts.append("froid marqué")
        if row["t_era5"] > month_normal + COLD_HOT_GAP:
            facts.append("chaleur marquée")
        if row["ecart_meteo"] > WEATHER_ERROR:
            facts.append("erreur de la météo prévue")
        worst.append(
            {
                "jour": str(jour),
                "mape_pct": round(float(row["mape_pct"]), 3),
                "biais_mw": round(float(row["biais_mw"]), 1),
                "temperature_moyenne_era5": round(float(row["t_era5"]), 2),
                "moyenne_du_mois_entrainement": round(month_normal, 2),
                "ecart_absolu_moyen_meteo_prevue": round(float(row["ecart_meteo"]), 2),
                "constats": facts or ["cause non établie"],
            }
        )

    # Importance des variables.
    gain = booster.feature_importance(importance_type="gain")
    gain_share = {
        name: round(float(g / gain.sum()), 4)
        for name, g in sorted(zip(md.FEATURES, gain, strict=True), key=lambda p: -p[1])
    }
    x_common = md.design(rows)
    permutation = ass.permutation_importance(
        lambda x: np.asarray(booster.predict(x), dtype=float), x_common, truth
    )

    fallbacks = built.fallbacks
    summary = {
        "regle": "journal des choix, entrée 19 ; le bilan ne modifie pas le modèle",
        "modele": "A17 : LightGBM figé, niveau en variable, ERA5 à l'entraînement depuis 2017",
        "comparaisons_sur_la_validation": 10,
        "echantillon_commun": {
            "premier_jour": str(tb.VALIDATION[0]),
            "dernier_jour": str(tb.VALIDATION[1]),
            "demi_heures_avec_cible": len(validation),
            "demi_heures_jugees": int(common.sum()),
            "mape_modele_pct": round(float(ass.ape(truth, forecast).mean()), 3),
            "alignement_rte": "moyenne f(t-15), f(t)",
        },
        "rapport_au_naif_j7": {
            "etiquette": "indication sur la validation, pas le critère",
            "rapport": round(ratio, 3),
            "intervalle_95": [round(low, 3), round(high, 3)],
            "seuils_adr_0001": THRESHOLDS,
            "probablement_optimiste_car": OPTIMISM,
        },
        "references": references,
        "meteo_parfaite": {
            "etiquette": "borne informative, météo parfaite, impossible en pratique",
            "mape_meteo_prevue_pct": round(perfect_gap.simple_mape, 3),
            "mape_meteo_observee_era5_pct": round(perfect_gap.complex_mape, 3),
            "difference_observee_moins_prevue_pts": round(perfect_gap.difference, 3),
            "intervalle_95_pts": [round(perfect_gap.low, 3), round(perfect_gap.high, 3)],
        },
        "decoupages": breakdowns,
        "pires_jours": {
            "regle_des_constats": {
                "froid_ou_chaleur_marques_degres": COLD_HOT_GAP,
                "erreur_meteo_prevue_degres": WEATHER_ERROR,
                "erreur_meteo_prevue_mesure": "moyenne du jour des écarts absolus, prévue − ERA5",
            },
            "jours": worst,
        },
        "importance": {
            "gain_part": gain_share,
            "gain_reserve": "favorise les variables qui offrent beaucoup de coupures possibles",
            "permutation_hausse_mape_pts": {
                k: round(v, 4) for k, v in sorted(permutation.items(), key=lambda p: -p[1])
            },
            "permutation_reserve": (
                "mélanger une variable liée à d'autres (température et lissages) sous-estime "
                "son importance"
            ),
            "permutations_par_variable": ass.PERMUTATION_REPEATS,
        },
        "calcul_de_secours_validation": int((fallbacks["periode"] == "validation").sum()),
    }
    SUMMARY.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"bilan écrit dans {SUMMARY}")


if __name__ == "__main__":
    main()
