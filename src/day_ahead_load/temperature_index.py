"""Choix des poids de l'indice national de température.

L'indice est une moyenne pondérée de températures régionales. Trois pondérations sont
comparées : population, consommation électrique, et part de la consommation sensible à la
température, approchée par la consommation d'hiver moins celle d'été. Cette dernière est une
approximation : la consommation d'été contient la climatisation (surtout en Provence-Alpes-
Côte d'Azur et en Occitanie), ce qui sous-estime la part de ces régions.

Les températures régionales observées (moyennes de stations, ODRÉ) ne servent qu'à ce choix.
Le modèle, lui, sera entraîné et utilisé sur les mêmes points de grille, pour voir la même
grandeur en entraînement et en prévision.

Le choix se fait par validation croisée temporelle : chaque année de test est prévue par un
modèle entraîné sur les seules années précédentes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import numpy as np
import pandas as pd

# Régions de France continentale (périmètre de la consommation nationale de RTE, sans la Corse).
MAINLAND_REGIONS = ("11", "24", "27", "28", "32", "44", "52", "53", "75", "76", "84", "93")
HEATING_BASE_C = 15.0
COOLING_BASE_C = 20.0
WINTER_MONTHS = (12, 1, 2)
SUMMER_MONTHS = (6, 7, 8)


def normalize(weights: Mapping[str, float]) -> dict[str, float]:
    kept = {r: max(float(weights.get(r, 0.0)), 0.0) for r in MAINLAND_REGIONS}
    total = sum(kept.values())
    if total <= 0:
        raise ValueError("poids tous nuls")
    return {r: w / total for r, w in kept.items()}


def population_weights(population: Mapping[str, float]) -> dict[str, float]:
    return normalize(population)


def consumption_weights(regional: pd.DataFrame) -> dict[str, float]:
    """Part moyenne de chaque région dans la consommation (colonnes region, date, conso_mw)."""
    totals = regional.groupby("region")["conso_mw"].mean()
    return normalize({str(r): float(v) for r, v in totals.items()})


def thermosensitive_weights(regional: pd.DataFrame) -> dict[str, float]:
    """Consommation moyenne d'hiver moins consommation moyenne d'été, par région."""
    month = pd.DatetimeIndex(regional["date"]).month
    winter = regional[np.isin(month, WINTER_MONTHS)].groupby("region")["conso_mw"].mean()
    summer = regional[np.isin(month, SUMMER_MONTHS)].groupby("region")["conso_mw"].mean()
    gap = (winter - summer).fillna(0.0)
    return normalize({str(r): float(v) for r, v in gap.items()})


def national_index(temperatures: pd.DataFrame, weights: Mapping[str, float]) -> pd.Series:
    """Indice journalier : moyenne pondérée des températures (colonnes region, date, tmoy).
    Un jour où une région manque reste manquant plutôt que d'être repondéré."""
    table = temperatures.pivot_table(index="date", columns="region", values="tmoy")
    table = table.reindex(columns=list(MAINLAND_REGIONS))
    w = np.array([weights[r] for r in MAINLAND_REGIONS])
    values = table.to_numpy() @ w
    values[table.isna().any(axis=1).to_numpy()] = np.nan
    return pd.Series(values, index=pd.DatetimeIndex(table.index), name="indice")


def design(index: pd.Series, years: list[int]) -> pd.DataFrame:
    """Variables du modèle journalier : degrés-jours de chauffage sous 15 °C, degrés-jours de
    climatisation au-dessus de 20 °C, jour de la semaine et niveau de chaque année."""
    dates = pd.DatetimeIndex(index.index)
    x = pd.DataFrame(index=dates)
    x["dj_chauffage"] = np.maximum(HEATING_BASE_C - index.to_numpy(), 0.0)
    x["dj_climatisation"] = np.maximum(index.to_numpy() - COOLING_BASE_C, 0.0)
    for day in range(1, 7):
        x[f"jour_{day}"] = (dates.day_of_week == day).astype(float)
    for year in years:
        x[f"annee_{year}"] = (dates.year == year).astype(float)
    return x


def fit(x: pd.DataFrame, y: pd.Series) -> pd.Series:
    coef, *_ = np.linalg.lstsq(x.to_numpy(), y.to_numpy(), rcond=None)
    return pd.Series(coef, index=x.columns)


def cross_validate(
    index_for: Callable[[int], pd.Series],
    consumption: pd.Series,
    first_year: int,
    test_years: list[int],
) -> dict[str, Any]:
    """Pour chaque année de test, entraînement sur les années précédentes depuis
    `first_year`. `index_for(annee)` construit l'indice avec des poids calculés sur les seules
    années antérieures à `annee`. Le niveau de l'année de test, inconnu à l'entraînement, est
    pris égal à celui de la dernière année d'entraînement."""
    folds: dict[str, dict[str, float]] = {}
    for year in test_years:
        data = pd.concat({"t": index_for(year), "y": consumption}, axis=1).dropna()
        years_of = pd.DatetimeIndex(data.index).year
        train = data[(years_of >= first_year) & (years_of < year)]
        test = data[years_of == year]
        train_years = sorted(set(pd.DatetimeIndex(train.index).year))
        coef = fit(design(train["t"], train_years), train["y"])
        x_test = design(test["t"], train_years)
        x_test[f"annee_{train_years[-1]}"] = 1.0
        error = x_test.to_numpy() @ coef.to_numpy() - test["y"].to_numpy()
        folds[str(year)] = {
            "jours": len(test),
            "mae_mw": round(float(np.abs(error).mean()), 1),
            "mape_pct": round(float((np.abs(error) / test["y"].to_numpy()).mean() * 100), 3),
            "sensibilite_chauffage_mw_par_degre": round(float(coef["dj_chauffage"]), 0),
        }
    maes = [f["mae_mw"] for f in folds.values()]
    return {"par_annee_de_test": folds, "mae_moyenne_mw": round(float(np.mean(maes)), 1)}
