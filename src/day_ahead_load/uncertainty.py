"""Quantiles et intervalles autour de la prévision ponctuelle (v0.2, journal des choix, entrée 21).

Chaque quantile est la prévision ponctuelle plus le quantile empirique des résidus passés
(consommation − prévision) du groupe de la demi-heure prévue. Les résidus utilisables à midi la
veille d'un jour livré D sont ceux des jours publiés en consolidé : jusqu'à la fin du mois
M − 3, où M est le mois de la décision, dans les 12 derniers mois civils disponibles.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

LEVELS = (0.025, 0.1, 0.5, 0.9, 0.975)
INTERVALS = {"80": (0.1, 0.9), "95": (0.025, 0.975)}
WINDOW_MONTHS = 12
MIN_RESIDUAL_DAYS = 90
MIN_GROUP_RESIDUALS = 100
COLD = 10.0  # °C, température prévue de la demi-heure
SLICE_HALF_HOURS = 6  # tranches de 3 h
WORKING, SATURDAY, REST = 0, 1, 2


def day_kind(table: pd.DataFrame) -> np.ndarray:
    """Ouvré ; samedi ; dimanche, jour férié, pont ou période du 24/12 au 01/01.

    Le lundi de Pentecôte reste un jour ouvré, comme dans le modèle.
    """
    weekday = table["jour_semaine"].to_numpy()
    rest = (
        (weekday == 6)
        | table["ferie"].to_numpy(dtype=bool)
        | table["pont"].to_numpy(dtype=bool)
        | table["noel"].to_numpy(dtype=bool)
    )
    return np.where(rest, REST, np.where(weekday == 5, SATURDAY, WORKING))


def group_q1(table: pd.DataFrame) -> np.ndarray:
    return table["demi_heure"].to_numpy(dtype=int)


def group_q2(table: pd.DataFrame) -> np.ndarray:
    band = table["demi_heure"].to_numpy(dtype=int) // SLICE_HALF_HOURS
    return np.asarray(band * 3 + day_kind(table), dtype=int)


def group_q3(table: pd.DataFrame) -> np.ndarray:
    cold = table["temperature_2m"].to_numpy(dtype=float) < COLD
    return np.asarray(group_q2(table) * 2 + cold, dtype=int)


def decision_month(days: Sequence[date]) -> pd.PeriodIndex:
    """Mois de la décision : celui de la veille du jour livré."""
    return pd.PeriodIndex([pd.Timestamp(d - timedelta(days=1)) for d in days], freq="M")


def window(month: pd.Period) -> tuple[date, date]:
    """Jours dont le résidu est utilisable pour une décision du mois `month` : les 12 derniers
    mois civils publiés, jusqu'à la fin de `month` − 3."""
    last = (month - 2).start_time - pd.Timedelta(days=1)
    first = (month - 2 - WINDOW_MONTHS).start_time
    return first.date(), last.date()


@dataclass
class Calibrated:
    """Quantiles prévus, ligne par ligne, et suivi de la calibration."""

    quantiles: pd.DataFrame  # une colonne par niveau, index des lignes prévues
    judged: pd.Series  # vrai si le jour dispose d'au moins 90 jours de résidus
    residual_days: pd.Series  # nombre de jours de résidus disponibles
    fallbacks: list[dict[str, object]] = field(default_factory=list)


def calibrate(
    point: pd.Series,
    target_rows: pd.DataFrame,
    residuals: pd.Series,
    residual_rows: pd.DataFrame,
    grouping: Callable[[pd.DataFrame], np.ndarray],
    fallback: Callable[[pd.DataFrame], np.ndarray] | None = None,
    levels: Sequence[float] = LEVELS,
) -> Calibrated:
    """Quantiles de `point` aux lignes `target_rows`, à partir des résidus passés.

    `residuals` et `residual_rows` partagent leur index ; `residual_rows` porte la colonne
    `jour` et les colonnes dont dépend le groupement. Avec `fallback`, un groupe qui compte
    moins de 100 résidus à la date de calibration prend les résidus de son groupe de repli.
    """
    res_day = pd.to_datetime(residual_rows["jour"]).to_numpy()
    res_value = residuals.to_numpy(dtype=float)
    res_group = grouping(residual_rows)
    res_parent = fallback(residual_rows) if fallback else None
    tgt_group = grouping(target_rows)
    tgt_parent = fallback(target_rows) if fallback else None
    months = decision_month(list(target_rows["jour"]))

    out = np.full((len(target_rows), len(levels)), np.nan)
    judged = np.zeros(len(target_rows), dtype=bool)
    counts = np.zeros(len(target_rows), dtype=int)
    fallbacks: list[dict[str, object]] = []
    for month in months.unique():
        first, last = window(month)
        in_window = (
            (res_day >= np.datetime64(first)) & (res_day <= np.datetime64(last))
        ) & ~np.isnan(res_value)
        rows = np.asarray(months == month)
        n_days = len(np.unique(res_day[in_window]))
        counts[rows] = n_days
        if n_days < MIN_RESIDUAL_DAYS:
            continue
        judged[rows] = True
        values = res_value[in_window]
        own = _group_quantiles(values, res_group[in_window], levels)
        parent = (
            _group_quantiles(values, res_parent[in_window], levels)
            if res_parent is not None
            else {}
        )
        sizes = pd.Series(res_group[in_window]).value_counts()
        for i in np.flatnonzero(rows):
            g = int(tgt_group[i])
            if tgt_parent is not None and int(sizes.get(g, 0)) < MIN_GROUP_RESIDUALS:
                out[i] = parent[int(tgt_parent[i])]
                fallbacks.append({"mois_decision": str(month), "groupe": g, "position": int(i)})
            else:
                out[i] = own[g]
    quantiles = pd.DataFrame(
        point.to_numpy(dtype=float)[:, None] + out,
        index=target_rows.index,
        columns=[str(level) for level in levels],
    )
    return Calibrated(
        quantiles,
        pd.Series(judged, index=target_rows.index),
        pd.Series(counts, index=target_rows.index),
        fallbacks,
    )


def _group_quantiles(
    values: np.ndarray, groups: np.ndarray, levels: Sequence[float] = LEVELS
) -> dict[int, np.ndarray]:
    return {int(g): np.quantile(values[groups == g], levels) for g in np.unique(groups)}


def j7_point(target_by_wall: pd.Series, wall: pd.DatetimeIndex) -> np.ndarray:
    """Naïf J-7 : même heure murale de Paris sept jours avant."""
    return target_by_wall.reindex(wall - pd.Timedelta(days=7)).to_numpy(dtype=float)


def pinball(truth: np.ndarray, quantile: np.ndarray, level: float) -> np.ndarray:
    gap = truth - quantile
    return np.asarray(np.maximum(level * gap, (level - 1) * gap), dtype=float)


def mean_pinball(truth: np.ndarray, quantiles: pd.DataFrame) -> np.ndarray:
    """Pinball moyen des cinq niveaux, demi-heure par demi-heure (MW)."""
    losses = [pinball(truth, quantiles[str(lv)].to_numpy(), lv) for lv in LEVELS]
    return np.asarray(np.mean(losses, axis=0), dtype=float)


def covered(truth: np.ndarray, quantiles: pd.DataFrame, interval: str) -> np.ndarray:
    low, high = INTERVALS[interval]
    lo = quantiles[str(low)].to_numpy()
    hi = quantiles[str(high)].to_numpy()
    return np.asarray((truth >= lo) & (truth <= hi))


def width(quantiles: pd.DataFrame, interval: str) -> np.ndarray:
    low, high = INTERVALS[interval]
    return np.asarray(quantiles[str(high)].to_numpy() - quantiles[str(low)].to_numpy())


def admissible(coverage_80: float, coverage_95: float) -> bool:
    """Plages de l'ADR 0001, bornes comprises, en pourcentage."""
    return 75.0 <= coverage_80 <= 85.0 and 92.0 <= coverage_95 <= 98.0
