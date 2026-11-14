"""Références simples pour la prévision de la consommation du lendemain.

La décision se prend à midi la veille (heure de Paris). Une valeur de consommation d'une
demi-heure n'est connue qu'une fois la demi-heure terminée, et la consommation consolidée d'un
mois n'est publiée que plus tard. Chaque référence est rangée dans une catégorie :

- réaliste : n'utilise que du consolidé publié à midi la veille ;
- optimiste : respecte midi, mais lit du consolidé que le fournisseur n'aurait pas encore
  (à midi, il n'a que le temps réel, dont il n'existe pas d'historique) ;
- avantagée : la prévision J-1 de RTE, publiée après midi ;
- borne : enfreint volontairement les règles, pour mesurer ce qu'elles coûtent.

Tous les instants sont en heure murale de Paris (sans fuseau). Les heures inexistantes de
mars et ambiguës d'octobre ont été écartées en amont (diagnostics.with_local_instants).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

HALF_HOUR = pd.Timedelta("30min")
QUARTER = pd.Timedelta("15min")
DAY = pd.Timedelta(days=1)
WEEK = pd.Timedelta(days=7)
DECISION_HOUR = pd.Timedelta(hours=12)
TARGET_NATURES = ("Données définitives", "Données consolidées")
# Le consolidé du mois M est tenu pour disponible le 1er du mois M + CONSOLIDATED_LAG_MONTHS.
# La documentation annonce la mi-M+1 ; le 14 novembre 2026, seul août était publié.
CONSOLIDATED_LAG_MONTHS = 3
BIAS_WINDOW_DAYS = 28


@dataclass(frozen=True)
class Reference:
    name: str
    category: str
    description: str


REFERENCES = (
    Reference("naif_j7", "optimiste", "même demi-heure sept jours avant"),
    Reference("naif_j2", "optimiste", "même demi-heure deux jours avant"),
    Reference(
        "naif_j1_matin_j2_apres_midi",
        "optimiste",
        "veille pour les heures déjà écoulées à midi, deux jours avant sinon",
    ),
    Reference("moyenne_4_semaines", "optimiste", "moyenne des quatre mêmes jours précédents"),
    Reference(
        "naif_hebdo_realiste",
        "réaliste",
        "même jour de la semaine le plus récent publié en consolidé",
    ),
    Reference("naif_annee_precedente", "réaliste", "même jour de la semaine 52 semaines avant"),
    Reference("rte_j1_brut", "avantagée", "prévision J-1 de RTE, moyenne f(t-15), f(t)"),
    Reference(
        "rte_corrige_retard_reel",
        "réaliste",
        "RTE J-1 + biais par demi-heure des 28 derniers jours de consolidé publiés à midi",
    ),
    Reference(
        "rte_corrige_meme_mois_an_dernier",
        "réaliste",
        "RTE J-1 + biais par demi-heure du même mois l'année précédente",
    ),
    Reference(
        "rte_corrige_4_semaines_ideal",
        "borne",
        "RTE J-1 + biais par demi-heure des 28 jours précédant le jour livré",
    ),
)


def decision_time(target: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Midi la veille du jour livré."""
    return target.normalize() - DAY + DECISION_HOUR


def consolidated_available_until(decision: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Fin (exclue) du consolidé publié à l'heure de décision."""
    months = decision.to_period("M") - (CONSOLIDATED_LAG_MONTHS - 1)
    return pd.DatetimeIndex(months.to_timestamp())


def target_series(df: pd.DataFrame) -> pd.Series:
    """Consommation consolidée ou définitive aux demi-heures pleines, en heure murale."""
    kept = df[df["nature"].isin(TARGET_NATURES) & df["instant"].dt.minute.isin([0, 30])]
    kept = kept.dropna(subset=["consommation"])
    wall = pd.DatetimeIndex(kept["instant"]).tz_localize(None)
    return pd.Series(kept["consommation"].astype(float).to_numpy(), index=wall).sort_index()


def forecast_series(df: pd.DataFrame) -> pd.Series:
    """Prévision J-1 de RTE au quart d'heure, en heure murale."""
    kept = df.dropna(subset=["prevision_j1"])
    wall = pd.DatetimeIndex(kept["instant"]).tz_localize(None)
    series = pd.Series(kept["prevision_j1"].astype(float).to_numpy(), index=wall)
    return series[~series.index.duplicated()].sort_index()


def aligned(forecast: pd.Series, at: pd.DatetimeIndex, offsets: tuple[int, ...]) -> np.ndarray:
    """Moyenne des prévisions décalées de `offsets` quarts d'heure, aux instants `at`."""
    values = [forecast.reindex(at + k * QUARTER).to_numpy() for k in offsets]
    return np.mean(np.vstack(values), axis=0)


def _lookup(series: pd.Series, at: pd.DatetimeIndex) -> np.ndarray:
    return series.reindex(at).to_numpy(dtype=float)


def _daily_bias(conso: pd.Series, forecast: pd.Series, offsets: tuple[int, ...]) -> pd.DataFrame:
    """Écart consommation − prévision RTE, en tableau jours × demi-heure du jour."""
    error = conso - aligned(forecast, pd.DatetimeIndex(conso.index), offsets)
    index = pd.DatetimeIndex(error.index)
    frame = pd.DataFrame(
        {"jour": index.normalize(), "demi_heure": index.strftime("%H:%M"), "e": error.to_numpy()}
    )
    return frame.pivot_table(index="jour", columns="demi_heure", values="e", aggfunc="mean")


def _bias_over(days: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    window = days[(days.index >= start) & (days.index < end)]
    return window.mean(axis=0)


def compute(
    conso: pd.Series,
    forecast: pd.Series,
    targets: pd.DatetimeIndex,
    offsets: tuple[int, ...] = (-1, 0),
) -> pd.DataFrame:
    """Valeur de chaque référence aux instants `targets` (demi-heures en heure murale)."""
    decision = decision_time(targets)
    available = consolidated_available_until(decision)
    out = pd.DataFrame(index=targets)

    out["naif_j7"] = _lookup(conso, targets - WEEK)
    out["naif_j2"] = _lookup(conso, targets - 2 * DAY)
    yesterday_known = (targets - DAY + HALF_HOUR) <= decision
    out["naif_j1_matin_j2_apres_midi"] = np.where(
        yesterday_known, _lookup(conso, targets - DAY), _lookup(conso, targets - 2 * DAY)
    )
    out["moyenne_4_semaines"] = np.mean(
        np.vstack([_lookup(conso, targets - k * WEEK) for k in range(1, 5)]), axis=0
    )

    # Nombre de semaines à remonter pour tomber sur une demi-heure terminée avant la fin du
    # consolidé publié.
    weeks_back = np.ceil((targets + HALF_HOUR - available) / WEEK).astype(int)
    out["naif_hebdo_realiste"] = _lookup(
        conso, pd.DatetimeIndex(targets - pd.to_timedelta(weeks_back * 7, unit="D"))
    )
    out["naif_annee_precedente"] = _lookup(conso, targets - 52 * WEEK)

    raw = aligned(forecast, targets, offsets)
    out["rte_j1_brut"] = raw

    days = _daily_bias(conso, forecast, offsets)
    slot = targets.strftime("%H:%M")
    window = pd.Timedelta(days=BIAS_WINDOW_DAYS)

    by_available = {
        end: _bias_over(days, end - window, end) for end in pd.DatetimeIndex(available).unique()
    }
    out["rte_corrige_retard_reel"] = raw + np.array(
        [by_available[end].get(s, np.nan) for end, s in zip(available, slot, strict=True)]
    )

    day_index = pd.DatetimeIndex(days.index)
    month_slot = days.groupby([day_index.year, day_index.month]).mean()
    last_year = [
        month_slot.loc[(t.year - 1, t.month), s]
        if (t.year - 1, t.month) in month_slot.index and s in month_slot.columns
        else np.nan
        for t, s in zip(targets, slot, strict=True)
    ]
    out["rte_corrige_meme_mois_an_dernier"] = raw + np.array(last_year, dtype=float)

    ideal = days.rolling(BIAS_WINDOW_DAYS, min_periods=BIAS_WINDOW_DAYS - 7).mean().shift(1)
    day_of = targets.normalize()
    out["rte_corrige_4_semaines_ideal"] = raw + np.array(
        [
            ideal.at[d, s] if d in ideal.index and s in ideal.columns else np.nan
            for d, s in zip(day_of, slot, strict=True)
        ],
        dtype=float,
    )
    return out


def errors(
    conso: pd.Series, refs: pd.DataFrame, common: bool = True
) -> dict[str, dict[str, float | int]]:
    """MAPE (%) et MAE (MW) de chaque référence. Avec `common`, toutes les références sont
    jugées sur les mêmes demi-heures (celles où toutes existent)."""
    truth = conso.reindex(refs.index)
    frame = refs.assign(_verite=truth.to_numpy())
    if common:
        frame = frame.dropna()
    out: dict[str, dict[str, float | int]] = {}
    for column in refs.columns:
        sample = frame[[column, "_verite"]].dropna()
        error = sample[column] - sample["_verite"]
        out[column] = {
            "demi_heures": len(sample),
            "mape_pct": round(float((error.abs() / sample["_verite"]).mean() * 100), 3),
            "mae_mw": round(float(error.abs().mean()), 1),
        }
    return out
