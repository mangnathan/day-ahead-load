"""Modèle figé des comparaisons de la v0.1 (journal des choix, entrée 1).

LightGBM aux réglages par défaut, graine et exécution déterministe fixées. Il ne change pas
d'une comparaison à l'autre : seules les entrées changent (convention, source météo, niveau).
"""

from __future__ import annotations

import hashlib
import json
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
    return paired_loss_gap(ape_s, ape_k, days.to_numpy()[keep], first_day, replicates, seed)


def paired_loss_gap(
    simple: np.ndarray,
    complex_: np.ndarray,
    days: np.ndarray,
    first_day: date,
    replicates: int = REPLICATES,
    seed: int = SEED,
) -> PairedGap:
    """Même test pour toute perte par demi-heure (erreur en %, pinball…) : les champs de
    PairedGap portent alors la perte moyenne de chaque option, dans son unité."""
    offsets = (pd.to_datetime(days) - pd.Timestamp(first_day)).days
    blocks = np.asarray(offsets, dtype=int) // BLOCK_DAYS
    if blocks.min() < 0:
        raise ValueError("jour antérieur au premier bloc")
    count = int(blocks.max()) + 1
    sums = np.bincount(blocks, weights=complex_ - simple, minlength=count)
    sizes = np.bincount(blocks, minlength=count).astype(float)
    draws = np.random.default_rng(seed).integers(0, count, size=(replicates, count))
    boot = sums[draws].sum(axis=1) / sizes[draws].sum(axis=1)
    low, high = np.percentile(boot, [2.5, 97.5])
    s, k = float(simple.mean()), float(complex_.mean())
    return PairedGap(s, k, k - s, float(low), float(high), (s - k) / s)


# Familles et variantes du niveau (journal des choix, entrée 12).
TRAIN_FIRST = date(2017, 1, 1)
HEATING_BASE = 15.0  # °C, sensibilité mesurée sous 15 °C en v0.0
COOLING_BASE = 18.0  # °C, fixé a priori, sans mesure
SLICE_HALF_HOURS = 6  # tranches horaires de 3 h
FAMILIES = ("lineaire", "lightgbm")
LEVEL_VARIANTS = ("sans", "niveau", "rapport")
WORKING, SATURDAY, SUNDAY_OR_HOLIDAY = 0, 1, 2
SMOOTHED = ("temperature_lissee_24h", "temperature_lissee_72h")
RAW_LINEAR = ("cloud_cover", "wind_speed_10m", "shortwave_radiation")


def day_type(table: pd.DataFrame) -> np.ndarray:
    """Ouvré, samedi, dimanche ou férié. Le lundi de Pentecôte reste un jour ouvré."""
    weekday = table["jour_semaine"].to_numpy()
    holiday = table["ferie"].to_numpy(dtype=bool)
    return np.where(
        holiday | (weekday == 6), SUNDAY_OR_HOLIDAY, np.where(weekday == 5, SATURDAY, WORKING)
    )


def _linear_inputs(with_level: bool) -> list[str]:
    inputs = ["temperature_2m", *SMOOTHED, *RAW_LINEAR]
    return [*inputs, tb.LEVEL] if with_level else inputs


def linear_design(table: pd.DataFrame, means: pd.Series) -> pd.DataFrame:
    """Matrice de la régression : constante, profil, calendrier, degrés croisés (entrée 12).

    `means` : moyennes de l'entraînement, qui remplacent les entrées manquantes ; leur index
    dit aussi si le niveau entre dans la matrice.
    """
    raw = table[list(means.index)].astype(float).fillna(means)
    slot = table["demi_heure"].to_numpy(dtype=int)
    kind = day_type(table)
    weekday = table["jour_semaine"].to_numpy(dtype=int)
    month = table["mois"].to_numpy(dtype=int)
    columns: dict[str, np.ndarray] = {"constante": np.ones(len(table))}
    for s in range(48):
        for k in (WORKING, SATURDAY, SUNDAY_OR_HOLIDAY):
            if (s, k) != (0, WORKING):
                columns[f"profil_{s:02d}_{k}"] = ((slot == s) & (kind == k)).astype(float)
    for d in range(1, 7):
        columns[f"jour_semaine_{d}"] = (weekday == d).astype(float)
    for m in range(2, 13):
        columns[f"mois_{m:02d}"] = (month == m).astype(float)
    for flag in ("ferie", "lundi_pentecote", "pont", "noel"):
        columns[flag] = table[flag].to_numpy(dtype=float)
    temperature = raw["temperature_2m"].to_numpy()
    heating = np.maximum(HEATING_BASE - temperature, 0.0)
    cooling = np.maximum(temperature - COOLING_BASE, 0.0)
    band = slot // SLICE_HALF_HOURS
    for b in range(48 // SLICE_HALF_HOURS):
        columns[f"chauffage_tranche_{b}"] = heating * (band == b)
        columns[f"climatisation_tranche_{b}"] = cooling * (band == b)
    for m in range(2, 13):
        columns[f"chauffage_mois_{m:02d}"] = heating * (month == m)
    for name in SMOOTHED:
        values = raw[name].to_numpy()
        columns[f"chauffage_{name}"] = np.maximum(HEATING_BASE - values, 0.0)
        columns[f"climatisation_{name}"] = np.maximum(values - COOLING_BASE, 0.0)
    for name in RAW_LINEAR:
        columns[name] = raw[name].to_numpy()
    if tb.LEVEL in means.index:
        columns[tb.LEVEL] = raw[tb.LEVEL].to_numpy()
    return pd.DataFrame(columns, index=table.index)


@dataclass(frozen=True)
class GridResult:
    forecast: pd.Series
    train_rows: int
    columns: int | None  # régression linéaire seulement
    rank: int | None


def grid_forecast(
    table: pd.DataFrame, family: str, level: str, train_first: date = TRAIN_FIRST
) -> GridResult:
    """Entraîne une case de la grille (famille × niveau) et prévoit la validation.

    Rapport : la cible est consommation / niveau, sans le niveau en entrée ; la prévision est
    remultipliée par le niveau du jour livré. Refuse les lignes du test ou au-delà.
    """
    if family not in FAMILIES or level not in LEVEL_VARIANTS:
        raise ValueError(f"case inconnue : {family}, {level}")
    if not table["periode"].isin(["entrainement", "validation"]).all():
        raise ValueError("comparaison réservée à l'entraînement et à la validation")
    day = pd.Series(pd.to_datetime(table["jour"]).to_numpy(), index=table.index)
    train_mask = (
        (table["periode"] == "entrainement")
        & (day >= pd.Timestamp(train_first))
        & table[tb.TARGET].notna()
    )
    train = table[train_mask]
    validation = table[table["periode"] == "validation"]
    target = train[tb.TARGET].astype(float)
    if level == "rapport":
        target = target / train[tb.LEVEL].astype(float)
    with_level = level == "niveau"
    columns = rank = None
    if family == "lightgbm":
        features = [f for f in FEATURES if with_level or f != tb.LEVEL]
        fitted = fit(design(train, features), target)
        forecast = np.asarray(fitted.predict(design(validation, features)), dtype=float)
    else:
        means = train[_linear_inputs(with_level)].astype(float).mean()
        x = linear_design(train, means).to_numpy()
        coef, _, rank, _ = np.linalg.lstsq(x, target.to_numpy(), rcond=None)
        columns = x.shape[1]
        forecast = linear_design(validation, means).to_numpy() @ coef
    if level == "rapport":
        forecast = forecast * validation[tb.LEVEL].to_numpy(dtype=float)
    return GridResult(
        pd.Series(forecast, index=validation.index),
        len(train),
        columns,
        None if rank is None else int(rank),
    )


# Réentraînement mensuel (ADR 0001), appliqué à la validation en v0.2 (journal, entrée 21).


def training_cutoff(month: date) -> date:
    """Dernier jour livré que le modèle du mois M peut apprendre : la fin du mois M − 4.

    Le modèle doit exister à midi la veille du 1er de M, soit le dernier jour de M − 1 ; le
    consolidé publié s'arrête alors à la fin de M − 4 (le mois M − 3 paraît le 1er de M).
    """
    first_unpublished = (pd.Period(month, "M") - 3).start_time
    return (first_unpublished - pd.Timedelta(days=1)).date()


def config_sha256() -> str:
    """Empreinte de la configuration figée, identique pour chaque modèle mensuel."""
    config = {
        "params": PARAMS,
        "rounds": ROUNDS,
        "features": list(FEATURES),
        "train_first": str(TRAIN_FIRST),
        "lightgbm": lgb.__version__,
    }
    text = json.dumps(config, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MonthlyModel:
    month: date
    last_training_day: date
    rows: int
    config_sha256: str
    booster: lgb.Booster


def monthly_training_rows(table: pd.DataFrame, month: date) -> pd.DataFrame:
    """Lignes d'entraînement du modèle du mois M : jours livrés du 01/01/2017 à la fin de M − 4,
    cible connue. Refuse toute ligne du test ou au-delà."""
    if not table["periode"].isin(["entrainement", "validation"]).all():
        raise ValueError("entraînement réservé aux lignes d'entraînement et de validation")
    day = pd.to_datetime(table["jour"])
    keep = (
        (day >= pd.Timestamp(TRAIN_FIRST))
        & (day <= pd.Timestamp(training_cutoff(month)))
        & table[tb.TARGET].notna()
    )
    return table[keep]


def fit_monthly(rows: pd.DataFrame, month: date) -> MonthlyModel:
    """Entraîne le modèle du mois M. Échoue si une ligne est postérieure à la fin de M − 4."""
    cutoff = training_cutoff(month)
    last = max(rows["jour"])
    if last > cutoff:
        raise ValueError(f"ligne d'entraînement du {last}, après la fin de M − 4 ({cutoff})")
    booster = fit(design(rows), rows[tb.TARGET])
    return MonthlyModel(month, last, len(rows), config_sha256(), booster)
