"""Variables météo à la demi-heure, vues au moment de la décision.

Conventions écrites avant toute mesure :

- demi-heure : la valeur de consommation étiquetée t couvre l'intervalle (t − 30 min, t]. La
  spécification d'éCO2mix dit « puissance moyenne » sans préciser le côté de l'intervalle ;
  cette convention est une hypothèse, cohérente avec l'alignement mesuré en v0.0 (aucune
  combinaison gagnante n'utilisait de quart d'heure postérieur à t) ;
- heures Open-Meteo (documentation de l'API historique, tableau « Hourly Parameter
  Definition ») : température, nébulosité et vent sont des valeurs instantanées à l'heure
  indiquée ; le rayonnement étiqueté h est la moyenne de (h − 1 h, h], ce que la v0.0 a vérifié
  aux 12 points pour les trois sources ;
- variables instantanées : interpolation linéaire entre les deux heures qui encadrent le milieu
  de la demi-heure, t − 15 min ;
- rayonnement : la demi-heure (t − 30 min, t] est contenue dans l'heure qui finit à t arrondi à
  l'heure supérieure. La valeur étiquetée 13 h 00 s'applique donc aux demi-heures 12 h 30 et
  13 h 00 ;
- températures lissées sur 24 h et 72 h : moyenne des températures horaires aux instants de
  (t − 24 h, t] et de (t − 72 h, t]. Manquante si une seule heure manque.

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


def _regular(hourly: pd.DataFrame) -> pd.DataFrame:
    """Grille horaire complète (les heures absentes deviennent manquantes)."""
    index = pd.DatetimeIndex(hourly.index)
    if index.has_duplicates:
        raise ValueError("heures en double dans la série météo")
    full = pd.date_range(index.min(), index.max(), freq="h")
    return hourly.reindex(full)


def half_hour_features(ends_utc: pd.DatetimeIndex, hourly: pd.DataFrame) -> pd.DataFrame:
    """Variables des demi-heures qui finissent à `ends_utc`, depuis une série horaire UTC."""
    grid = _regular(hourly)
    middle = ends_utc - QUARTER
    before = middle.floor("h")
    weight = np.asarray((middle - before) / HOUR)
    out = pd.DataFrame(index=ends_utc)
    for name in INSTANT_VARIABLES:
        low = grid[name].reindex(before).to_numpy(dtype=float)
        high = grid[name].reindex(before + HOUR).to_numpy(dtype=float)
        out[name] = (1 - weight) * low + weight * high
    out[RADIATION] = grid[RADIATION].reindex(ends_utc.ceil("h")).to_numpy(dtype=float)
    for hours in SMOOTHING_HOURS:
        smoothed = grid[TEMPERATURE].rolling(hours, min_periods=hours).mean()
        # Heures de (t − n h, t] : de floor(t) − (n − 1) h à floor(t).
        out[f"temperature_lissee_{hours}h"] = smoothed.reindex(ends_utc.floor("h")).to_numpy(
            dtype=float
        )
    return out


def _latest_known(runs: pd.DataFrame) -> pd.DataFrame:
    """Pour chaque heure et chaque variable, la valeur du calcul le plus récent de `runs` qui
    la donne (les valeurs manquantes d'un calcul sont prises dans le calcul précédent)."""
    ordered = runs.sort_index(level="calcul")
    latest: pd.DataFrame = ordered.groupby(level="heure").last()
    return latest.sort_index()


def _run_days(runs: pd.DataFrame) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(
        pd.to_datetime(runs.index.get_level_values("calcul")).tz_localize("UTC")
    )


def own_day_hours(runs: pd.DataFrame) -> pd.DataFrame:
    """Pour chaque heure, la valeur du calcul de 00 UTC du même jour UTC (échéances 0 à 23 h).

    Calcul de secours : si cette valeur manque, celle du calcul antérieur le plus récent qui
    couvre l'heure. `runs` est indexé par (jour du calcul, heure UTC).
    """
    valid = pd.DatetimeIndex(runs.index.get_level_values("heure"))
    return _latest_known(runs[np.asarray(_run_days(runs) <= valid.normalize())])


def seen_at_decision(runs: pd.DataFrame, own_day: pd.DataFrame, delivered: date) -> pd.DataFrame:
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
    history = own_day[pd.DatetimeIndex(own_day.index) < start]
    return pd.concat([history, latest]).sort_index()


def forecast_features(
    rows: pd.DataFrame, runs: pd.DataFrame, own_day: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Variables météo des demi-heures de `rows` (colonnes `jour` et index `fin_utc`), jour
    livré par jour livré, telles qu'elles sont connues à midi la veille."""
    if rows.empty:
        return pd.DataFrame(columns=feature_names(), index=rows.index, dtype=float)
    own = own_day_hours(runs) if own_day is None else own_day
    span = pd.Timedelta(hours=max(SMOOTHING_HOURS) + 3)
    pieces = []
    for delivered, group in rows.groupby("jour", sort=True):
        ends = pd.DatetimeIndex(group.index)
        if not isinstance(delivered, date):
            raise TypeError(f"jour livré inattendu : {delivered!r}")
        hourly = seen_at_decision(runs, own, delivered)
        window = hourly[
            (pd.DatetimeIndex(hourly.index) >= ends.min() - span)
            & (pd.DatetimeIndex(hourly.index) <= ends.max() + HOUR)
        ]
        if window.empty:
            pieces.append(pd.DataFrame(np.nan, index=ends, columns=feature_names()))
        else:
            pieces.append(half_hour_features(ends, window))
    return pd.concat(pieces)


def feature_names() -> list[str]:
    return [*INSTANT_VARIABLES, RADIATION, *(f"temperature_lissee_{h}h" for h in SMOOTHING_HOURS)]


def _national(by_point: Mapping[Point, pd.DataFrame], weights: Mapping[str, float]) -> pd.DataFrame:
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
    return _national({p: wc.archive_series(root, source, p) for p in points}, weights)


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
    return _national(by_point, weights)
