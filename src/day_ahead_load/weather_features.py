"""Variables météo à la demi-heure, vues au moment de la décision.

Conventions (ADR 0002) :

- demi-heure : la valeur de consommation étiquetée t couvre l'intervalle (t − 15 min, t + 15 min].
  La spécification d'éCO2mix dit « puissance moyenne » sans préciser l'intervalle. L'option
  (t − 30 min, t] a été comparée par une mesure dans l'entraînement, règle écrite avant le
  calcul (journal des choix, entrée 3) ;
- heures Open-Meteo (documentation de l'API historique, tableau « Hourly Parameter
  Definition ») : température, nébulosité et vent sont des valeurs instantanées à l'heure
  indiquée ; le rayonnement étiqueté h est la moyenne de (h − 1 h, h], ce que la v0.0 a vérifié
  aux 12 points pour les trois sources ;
- variables instantanées : interpolation linéaire entre les deux heures qui encadrent le milieu
  de l'intervalle, t ;
- rayonnement : moyenne des heures qui recouvrent l'intervalle, pondérée par la durée du
  recouvrement. La demi-heure 12 h 30 reçoit la valeur de 13 h 00 ; la demi-heure 13 h 00
  reçoit la moitié de celle de 13 h 00 et la moitié de celle de 14 h 00 ;
- températures lissées sur 24 h et 72 h : moyenne des températures horaires des 24 et 72 heures
  qui finissent à la fin de l'intervalle, arrondie à l'heure inférieure. Manquante si une seule
  heure manque.

Source de chaque heure, y compris les heures passées des lissages :

- entraînement : ERA5 pour toutes les heures. ERA5 est publié avec environ 5 jours de retard :
  cette source n'existe pas à midi la veille pour les jours récents ;
- validation, test et production, pour le jour livré J : le calcul ECMWF de 00 UTC de J-1
  pour toutes les heures à partir de 00 UTC de J-1, donc pour les heures de J et pour celles de
  J-1, avant comme après midi ; pour les heures antérieures, les premières heures (échéances 0
  à 23 h) du calcul de 00 UTC du jour UTC de chaque heure. Tous ces calculs sont lancés au plus
  tard à 00 UTC de J-1 et déposés, avec la marge de 2 h, avant midi la veille.

Calcul de secours : une valeur absente d'un calcul est prise dans le calcul antérieur le plus
récent qui couvre l'heure, comme le ferait la production. Constaté dans le cache le 17/11/2026 :
le rayonnement de l'échéance 0 est absent de tous les calculs (une moyenne de l'heure
précédente n'existe pas au lancement), et le calcul du 23/06/2026 n'a ni température, ni vent,
ni humidité sur ses 72 heures, aux 12 points.

Le passage d'ERA5 aux calculs ECMWF dans les lissages est le même type d'écart d'une source à
l'autre que celui que mesure la comparaison A / B / C pour la température du jour.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from day_ahead_load import weather as w
from day_ahead_load import weather_compare as wc
from day_ahead_load.weather_points import Point

TEMPERATURE = "temperature_2m"
RADIATION = "shortwave_radiation"
INSTANT_VARIABLES = (TEMPERATURE, "cloud_cover", "wind_speed_10m")
VARIABLES = (*INSTANT_VARIABLES, RADIATION)
SMOOTHING_HOURS = (24, 72)
HOUR = pd.Timedelta(hours=1)
HALF_HOUR = pd.Timedelta(minutes=30)
QUARTER = pd.Timedelta(minutes=15)
RUN_PREFIX = "run-"


@dataclass(frozen=True)
class Convention:
    """Intervalle couvert par la demi-heure étiquetée t : (t + debut, t + fin]."""

    name: str
    start: pd.Timedelta
    end: pd.Timedelta

    @property
    def middle(self) -> pd.Timedelta:
        return (self.start + self.end) / 2


# Les deux options de l'ADR 0002. Retenue le 17/11/2026 par la mesure sur l'entraînement
# (journal des choix, entrée 3) : (t − 15 min, t + 15 min], MAPE moyenne 4,295 % contre
# 4,387 %, écart relatif de 2,1 %, au-delà du seuil de 1 % fixé avant le calcul.
END_LABEL = Convention("fin", -HALF_HOUR, pd.Timedelta(0))
CENTRED = Convention("centre", -QUARTER, QUARTER)
CONVENTIONS = {c.name: c for c in (END_LABEL, CENTRED)}
RETAINED = CENTRED


def _regular(hourly: pd.DataFrame) -> pd.DataFrame:
    """Grille horaire complète (les heures absentes deviennent manquantes)."""
    index = pd.DatetimeIndex(hourly.index)
    if index.has_duplicates:
        raise ValueError("heures en double dans la série météo")
    full = pd.date_range(index.min(), index.max(), freq="h")
    return hourly.reindex(full)


def half_hour_features(
    ends_utc: pd.DatetimeIndex, hourly: pd.DataFrame, convention: Convention = RETAINED
) -> pd.DataFrame:
    """Variables des demi-heures étiquetées `ends_utc`, depuis une série horaire UTC.

    Valeurs instantanées : interpolées au milieu de l'intervalle. Rayonnement : moyenne des
    heures qui recouvrent l'intervalle, pondérée par la durée du recouvrement. Lissages : heures
    jusqu'à la fin de l'intervalle, arrondie à l'heure inférieure.
    """
    grid = _regular(hourly)
    first = ends_utc + convention.start
    last = ends_utc + convention.end
    middle = ends_utc + convention.middle
    before = middle.floor("h")
    weight = np.asarray((middle - before) / HOUR)
    out = pd.DataFrame(index=ends_utc)
    for name in INSTANT_VARIABLES:
        low = grid[name].reindex(before).to_numpy(dtype=float)
        high = grid[name].reindex(before + HOUR).to_numpy(dtype=float)
        out[name] = (1 - weight) * low + weight * high
    # Heure (étiquetée par sa fin) qui contient le début de l'intervalle, puis la suivante si
    # l'intervalle déborde.
    hour_end = first.floor("h") + HOUR
    spills = np.asarray(last > hour_end)
    share = np.where(spills, np.asarray((hour_end - first) / (last - first)), 1.0)
    current = grid[RADIATION].reindex(hour_end).to_numpy(dtype=float)
    following = grid[RADIATION].reindex(hour_end + HOUR).to_numpy(dtype=float)
    out[RADIATION] = np.where(spills, share * current + (1 - share) * following, current)
    for hours in SMOOTHING_HOURS:
        smoothed = grid[TEMPERATURE].rolling(hours, min_periods=hours).mean()
        # Heures de (fin − n h, fin] : de floor(fin) − (n − 1) h à floor(fin).
        out[f"temperature_lissee_{hours}h"] = smoothed.reindex(last.floor("h")).to_numpy(
            dtype=float
        )
    return out


@dataclass(frozen=True)
class Hourly:
    """Série horaire et, pour chaque valeur, le jour du calcul qui l'a fournie."""

    values: pd.DataFrame
    runs: pd.DataFrame

    def before(self, moment: pd.Timestamp) -> Hourly:
        keep = np.asarray(pd.DatetimeIndex(self.values.index) < moment)
        return Hourly(self.values[keep], self.runs[keep])


FALLBACK_COLUMNS = ("jour", "variable", "heure_utc", "calcul_prevu", "calcul_utilise")


def _latest_known(runs: pd.DataFrame) -> Hourly:
    """Pour chaque heure et chaque variable, la valeur du calcul le plus récent de `runs` qui
    la donne (les valeurs manquantes d'un calcul sont prises dans le calcul précédent)."""
    values: dict[str, pd.Series] = {}
    used: dict[str, pd.Series] = {}
    for name in runs.columns:
        known = runs[name].dropna().sort_index(level="calcul")
        last = known.reset_index(level="calcul").groupby(level="heure").last()
        values[str(name)] = last[name]
        used[str(name)] = last["calcul"]
    return Hourly(pd.DataFrame(values).sort_index(), pd.DataFrame(used).sort_index())


def _run_days(runs: pd.DataFrame) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(
        pd.to_datetime(runs.index.get_level_values("calcul")).tz_localize("UTC")
    )


def own_day_hours(runs: pd.DataFrame) -> Hourly:
    """Pour chaque heure, la valeur du calcul de 00 UTC du même jour UTC (échéances 0 à 23 h).

    Calcul de secours : si cette valeur manque, celle du calcul antérieur le plus récent qui
    couvre l'heure. `runs` est indexé par (jour du calcul, heure UTC).
    """
    valid = pd.DatetimeIndex(runs.index.get_level_values("heure"))
    return _latest_known(runs[np.asarray(_run_days(runs) <= valid.normalize())])


def seen_at_decision(runs: pd.DataFrame, own_day: Hourly, delivered: date) -> Hourly:
    """Série horaire connue à midi la veille du jour livré.

    À partir de 00 UTC de la veille : le calcul de 00 UTC de la veille, avec le calcul de
    secours ; avant : premières heures du calcul de chaque jour (`own_day_hours`). Aucun
    calcul lancé après 00 UTC de la veille n'est lu.
    """
    run_day = delivered - timedelta(days=1)
    start = pd.Timestamp(run_day, tz="UTC")
    days = _run_days(runs)
    valid = pd.DatetimeIndex(runs.index.get_level_values("heure"))
    keep = (days <= start) & (days >= start - pd.Timedelta(days=3)) & (valid >= start)
    latest = _latest_known(runs[np.asarray(keep)])
    history = own_day.before(start)
    return Hourly(
        pd.concat([history.values, latest.values]).sort_index(),
        pd.concat([history.runs, latest.runs]).sort_index(),
    )


def _used_hours(
    ends: pd.DatetimeIndex, convention: Convention
) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    """Heures que lit chaque variable pour les demi-heures `ends` (bornes incluses)."""
    first_middle = (ends.min() + convention.middle).floor("h")
    last_middle = (ends.max() + convention.middle).floor("h") + HOUR
    longest = pd.Timedelta(hours=max(SMOOTHING_HOURS) - 1)
    out = {name: (first_middle, last_middle) for name in INSTANT_VARIABLES}
    smoothing_start = (ends.min() + convention.end).floor("h") - longest
    out[TEMPERATURE] = (min(first_middle, smoothing_start), last_middle)
    out[RADIATION] = (
        (ends.min() + convention.start).floor("h") + HOUR,
        (ends.max() + convention.end).ceil("h"),
    )
    return out


def fallbacks(
    delivered: date, hourly: Hourly, ends: pd.DatetimeIndex, convention: Convention = RETAINED
) -> pd.DataFrame:
    """Valeurs lues pour le jour livré qui ne viennent pas du calcul prévu par la règle.

    Calcul prévu : celui de la veille à partir de son lancement, celui du jour UTC de l'heure
    avant. Le rayonnement de l'échéance 0 n'est jamais fourni (pas d'heure précédente) : ce
    n'est pas une panne, il n'est pas compté.
    """
    start = pd.Timestamp(delivered - timedelta(days=1), tz="UTC")
    rows = []
    for name, (first, last) in _used_hours(ends, convention).items():
        hours = pd.DatetimeIndex(hourly.runs.index)
        used = hourly.runs[name][np.asarray((hours >= first) & (hours <= last))].dropna()
        for moment, run in zip(pd.DatetimeIndex(used.index), used.to_numpy(), strict=True):
            nominal = start if moment >= start else moment.normalize()
            if pd.Timestamp(run, tz="UTC") == nominal:
                continue
            if name == RADIATION and moment == nominal:
                continue
            rows.append((delivered, name, moment, nominal.date(), run))
    return pd.DataFrame(rows, columns=list(FALLBACK_COLUMNS))


def forecast_features(
    rows: pd.DataFrame,
    runs: pd.DataFrame,
    own_day: Hourly | None = None,
    convention: Convention = RETAINED,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Variables météo des demi-heures de `rows` (colonnes `jour` et index `fin_utc`), jour
    livré par jour livré, telles qu'elles sont connues à midi la veille, et la liste des
    utilisations du calcul de secours."""
    if rows.empty:
        empty = pd.DataFrame(columns=feature_names(), index=rows.index, dtype=float)
        return empty, pd.DataFrame(columns=list(FALLBACK_COLUMNS))
    own = own_day_hours(runs) if own_day is None else own_day
    span = pd.Timedelta(hours=max(SMOOTHING_HOURS) + 3)
    pieces = []
    used = []
    for delivered, group in rows.groupby("jour", sort=True):
        ends = pd.DatetimeIndex(group.index)
        if not isinstance(delivered, date):
            raise TypeError(f"jour livré inattendu : {delivered!r}")
        hourly = seen_at_decision(runs, own, delivered)
        hours = pd.DatetimeIndex(hourly.values.index)
        keep = np.asarray((hours >= ends.min() - span) & (hours <= ends.max() + HOUR))
        window = Hourly(hourly.values[keep], hourly.runs[keep])
        if window.values.empty:
            pieces.append(pd.DataFrame(np.nan, index=ends, columns=feature_names()))
            continue
        pieces.append(half_hour_features(ends, window.values, convention))
        used.append(fallbacks(delivered, window, ends, convention))
    log = (
        pd.concat(used, ignore_index=True) if used else pd.DataFrame(columns=list(FALLBACK_COLUMNS))
    )
    return pd.concat(pieces), log


def feature_names() -> list[str]:
    return [*INSTANT_VARIABLES, RADIATION, *(f"temperature_lissee_{h}h" for h in SMOOTHING_HOURS)]


def national(by_point: Mapping[Point, pd.DataFrame], weights: Mapping[str, float]) -> pd.DataFrame:
    """Indice national horaire de chaque variable, moyenne des points pondérée par région."""
    return pd.DataFrame(
        {
            name: wc.weighted_index({p: f[name] for p, f in by_point.items()}, weights)
            for name in VARIABLES
        }
    )


def archive_index(
    root: Path, source: str, points: Sequence[Point], weights: Mapping[str, float]
) -> pd.DataFrame:
    """Indice national horaire (UTC) d'une source d'archive, pondéré par région."""
    return national({p: wc.archive_series(root, source, p) for p in points}, weights)


def runs_index(root: Path, points: Sequence[Point], weights: Mapping[str, float]) -> pd.DataFrame:
    """Indice national horaire de chaque calcul de 00 UTC en cache, indexé par (calcul, heure)."""
    by_point = {}
    for point in points:
        frames = {}
        for path in sorted((root / "ecmwf_00utc" / point.commune).glob(f"{RUN_PREFIX}*.json")):
            record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            run_day = date.fromisoformat(path.stem.removeprefix(RUN_PREFIX))
            # Certaines réponses contiennent des valeurs nulles : elles deviennent manquantes.
            frames[run_day] = w.hourly_frame(record["reponse"]).astype(float)
        if not frames:
            raise FileNotFoundError(f"aucun calcul ECMWF pour {point.nom}")
        by_point[point] = pd.concat(frames, names=["calcul", "heure"])
    return national(by_point, weights)
