"""Variante C de la comparaison des sources : ERA5 corrigé de l'écart moyen IFS − ERA5.

Règle écrite avant le calcul (journal des choix, entrée 4) : pour chaque point, chaque mois et
chaque heure UTC, l'écart moyen IFS − ERA5 est calculé sur les heures communes du 01/01/2017 au
14/03/2024, dans l'entraînement seulement. Il est ajouté à ERA5 au point, avant l'indice
national, puis chaque variable est ramenée dans ses bornes physiques. L'humidité n'est pas
corrigée : elle n'entre pas dans le modèle de la v0.1 (ADR 0002).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from day_ahead_load import table as tb
from day_ahead_load import weather_features as wf

GAP_FIRST = date(2017, 1, 1)
GAP_LAST = tb.TRAIN_LAST
# Bornes (basse, haute) de chaque variable corrigée ; None : pas de borne.
BOUNDS: dict[str, tuple[float | None, float | None]] = {
    wf.TEMPERATURE: (None, None),
    wf.RADIATION: (0.0, None),
    "cloud_cover": (0.0, 100.0),
    "wind_speed_10m": (0.0, None),
}
NOT_CORRECTED = {"relative_humidity_2m": "n'entre pas dans le modèle de la v0.1 (ADR 0002)"}
KEYS = ("mois", "heure_utc")


def _keys(index: pd.DatetimeIndex) -> pd.MultiIndex:
    utc = index.tz_convert("UTC")
    return pd.MultiIndex.from_arrays([utc.month, utc.hour], names=KEYS)


def mean_gap(
    reference: pd.DataFrame, other: pd.DataFrame, first: date = GAP_FIRST, last: date = GAP_LAST
) -> pd.DataFrame:
    """Écart moyen `other` − `reference` par mois et heure UTC, heures communes de [first, last]."""
    columns = list(BOUNDS)
    gap = (other[columns] - reference[columns]).dropna()
    days = pd.DatetimeIndex(gap.index).tz_convert("UTC").date
    gap = gap[np.asarray((days >= first) & (days <= last))]
    out = gap.groupby(_keys(pd.DatetimeIndex(gap.index))).mean()
    if len(out) != 12 * 24:
        raise ValueError(f"écart incomplet : {len(out)} couples (mois, heure) sur 288")
    return out


def shift_for(reference: pd.DataFrame, gap: pd.DataFrame) -> pd.DataFrame:
    """Écart à ajouter à chaque heure de `reference`, selon son mois et son heure UTC."""
    return gap.reindex(_keys(pd.DatetimeIndex(reference.index))).set_axis(reference.index)


def corrected(reference: pd.DataFrame, gap: pd.DataFrame) -> pd.DataFrame:
    """`reference` + écart de son (mois, heure UTC), ramené dans les bornes. Autres colonnes
    inchangées."""
    out = reference.copy()
    shift = shift_for(reference, gap)
    for name, (low, high) in BOUNDS.items():
        values = reference[name].to_numpy() + shift[name].to_numpy()
        if low is not None or high is not None:
            values = np.clip(values, low, high)
        out[name] = values
    return out
