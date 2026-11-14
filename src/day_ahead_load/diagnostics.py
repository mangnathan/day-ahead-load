"""Diagnostics de l'étude de faisabilité sur la prévision J-1 de RTE.

Trois questions : à quel instant de la prévision (au quart d'heure) correspond la
consommation moyenne d'une demi-heure, comment les jours de changement d'heure sont codés, et
comment le biais de la prévision évolue par mois et par tranche horaire.

Les instants sont reconstruits à partir de la date et de l'heure locales publiées, et non du
champ `date_heure` d'ODRÉ, qui convertit mal les jours de changement d'heure (voir v0.0).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

PARIS = "Europe/Paris"
QUARTER = pd.Timedelta("15min")
RAW_COLUMNS = ["nature", "date", "heure", "consommation", "prevision_j1"]

# Tranches horaires (heure locale, borne de début incluse) pour lire le profil du biais.
BANDS = (("00-06", 0), ("06-12", 6), ("12-13", 12), ("13-17", 13), ("17-20", 17), ("20-24", 20))

# Prévision comparée à la consommation de l'instant t, exprimée comme moyenne de prévisions
# décalées (en quarts d'heure). (0,) = la prévision de t seule.
ALIGNMENTS: dict[str, tuple[int, ...]] = {
    "f(t)": (0,),
    "f(t+15)": (1,),
    "f(t-15)": (-1,),
    "moyenne f(t-15), f(t)": (-1, 0),
    "moyenne f(t), f(t+15) = [t, t+30]": (0, 1),
    "moyenne f(t-30), f(t-15) = [t-30, t]": (-2, -1),
}


def read_raw(paths: list[Path]) -> pd.DataFrame:
    frames = [pd.read_parquet(p, columns=RAW_COLUMNS) for p in paths]
    return pd.concat(frames, ignore_index=True)


def with_local_instants(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Ajoute l'instant (heure de Paris) reconstruit depuis la date et l'heure publiées.

    Les heures qui n'existent pas (02 h le jour du passage à l'heure d'été) et les heures
    ambiguës (les deux 02 h du retour à l'heure d'hiver, dont on ne sait pas laquelle est
    publiée) sont écartées et comptées.
    """
    naive = pd.to_datetime(raw["date"] + " " + raw["heure"], format="%Y-%m-%d %H:%M")
    local = pd.DatetimeIndex(naive).tz_localize(PARIS, ambiguous="NaT", nonexistent="NaT")
    out = raw.assign(instant=local)
    dropped = out["instant"].isna()
    months = naive[dropped].dt.month
    counts = {
        "lignes_heure_inexistante_mars": int((months == 3).sum()),
        "lignes_heure_ambigue_octobre": int((months == 10).sum()),
    }
    out = out[~dropped].drop_duplicates("instant").sort_values("instant").reset_index(drop=True)
    return out, counts


def aligned_forecast(df: pd.DataFrame, offsets: tuple[int, ...]) -> pd.Series:
    """Moyenne des prévisions décalées de `offsets` quarts d'heure, indexée par instant."""
    forecast = df.set_index("instant")["prevision_j1"].astype(float)
    shifted = [
        forecast.reindex(forecast.index + k * QUARTER).set_axis(forecast.index) for k in offsets
    ]
    return pd.concat(shifted, axis=1).mean(axis=1, skipna=False)


def alignment_table(df: pd.DataFrame, years: list[int]) -> dict[str, dict[str, dict[str, float]]]:
    """Pour chaque année et chaque alignement : MAE, MAE de 6 h à 9 h (montée du matin) et
    écart-type de l'erreur. L'écart-type ne dépend pas du biais moyen, qui gonfle la MAE de
    certaines années et masquerait l'effet du seul alignement."""
    conso = df.dropna(subset=["consommation"]).set_index("instant")["consommation"].astype(float)
    out: dict[str, dict[str, dict[str, float]]] = {}
    for year in years:
        c = conso[pd.DatetimeIndex(conso.index).year == year]
        rows: dict[str, dict[str, float]] = {}
        for name, offsets in ALIGNMENTS.items():
            aligned: pd.Series = aligned_forecast(df, offsets).reindex(c.index)
            error: pd.Series = aligned.sub(c).dropna()
            hours = pd.DatetimeIndex(error.index).hour
            ramp = (hours >= 6) & (hours < 9)
            rows[name] = {
                "mae_mw": round(float(error.abs().mean()), 1),
                "mae_6h_9h_mw": round(float(error[ramp].abs().mean()), 1),
                "ecart_type_mw": round(float(error.std()), 1),
            }
        out[str(year)] = rows
    return out


def october_jumps(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Variation de consommation 02 h 30 → 03 h 00 et 01 h 30 → 02 h 00 (heure affichée) le
    jour du retour à l'heure d'hiver, comparée aux dimanches une semaine avant et après.

    Calculé sur l'heure affichée, avant d'écarter les heures ambiguës : c'est justement le
    codage de ces heures qu'on cherche à reconnaître."""
    conso = df.dropna(subset=["consommation"])
    shown = pd.to_datetime(conso["date"] + " " + conso["heure"], format="%Y-%m-%d %H:%M")
    series = pd.Series(conso["consommation"].astype(float).to_numpy(), index=shown)
    series = series[~series.index.duplicated()]

    def jump(day: pd.Timestamp, start: str, end: str) -> float:
        a = series.get(pd.Timestamp(f"{day.date()} {start}"))
        b = series.get(pd.Timestamp(f"{day.date()} {end}"))
        return float(b - a) if a is not None and b is not None else float("nan")

    out = []
    for year in sorted(set(pd.DatetimeIndex(series.index).year)):
        sundays = pd.date_range(f"{year}-10-25", f"{year}-10-31", freq="W-SUN")
        if len(sundays) != 1:
            continue
        day = sundays[0]
        if pd.Timestamp(f"{day.date()} 03:00") not in series.index:
            continue
        week = pd.Timedelta(days=7)
        out.append(
            {
                "annee": year,
                "jour": str(day.date()),
                "saut_0230_0300": jump(day, "02:30", "03:00"),
                "saut_0130_0200": jump(day, "01:30", "02:00"),
                "voisins_saut_0230_0300": [
                    jump(day - week, "02:30", "03:00"),
                    jump(day + week, "02:30", "03:00"),
                ],
                "voisins_saut_0130_0200": [
                    jump(day - week, "01:30", "02:00"),
                    jump(day + week, "01:30", "02:00"),
                ],
            }
        )
    return out


def monthly_bias(df: pd.DataFrame, start: str) -> dict[str, dict[str, Any]]:
    """Biais moyen (prévision − consommation, MW) par mois et par tranche horaire, avec la
    nature des données du mois. Seules les demi-heures pleines sont comparées."""
    both = df.dropna(subset=["consommation", "prevision_j1"])
    both = both[
        (both["instant"] >= pd.Timestamp(start, tz=PARIS)) & both["instant"].dt.minute.isin([0, 30])
    ]
    error = both["prevision_j1"].astype(float) - both["consommation"].astype(float)
    month = both["instant"].dt.strftime("%Y-%m")
    band = pd.cut(
        both["instant"].dt.hour,
        [start for _, start in BANDS] + [24],
        right=False,
        labels=[name for name, _ in BANDS],
    )
    table = error.groupby([month, band], observed=True).mean().unstack()
    overall = error.groupby(month).mean()
    natures = both.groupby(month)["nature"].agg(lambda s: sorted(set(s)))
    return {
        str(m): {
            "nature": natures[m],
            "tout": round(float(overall[m]), 0),
            **{str(b): round(float(v), 0) for b, v in table.loc[m].items()},
        }
        for m in table.index
    }
