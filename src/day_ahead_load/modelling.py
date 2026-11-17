"""Modèle figé des comparaisons de la v0.1 (journal des choix, entrée 1).

LightGBM aux réglages par défaut, graine et exécution déterministe fixées. Il ne change pas
d'une comparaison à l'autre : seules les entrées changent (convention, source météo, niveau).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import lightgbm as lgb
import numpy as np
import pandas as pd

from day_ahead_load import table as tb

SEED = 20261117
FEATURES = (
    "demi_heure",
    "jour_semaine",
    "mois",
    "ferie",
    "lundi_pentecote",
    "pont",
    "noel",
    "temperature_2m",
    "cloud_cover",
    "wind_speed_10m",
    "shortwave_radiation",
    "temperature_lissee_24h",
    "temperature_lissee_72h",
    tb.LEVEL,
)
HELD_OUT_YEARS = (2019, 2020, 2021, 2022, 2023)


# Interface native de LightGBM (l'interface scikit-learn demanderait scikit-learn) : réglages
# par défaut, objectif de régression, 100 itérations. Seules la graine, l'exécution
# déterministe et le nombre de fils sont fixés.
PARAMS = {
    "objective": "regression",
    "seed": SEED,
    "deterministic": True,
    "force_row_wise": True,
    "num_threads": 1,
    "verbose": -1,
}
ROUNDS = 100


def fit(x: pd.DataFrame, y: pd.Series) -> lgb.Booster:
    return lgb.train(PARAMS, lgb.Dataset(x, label=y), num_boost_round=ROUNDS)


def design(table: pd.DataFrame, features: Sequence[str] = FEATURES) -> pd.DataFrame:
    return table[list(features)].astype(float)


def mape(truth: pd.Series, forecast: np.ndarray) -> float:
    """Erreur absolue moyenne en pourcentage, sur les demi-heures où la cible existe."""
    values = truth.to_numpy(dtype=float)
    keep = ~np.isnan(values)
    return float(np.mean(np.abs(forecast[keep] - values[keep]) / values[keep]) * 100)


@dataclass(frozen=True)
class FoldResult:
    year: int
    train_rows: int
    scored_rows: int
    mape_pct: float


def cross_validate(table: pd.DataFrame, years: Sequence[int] = HELD_OUT_YEARS) -> list[FoldResult]:
    """Chaque année mise de côté à tour de rôle, entraînement sur tous les jours antérieurs.

    Refuse toute ligne hors entraînement : cette mesure ne touche jamais la validation.
    """
    if (table["periode"] != "entrainement").any():
        raise ValueError("validation croisée réservée à l'entraînement")
    known = table.dropna(subset=[tb.TARGET])
    day = pd.to_datetime(pd.Series(known["jour"].to_numpy(), index=known.index))
    out = []
    for year in years:
        start = pd.Timestamp(date(year, 1, 1))
        before = np.asarray(day < start)
        held = np.asarray((day >= start) & (day < pd.Timestamp(date(year + 1, 1, 1))))
        fitted = fit(design(known[before]), known.loc[before, tb.TARGET])
        forecast = np.asarray(fitted.predict(design(known[held])), dtype=float)
        out.append(
            FoldResult(
                year, int(before.sum()), int(held.sum()), mape(known.loc[held, tb.TARGET], forecast)
            )
        )
    return out
