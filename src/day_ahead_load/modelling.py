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


# Test de bruit des comparaisons sur la validation (journal des choix, entrée 4).
BLOCK_DAYS = 7
REPLICATES = 10_000
MIN_RELATIVE_GAIN = 0.01


def validation_forecast(table: pd.DataFrame, train_first: date) -> tuple[pd.Series, int]:
    """Entraîne sur les jours livrés de `train_first` au 14/03/2024, prévoit la validation.

    Refuse une table qui contient des lignes du test ou au-delà.
    """
    if not table["periode"].isin(["entrainement", "validation"]).all():
        raise ValueError("comparaison réservée à l'entraînement et à la validation")
    day = pd.Series(pd.to_datetime(table["jour"]).to_numpy(), index=table.index)
    train = (
        (table["periode"] == "entrainement")
        & (day >= pd.Timestamp(train_first))
        & table[tb.TARGET].notna()
    )
    fitted = fit(design(table[train]), table.loc[train, tb.TARGET])
    validation = table[table["periode"] == "validation"]
    forecast = np.asarray(fitted.predict(design(validation)), dtype=float)
    return pd.Series(forecast, index=validation.index), int(train.sum())


@dataclass(frozen=True)
class PairedGap:
    """Option simple S contre option plus complexe K, sur les mêmes demi-heures."""

    simple_mape: float
    complex_mape: float
    difference: float  # MAPE(K) − MAPE(S), en points de pourcentage
    low: float
    high: float
    relative_gain: float  # (MAPE(S) − MAPE(K)) / MAPE(S)

    @property
    def complex_retained(self) -> bool:
        return self.relative_gain > MIN_RELATIVE_GAIN and self.high < 0


def paired_gap(
    truth: pd.Series,
    simple: np.ndarray,
    complex_: np.ndarray,
    days: pd.Series,
    first_day: date,
    replicates: int = REPLICATES,
    seed: int = SEED,
) -> PairedGap:
    """Différence appariée de MAPE, intervalle à 95 % par bootstrap par blocs de 7 jours livrés
    consécutifs à partir de `first_day`, tirés avec remise."""
    values = truth.to_numpy(dtype=float)
    keep = ~np.isnan(values)
    ape_s = np.abs(simple[keep] - values[keep]) / values[keep] * 100
    ape_k = np.abs(complex_[keep] - values[keep]) / values[keep] * 100
    offsets = (pd.to_datetime(days.to_numpy()[keep]) - pd.Timestamp(first_day)).days
    blocks = np.asarray(offsets, dtype=int) // BLOCK_DAYS
    if blocks.min() < 0:
        raise ValueError("jour antérieur au premier bloc")
    count = int(blocks.max()) + 1
    sums = np.bincount(blocks, weights=ape_k - ape_s, minlength=count)
    sizes = np.bincount(blocks, minlength=count).astype(float)
    draws = np.random.default_rng(seed).integers(0, count, size=(replicates, count))
    boot = sums[draws].sum(axis=1) / sizes[draws].sum(axis=1)
    low, high = np.percentile(boot, [2.5, 97.5])
    s, k = float(ape_s.mean()), float(ape_k.mean())
    return PairedGap(s, k, k - s, float(low), float(high), (s - k) / s)
