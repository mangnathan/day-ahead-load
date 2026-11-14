"""Références simples pour la prévision de la consommation du lendemain.

La décision se prend à midi la veille (heure de Paris). Une valeur de consommation d'une
demi-heure n'est connue qu'une fois la demi-heure terminée, et la consommation consolidée d'un
mois n'est publiée que plus tard. Chaque référence est rangée dans une catégorie :

- réaliste : n'utilise que du consolidé publié à midi la veille ;
- optimiste : respecte midi, mais lit du consolidé que le fournisseur n'aurait pas encore
  (à midi, il n'a que le temps réel, dont il n'existe pas d'historique) ;
- avantagée : repose sur la prévision J-1 de RTE, publiée après la décision (vers 14 h 30
  selon le portail de RTE, à interroger vers 19 h 30 selon le guide de son API). Corriger
  son biais avec du consolidé publié ne rend pas la prévision elle-même disponible à midi ;
- borne : enfreint volontairement les règles, pour mesurer ce qu'elles coûtent.

À part la catégorie, `published_consolidated_only` indique si la référence ne lit que du
consolidé publié à midi : c'est vrai des références réalistes et des corrections de RTE.

Tous les instants sont en heure murale de Paris (sans fuseau). Les heures inexistantes de
mars et ambiguës d'octobre ont été écartées en amont (diagnostics.with_local_instants).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

PARIS_TZ = "Europe/Paris"
HALF_HOUR = pd.Timedelta("30min")
QUARTER = pd.Timedelta("15min")
DAY = pd.Timedelta(days=1)
WEEK = pd.Timedelta(days=7)
DECISION_HOUR = pd.Timedelta(hours=12)
TARGET_NATURES = ("Données définitives", "Données consolidées")
# Le consolidé du mois M est tenu pour disponible le 1er du mois M + CONSOLIDATED_LAG_MONTHS.
# Règle prudente fondée sur une observation datée : la documentation annonce une livraison à
# la mi-M+1, mais le 14 novembre 2026 le jeu consolidé s'arrêtait au 31 août 2026 (septembre
# non publié deux mois après sa fin).
CONSOLIDATED_LAG_MONTHS = 3
CONSOLIDATED_LAG_JUSTIFICATION = (
    "règle prudente fondée sur une observation datée : la documentation annonce la mi-M+1, "
    "mais le 14 novembre 2026 le consolidé publié s'arrêtait au 31 août 2026"
)
BIAS_WINDOW_DAYS = 28


@dataclass(frozen=True)
class Reference:
    name: str
    category: str
    description: str
    published_consolidated_only: bool


REFERENCES = (
    Reference("naif_j7", "optimiste", "même demi-heure sept jours avant", False),
    Reference("naif_j2", "optimiste", "même demi-heure deux jours avant", False),
    Reference(
        "naif_j1_matin_j2_apres_midi",
        "optimiste",
        "veille pour les heures déjà écoulées à midi, deux jours avant sinon",
        False,
    ),
    Reference(
        "moyenne_4_semaines", "optimiste", "moyenne des quatre mêmes jours précédents", False
    ),
    Reference(
        "naif_hebdo_realiste",
        "réaliste",
        "même jour de la semaine le plus récent publié en consolidé",
        True,
    ),
    Reference(
        "naif_annee_precedente", "réaliste", "même jour de la semaine 52 semaines avant", True
    ),
    Reference("rte_j1_brut", "avantagée", "prévision J-1 de RTE, moyenne f(t-15), f(t)", True),
    Reference(
        "rte_corrige_retard_reel",
        "avantagée",
        "RTE J-1 + biais par demi-heure des 28 derniers jours de consolidé publiés à midi",
        True,
    ),
    Reference(
        "rte_corrige_meme_mois_an_dernier",
        "avantagée",
        "RTE J-1 + biais par demi-heure du même mois l'année précédente",
        True,
    ),
    Reference(
        "rte_corrige_4_semaines_ideal",
        "borne",
        "RTE J-1 + biais par demi-heure des 28 jours précédant le jour livré",
        False,
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


def missing_by_cause(
    conso: pd.Series, values: pd.DataFrame, first_day: str, last_day: str
) -> dict[str, int]:
    """Demi-heures réelles de la période absentes de l'échantillon commun, par cause.

    La grille de référence suit l'heure légale réelle : 46 demi-heures le jour du passage à
    l'heure d'été, 50 le jour du retour à l'heure d'hiver. Chaque demi-heure manquante reçoit
    la première cause qui s'applique : heure ambiguë d'octobre, cible absente, puis la
    première référence indisponible dans l'ordre de REFERENCES."""
    start = pd.Timestamp(first_day).tz_localize(PARIS_TZ)
    end = (pd.Timestamp(last_day) + DAY).tz_localize(PARIS_TZ)
    real = pd.date_range(start, end, freq="30min", inclusive="left")
    wall = pd.DatetimeIndex(real.tz_localize(None))
    ambiguous = wall.duplicated(keep=False)
    causes: dict[str, int] = {
        "demi_heures_reelles": len(real),
        "heure_ambigue_octobre": int(ambiguous.sum()),
    }
    unique_wall = pd.DatetimeIndex(wall[~ambiguous])
    present = unique_wall.isin(conso.index)
    causes["cible_absente"] = int((~present).sum())
    kept = values.reindex(unique_wall[present])
    complete = kept.notna().all(axis=1)
    for r in REFERENCES:
        missing = ~complete & kept[r.name].isna()
        causes[f"reference_indisponible:{r.name}"] = int(missing.sum())
        complete = complete | missing
    causes["echantillon_commun"] = int(kept.notna().all(axis=1).sum())
    return causes
