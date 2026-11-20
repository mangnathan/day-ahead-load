"""Table de données à la demi-heure : cible, calendrier, météo et niveau récent.

Une ligne par demi-heure réelle (46 le jour du passage à l'heure d'été, 50 le jour du retour à
l'heure d'hiver), indexée par l'instant UTC de fin de la demi-heure. Le jour livré est la date
publiée par éCO2mix (les demi-heures étiquetées de 00 h 00 à 23 h 30, heure de Paris), comme
pour les références de la v0.0.

Découpage de l'ADR 0001 : entraînement jusqu'au 14/03/2024, validation du 15/03/2024 au
31/08/2025, test du 01/09/2025 au 31/08/2026, ouvert une seule fois. Par défaut, la cible du
test est masquée : la table peut être construite et lue sans jamais voir le test.

Niveau récent : moyenne de la consommation consolidée ou définitive des 52 semaines qui
précèdent la fin du consolidé publié à midi la veille (règle M+3 de la v0.0). Une année
glissante donne le niveau sans effet de saison ; quatre semaines vieilles de 9 à 13 semaines
mêlent niveau et saison, ce qui expliquait les 18,8 % de la référence « hebdomadaire
réaliste ». Manquant tant que la fenêtre déborde avant le début des données ou qu'il manque
plus de 1 % de ses demi-heures.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from day_ahead_load import calendar_features as cal
from day_ahead_load import references as refs
from day_ahead_load import weather_features as wf

PARIS = "Europe/Paris"
TRAIN_LAST = date(2024, 3, 14)
VALIDATION = (date(2024, 3, 15), date(2025, 8, 31))
TEST = (date(2025, 9, 1), date(2026, 8, 31))
LEVEL_WEEKS = 52
LEVEL_MIN_SHARE = 0.99
TARGET = "consommation"
LEVEL = "niveau_52_semaines"
SOURCE_TRAIN = "era5"
SOURCE_FORECAST = "ecmwf_00utc_veille"


@dataclass(frozen=True)
class Built:
    table: pd.DataFrame
    # Une ligne par valeur lue dans un calcul de secours : jour livré, variable, heure,
    # calcul prévu par la règle et calcul utilisé.
    fallbacks: pd.DataFrame


def period(day: date) -> str:
    if day <= TRAIN_LAST:
        return "entrainement"
    if day <= VALIDATION[1]:
        return "validation"
    if day <= TEST[1]:
        return "test"
    return "prospectif"


def half_hour_grid(first: date, last: date) -> pd.DataFrame:
    """Demi-heures réelles des jours `first` à `last` (heure de Paris), index UTC de fin."""
    start = pd.Timestamp(first).tz_localize(PARIS)
    end = pd.Timestamp(last + timedelta(days=1)).tz_localize(PARIS)
    local = pd.date_range(start, end, freq="30min", inclusive="left")
    grid = pd.DataFrame(
        {
            "jour": local.date,
            "demi_heure": local.hour * 2 + local.minute // 30,
        },
        index=pd.DatetimeIndex(local.tz_convert("UTC"), name="fin_utc"),
    )
    return grid


def target_utc(instants: pd.DataFrame) -> pd.Series:
    """Consommation consolidée ou définitive aux demi-heures pleines, index UTC.

    `instants` sort de `diagnostics.with_local_instants` : les heures ambiguës d'octobre en
    sont déjà écartées.
    """
    kept = instants[
        instants["nature"].isin(refs.TARGET_NATURES) & instants["instant"].dt.minute.isin([0, 30])
    ].dropna(subset=["consommation"])
    index = pd.DatetimeIndex(kept["instant"]).tz_convert("UTC")
    series = pd.Series(kept["consommation"].astype(float).to_numpy(), index=index, name=TARGET)
    if series.index.has_duplicates:
        raise ValueError("demi-heures en double dans la cible")
    return series.sort_index()


def level_by_day(target: pd.Series, days: list[date]) -> pd.Series:
    """Niveau récent connu à midi la veille de chaque jour livré."""
    decision = pd.DatetimeIndex([pd.Timestamp(d) - refs.DAY + refs.DECISION_HOUR for d in days])
    available = refs.consolidated_available_until(decision)
    first_known = pd.DatetimeIndex(target.index).min()
    stamps = pd.DatetimeIndex(target.index)
    by_end: dict[pd.Timestamp, float] = {}
    for end_wall in available.unique():
        end = pd.Timestamp(end_wall).tz_localize(PARIS)
        start = end - pd.Timedelta(weeks=LEVEL_WEEKS)
        window = target[(stamps >= start) & (stamps < end)]
        expected = (end - start) / pd.Timedelta(minutes=30)
        complete = start >= first_known and len(window) >= LEVEL_MIN_SHARE * expected
        by_end[end_wall] = float(window.mean()) if complete else np.nan
    return pd.Series([by_end[e] for e in available], index=days, name=LEVEL)


def build(
    instants: pd.DataFrame,
    archive: pd.DataFrame,
    runs: pd.DataFrame,
    first: date,
    last: date,
    open_test: bool = False,
    convention: wf.Convention = wf.RETAINED,
) -> Built:
    """Assemble la table du jour `first` au jour `last`, avec le journal du calcul de secours.

    `archive` : indice national horaire de la source d'entraînement (ERA5 pour la variante A) ;
    `runs` : indice national horaire des calculs ECMWF de 00 UTC, indexé par (calcul, heure).
    """
    table = half_hour_grid(first, last)
    days = sorted(set(table["jour"]))
    table["periode"] = [period(d) for d in table["jour"]]

    calendar = cal.daily_calendar(first, last)
    table = table.join(calendar, on="jour")

    target = target_utc(instants)
    table[TARGET] = target.reindex(table.index).to_numpy()
    level = level_by_day(target, days)
    table[LEVEL] = level.reindex(table["jour"]).to_numpy()

    training = table["periode"] == "entrainement"
    table["source_meteo"] = np.where(training, SOURCE_TRAIN, SOURCE_FORECAST)
    forecast, fallbacks = wf.forecast_features(table[~training], runs, convention=convention)
    past = wf.half_hour_features(pd.DatetimeIndex(table.index[training]), archive, convention)
    weather = pd.concat([past, forecast]).reindex(table.index)
    table = table.join(weather)
    fallbacks["periode"] = [period(d) for d in fallbacks["jour"]]

    if not open_test:
        table.loc[table["periode"] == "test", TARGET] = np.nan
    return Built(table, fallbacks)
