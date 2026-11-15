"""Écart entre les sources météo aux mêmes points, sur la validation.

Pour chaque jour J (heure de Paris), la prévision est le calcul ECMWF de 00 UTC de J-1,
restreint aux heures de J. Elle est comparée à ERA5 (source d'entraînement retenue) et à la
série IFS historique d'Open-Meteo (candidate, disponible depuis 2017 seulement).

À lire avec prudence : la série IFS historique est assemblée à partir de calculs du même
modèle que la prévision. Être plus proche de la prévision veut dire « plus cohérent avec
l'entrée du modèle au moment de la décision », pas « plus juste face aux observations ».
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from day_ahead_load import weather as w
from day_ahead_load.weather_points import Point

PARIS = "Europe/Paris"


def _frame(path: Path) -> pd.DataFrame:
    record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return w.hourly_frame(record["reponse"])


def archive_series(root: Path, source: str, point: Point) -> pd.DataFrame:
    """Toutes les tranches en cache d'une source d'archive pour un point, index UTC."""
    files = sorted((root / source / point.commune).glob("*.json"))
    if not files:
        raise FileNotFoundError(f"aucune donnée {source} pour {point.nom}")
    frames = [_frame(f) for f in files]
    out = pd.concat(frames).sort_index()
    if out.index.has_duplicates:
        raise ValueError(f"tranches qui se recouvrent : {source}, {point.nom}")
    return out


def paris_day(frame: pd.DataFrame, day: date) -> pd.DataFrame:
    """Les heures dont la date à Paris est `day` (23, 24 ou 25 heures selon le jour)."""
    local = pd.DatetimeIndex(frame.index).tz_convert(PARIS)
    return frame[np.asarray(local.date == day)]


def forecast_series(root: Path, point: Point, days: Iterable[date]) -> pd.DataFrame:
    """Prévision vue au moment de la décision : pour chaque jour J, le calcul de 00 UTC de J-1."""
    pieces = []
    for day in days:
        run = day - timedelta(days=1)
        path = root / "ecmwf_00utc" / point.commune / f"run-{run}.json"
        if not path.exists():
            continue
        piece = paris_day(_frame(path), day).copy()
        run_start = pd.Timestamp(run, tz="UTC")
        piece["echeance_h"] = (pd.DatetimeIndex(piece.index) - run_start) / pd.Timedelta(hours=1)
        pieces.append(piece)
    if not pieces:
        raise FileNotFoundError(f"aucun calcul ECMWF pour {point.nom}")
    return pd.concat(pieces).sort_index()


def gap(forecast: pd.Series, reference: pd.Series) -> dict[str, float | int]:
    """Erreur de `forecast` face à `reference` sur les heures communes."""
    both = pd.concat({"f": forecast, "r": reference}, axis=1).dropna()
    diff = both["f"] - both["r"]
    return {
        "heures": len(both),
        "mae": round(float(diff.abs().mean()), 3),
        "biais": round(float(diff.mean()), 3),
        "ecart_type": round(float(diff.std()), 3),
    }


def weighted_index(by_point: Mapping[Point, pd.Series], weights: Mapping[str, float]) -> pd.Series:
    """Moyenne pondérée par région ; une heure où un point manque reste manquante."""
    table = pd.concat({p.region: s for p, s in by_point.items()}, axis=1)
    regions = list(table.columns)
    values = table.to_numpy() @ np.array([weights[str(r)] for r in regions])
    values[table.isna().any(axis=1).to_numpy()] = np.nan
    return pd.Series(values, index=table.index, name="indice")


def monthly_gap(forecast: pd.Series, reference: pd.Series) -> dict[str, dict[str, float | int]]:
    both = pd.concat({"f": forecast, "r": reference}, axis=1).dropna()
    months = pd.DatetimeIndex(both.index).tz_convert(PARIS).strftime("%Y-%m")
    return {str(m): gap(g["f"], g["r"]) for m, g in both.groupby(months)}
