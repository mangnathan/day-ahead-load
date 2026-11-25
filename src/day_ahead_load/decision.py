"""Décision d'achat de la v0.3 : quantile du vendeur de journaux et coût des écarts.

Règles écrites avant le calcul (journal des choix, entrées 24 et 25) :

- la demi-heure étiquetée t couvre (t − 15 min, t + 15 min] ; elle se coupe en deux quarts
  d'heure qui commencent à t − 15 min et à t, de même écart de puissance, chacun réglé au prix
  de la période de règlement qui le contient ;
- le règlement se fait à la demi-heure avant le 01/01/2025, heure de Paris, et au quart d'heure
  ensuite ; le 31/12/2024, publié au quart d'heure avec des prix recopiés, reste à la demi-heure ;
- coût d'un quart d'heure, pour un écart Δ = s × (consommation − achat) en MWh : Δ × (prix
  payé par le fournisseur court − P_ref) s'il est court, |Δ| × (P_ref − prix payé au
  fournisseur long) s'il est long ;
- un quart d'heure sans prix est retiré de tous les calculs à la fois.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

QUARTER = pd.Timedelta(minutes=15)
HALF_HOUR = pd.Timedelta(minutes=30)
# Début du règlement au quart d'heure : 01/01/2025 à 0 h, heure de Paris.
QUARTER_SETTLEMENT = pd.Timestamp("2024-12-31T23:00Z")
LONG, SHORT = "pre_positif", "pre_negatif"  # payé au fournisseur long, payé par le court


def quarter_prices(prices: pd.DataFrame) -> pd.DataFrame:
    """Prix sur une grille au quart d'heure, une ligne par quart d'heure.

    Une période de 30 minutes donne deux quarts d'heure au même prix. Avant le règlement au
    quart d'heure, une publication au pas de 15 minutes doit porter le même prix sur les deux
    quarts d'heure de chaque demi-heure : elle est ramenée à la demi-heure, sinon refusée.
    """
    index = pd.DatetimeIndex(prices.index)
    before = np.asarray(index < QUARTER_SETTLEMENT)
    early_quarters = prices[before & (prices["pas"].to_numpy() == 15)]
    if len(early_quarters):
        halves = pd.DatetimeIndex(early_quarters.index).floor("30min")
        spread = early_quarters.groupby(halves)[[LONG, SHORT]].agg(lambda s: s.max() - s.min())
        if (spread.to_numpy() > 0).any():
            raise ValueError("prix différents dans une demi-heure réglée à la demi-heure")
    pieces = []
    for step in (30, 15):
        part = prices[prices["pas"].to_numpy() == step][[LONG, SHORT]]
        if step == 30 or len(part) == 0:
            starts = pd.DatetimeIndex(part.index)
            pieces += [part.set_axis(starts), part.set_axis(starts + QUARTER)]
        else:
            pieces.append(part)
    out: pd.DataFrame = pd.concat(pieces).sort_index()
    if out.index.duplicated().any():
        raise ValueError("quart d'heure compté deux fois")
    return out


def half_hour_quarters(ends: pd.DatetimeIndex) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    """Débuts des deux quarts d'heure de la demi-heure étiquetée t : t − 15 min et t."""
    return ends - QUARTER, ends


@dataclass(frozen=True)
class Quarters:
    """Une ligne par quart d'heure jugé : les deux quarts d'heure de chaque demi-heure."""

    frame: pd.DataFrame  # colonnes : jour, consommation, prevision, pre_positif, pre_negatif
    excluded: pd.DataFrame  # quarts d'heure retirés faute de prix : debut, jour


def expand(rows: pd.DataFrame, prices_q: pd.DataFrame, columns: list[str]) -> Quarters:
    """Coupe chaque demi-heure en ses deux quarts d'heure et y joint les prix.

    `rows` est indexé par l'étiquette t (UTC) et porte `jour` et `columns` (puissances en MW).
    """
    first, second = half_hour_quarters(pd.DatetimeIndex(rows.index))
    parts = []
    for starts in (first, second):
        part = rows[["jour", *columns]].copy()
        part.index = starts
        parts.append(part)
    frame = pd.concat(parts).sort_index()
    frame = frame.join(prices_q, how="left")
    missing = frame[[LONG, SHORT]].isna().any(axis=1)
    excluded = pd.DataFrame({"debut": frame.index[missing], "jour": frame.loc[missing, "jour"]})
    return Quarters(frame[~missing], excluded.reset_index(drop=True))


def energy(power_mw: np.ndarray, share: float) -> np.ndarray:
    """Énergie d'un quart d'heure, en MWh, pour la part de marché `share`."""
    return np.asarray(power_mw * share * QUARTER.total_seconds() / 3600, dtype=float)


def cost(
    consumption: np.ndarray,
    purchase: np.ndarray,
    long_price: np.ndarray,
    short_price: np.ndarray,
    reference: float,
    share: float,
) -> np.ndarray:
    """Coût de chaque quart d'heure face à un achat parfait, en euros."""
    delta = energy(consumption - purchase, share)
    short = delta * (short_price - reference)
    long = -delta * (reference - long_price)
    return np.asarray(np.where(delta > 0, short, long), dtype=float)


@dataclass(frozen=True)
class Penalties:
    short: float  # Cu
    long: float  # Co
    short_periods: int
    long_periods: int

    @property
    def quantile(self) -> float | None:
        """q = Cu / (Cu + Co) ; None si Cu ou Co n'est pas strictement positif."""
        if self.short <= 0 or self.long <= 0:
            return None
        return self.short / (self.short + self.long)


def penalties_by_sign(
    error: np.ndarray, long_price: np.ndarray, short_price: np.ndarray, reference: float
) -> Penalties:
    """Formule B : chaque pénalité est moyennée sur les périodes où la prévision ponctuelle
    laissait le fournisseur court (erreur > 0) ou long (erreur < 0)."""
    short = error > 0
    long = error < 0
    return Penalties(
        float(np.mean(short_price[short] - reference)),
        float(np.mean(reference - long_price[long])),
        int(short.sum()),
        int(long.sum()),
    )


def penalties_all(long_price: np.ndarray, short_price: np.ndarray, reference: float) -> Penalties:
    """Formule A de l'ADR 0001 : moyennes sur toutes les périodes (information)."""
    n = len(long_price)
    return Penalties(
        float(np.mean(short_price - reference)), float(np.mean(reference - long_price)), n, n
    )
