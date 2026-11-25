"""Bilan de la v0.1 : mesures du modèle retenu, sans rien choisir (journal, entrée 19).

Biais : prévision − consommation, positif quand le modèle prévoit trop. Les intervalles
reprennent le bootstrap par blocs d'une semaine des comparaisons (entrée 4).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date

import numpy as np
import pandas as pd

from day_ahead_load import guard
from day_ahead_load import modelling as md

SEASONS = {
    12: "hiver",
    1: "hiver",
    2: "hiver",
    3: "printemps",
    4: "printemps",
    5: "printemps",
    6: "ete",
    7: "ete",
    8: "ete",
    9: "automne",
    10: "automne",
    11: "automne",
}
TEMPERATURE_EDGES = (0.0, 5.0, 10.0, 15.0)
TEMPERATURE_LABELS = ("< 0", "0-5", "5-10", "10-15", "> 15")
PERMUTATION_REPEATS = 5


def ape(truth: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    """Erreur absolue en pourcentage, demi-heure par demi-heure."""
    return np.asarray(np.abs(forecast - truth) / truth * 100, dtype=float)


def blocks(days: Sequence[date], first_day: date) -> np.ndarray:
    """Numéro du bloc de 7 jours livrés consécutifs à partir de `first_day`."""
    guard.refuse_test_days(days)
    offsets = (pd.to_datetime(pd.Series(days)) - pd.Timestamp(first_day)).dt.days.to_numpy()
    if (offsets < 0).any():
        raise ValueError("jour antérieur au premier bloc")
    return np.asarray(offsets, dtype=int) // md.BLOCK_DAYS


def ratio_interval(
    truth: np.ndarray,
    model: np.ndarray,
    reference: np.ndarray,
    days: Sequence[date],
    first_day: date,
    replicates: int = md.REPLICATES,
    seed: int = md.SEED,
) -> tuple[float, float, float]:
    """MAPE(modèle) / MAPE(référence) et son intervalle à 95 % : à chaque tirage des mêmes
    blocs, rapport des deux MAPE de l'échantillon tiré."""
    ids = blocks(days, first_day)
    count = int(ids.max()) + 1
    model_sums = np.bincount(ids, weights=ape(truth, model), minlength=count)
    reference_sums = np.bincount(ids, weights=ape(truth, reference), minlength=count)
    draws = np.random.default_rng(seed).integers(0, count, size=(replicates, count))
    boot = model_sums[draws].sum(axis=1) / reference_sums[draws].sum(axis=1)
    low, high = np.percentile(boot, [2.5, 97.5])
    ratio = float(ape(truth, model).mean() / ape(truth, reference).mean())
    return ratio, float(low), float(high)


def breakdown(truth: np.ndarray, forecast: np.ndarray, groups: Sequence[object]) -> pd.DataFrame:
    """MAPE, biais en MW et biais en % de la consommation moyenne, par groupe."""
    frame = pd.DataFrame(
        {
            "groupe": list(groups),
            "ape": ape(truth, forecast),
            "ecart": forecast - truth,
            "verite": truth,
        }
    )
    out = frame.groupby("groupe", sort=True).agg(
        demi_heures=("ape", "size"),
        mape_pct=("ape", "mean"),
        biais_mw=("ecart", "mean"),
        verite=("verite", "mean"),
    )
    out["biais_pct"] = out["biais_mw"] / out["verite"] * 100
    return out.drop(columns="verite")


def season(months: Sequence[int]) -> list[str]:
    return [SEASONS[int(m)] for m in months]


def temperature_band(values: np.ndarray) -> list[str]:
    """Tranches < 0, [0, 5), [5, 10), [10, 15), ≥ 15 °C."""
    if np.isnan(values).any():
        raise ValueError("température manquante")
    return [TEMPERATURE_LABELS[i] for i in np.searchsorted(TEMPERATURE_EDGES, values, "right")]


def permutation_importance(
    predict: Callable[[pd.DataFrame], np.ndarray],
    x: pd.DataFrame,
    truth: np.ndarray,
    repeats: int = PERMUTATION_REPEATS,
    seed: int = md.SEED,
) -> dict[str, float]:
    """Hausse moyenne de la MAPE, en points, quand une variable est mélangée entre lignes."""
    base = float(ape(truth, predict(x)).mean())
    rng = np.random.default_rng(seed)
    out = {}
    for column in x.columns:
        rises = []
        for _ in range(repeats):
            shuffled = x.copy()
            shuffled[column] = rng.permutation(shuffled[column].to_numpy())
            rises.append(float(ape(truth, predict(shuffled)).mean()) - base)
        out[str(column)] = float(np.mean(rises))
    return out
