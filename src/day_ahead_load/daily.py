"""Chaîne quotidienne de la v0.4 (journal des choix, entrée 27).

Pour le jour livré D, avant midi, heure de Paris, la veille : la prévision centrale des
demi-heures de D par le modèle figé, les cinq quantiles de la fourchette figée et le volume au
quantile q de la v0.3, étiqueté « règle de la v0.3, non validée ».

Les fonctions de ce module sont pures : elles ne font aucun appel réseau. Le script
`scripts/pipeline/daily_forecast.py` télécharge les entrées et écrit les fichiers.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from day_ahead_load import calendar_features as cal
from day_ahead_load import frozen
from day_ahead_load import modelling as md
from day_ahead_load import table as tb
from day_ahead_load import weather_features as wf

PARIS = "Europe/Paris"
SAFETY_MARGIN = timedelta(hours=2)
RUN_DAYS_BACK = 4  # calculs de D-4 à D-1 : lissage sur 72 h et heures de D
LABELS = [
    "prévisions produites par ce projet, pas des données RTE",
    "modèle et fourchette figés à la fin de la validation (31/08/2025), test fermé",
    f"volume au quantile q : {frozen.PURCHASE_LABEL}",
]
SOURCES = {
    "consommation": "éCO2mix (RTE, via ODRÉ), Licence Ouverte 2.0 : niveau des 52 semaines",
    "meteo": "Open-Meteo, calculs ECMWF IFS de 00 UTC, CC BY 4.0 : indice national",
}


def delivered_day(now: datetime) -> date:
    """Le jour livré prévu par une exécution : le lendemain, heure de Paris."""
    local = pd.Timestamp(now).tz_convert(PARIS)
    return (local + pd.Timedelta(days=1)).date()


def deadline(day: date) -> pd.Timestamp:
    """Midi, heure de Paris, la veille du jour livré, en UTC."""
    noon = pd.Timestamp(day - timedelta(days=1)).replace(hour=12).tz_localize(PARIS)
    return noon.tz_convert("UTC")


def run_ready(now: datetime, deposit: datetime) -> bool:
    """Le calcul est utilisable 2 h après son dépôt sur la copie AWS d'Open-Meteo (ADR 0001)."""
    return pd.Timestamp(deposit) + SAFETY_MARGIN <= pd.Timestamp(now)


def on_time(completed: datetime, day: date) -> str:
    """Statut jugé sur l'heure de fin de l'étape de prévision, enregistrée par GitHub."""
    return "à l'heure" if pd.Timestamp(completed) <= deadline(day) else "en retard"


def run_from_csv(text: str) -> pd.DataFrame:
    frame = pd.read_csv(io.StringIO(text), index_col="heure")
    frame.index = pd.DatetimeIndex(frame.index).tz_convert("UTC")
    return frame.astype(float)


def run_to_csv(frame: pd.DataFrame) -> str:
    out = frame[list(wf.VARIABLES)].copy()
    out.index = pd.DatetimeIndex(out.index).strftime("%Y-%m-%dT%H:%MZ")
    out.index.name = "heure"
    return str(out.round(3).to_csv(lineterminator="\n"))


def runs_frame(runs: dict[date, pd.DataFrame]) -> pd.DataFrame:
    """Calculs stockés, indexés par (jour du calcul, heure UTC), comme `runs_index`."""
    if not runs:
        return pd.DataFrame(
            columns=list(wf.VARIABLES),
            index=pd.MultiIndex.from_arrays([[], []], names=["calcul", "heure"]),
        )
    return pd.concat(runs, names=["calcul", "heure"]).sort_index()


@dataclass(frozen=True)
class Inputs:
    """Ce que la chaîne sait à midi la veille du jour livré."""

    day: date
    runs: pd.DataFrame  # indice national de chaque calcul de 00 UTC, (calcul, heure)
    level: float | None  # niveau des 52 semaines, connu à midi la veille


def features(inputs: Inputs) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Variables des demi-heures du jour livré, et journal du calcul de secours."""
    rows = tb.half_hour_grid(inputs.day, inputs.day)
    rows = rows.join(cal.daily_calendar(inputs.day, inputs.day), on="jour")
    rows[tb.LEVEL] = np.nan if inputs.level is None else inputs.level
    weather, log = wf.forecast_features(rows, inputs.runs)
    return rows.join(weather), log


def weather_runs_used(inputs: Inputs) -> dict[str, list[str]]:
    """Pour chaque variable, les calculs de 00 UTC qui ont fourni les heures du jour livré."""
    hourly = wf.seen_at_decision(inputs.runs, wf.own_day_hours(inputs.runs), inputs.day)
    rows = tb.half_hour_grid(inputs.day, inputs.day)
    ends = pd.DatetimeIndex(rows.index)
    hours = pd.DatetimeIndex(hourly.runs.index)
    keep = np.asarray(
        (hours >= ends.min() - timedelta(hours=1)) & (hours <= ends.max() + timedelta(hours=1))
    )
    used = hourly.runs[keep]
    return {name: sorted({f"{d}T00:00Z" for d in used[name].dropna()}) for name in wf.VARIABLES}


@dataclass(frozen=True)
class Absence:
    day: date
    cause: str


def forecast(
    inputs: Inputs, model_text: str, offsets: dict[str, dict[str, float]]
) -> pd.DataFrame | Absence:
    """Prévision, quantiles et volume au quantile q ; une absence si une entrée manque."""
    if inputs.level is None or not np.isfinite(inputs.level):
        return Absence(inputs.day, "niveau des 52 semaines absent")
    table, _ = features(inputs)
    missing = [c for c in md.FEATURES if table[c].isna().any()]
    if missing:
        return Absence(inputs.day, f"entrées manquantes après le calcul de secours : {missing}")
    booster = lgb.Booster(model_str=model_text)
    point = np.asarray(booster.predict(md.design(table)), dtype=float)
    out = pd.DataFrame(
        {"jour": table["jour"], "demi_heure": table["demi_heure"]}, index=table.index
    )
    out["prevision"] = point
    slots = table["demi_heure"].astype(int).astype(str)
    for level in frozen.OFFSET_LEVELS:
        shift = np.array([offsets[s][str(level)] for s in slots])
        name = "achat_q" if level == frozen.PURCHASE_Q else f"q{level}"
        out[name] = point + shift
    return out


def core(
    day: date, prediction: pd.DataFrame, inputs: Inputs, meta: dict[str, Any]
) -> dict[str, Any]:
    """Contenu de prévision dont l'empreinte est publiée : tout sauf les champs d'exécution."""
    local = pd.DatetimeIndex(prediction.index).tz_convert(PARIS)
    rows = []
    ends = pd.DatetimeIndex(prediction.index)
    for end, (_, row), paris in zip(ends, prediction.iterrows(), local, strict=True):
        rows.append(
            {
                "fin_utc": end.strftime("%Y-%m-%dT%H:%MZ"),
                "heure_paris": paris.strftime("%Y-%m-%d %H:%M %z"),
                "prevision_mw": round(float(row["prevision"]), 1),
                "quantiles_mw": {
                    str(lv): round(float(row[f"q{lv}"]), 1) for lv in frozen.OFFSET_LEVELS[:-1]
                },
                "achat_au_quantile_q_mw": round(float(row["achat_q"]), 1),
            }
        )
    return {
        "jour_livre": str(day),
        "decision_au_plus_tard_utc": deadline(day).strftime("%Y-%m-%dT%H:%MZ"),
        "etiquettes": LABELS,
        "sources": SOURCES,
        "quantile_d_achat": {"q": frozen.PURCHASE_Q, "etiquette": frozen.PURCHASE_LABEL},
        "niveau_52_semaines_mw": None if inputs.level is None else round(inputs.level, 1),
        "calculs_meteo_utilises": weather_runs_used(inputs),
        "artefacts": meta,
        "demi_heures": rows,
    }


def canonical(content: dict[str, Any]) -> str:
    return json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def content_sha256(content: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(content).encode("utf-8")).hexdigest()


def write_once(path: Path, text: str) -> bool:
    """Écrit le fichier s'il n'existe pas encore ; ne l'écrase jamais. Renvoie s'il a écrit."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as out:
        out.write(text)
    return True


def now_utc() -> datetime:
    return datetime.now(UTC)


def merge_levels(
    existing: dict[str, float | None], computed: dict[str, float | None], now: datetime
) -> dict[str, float | None]:
    """Complète les niveaux d'un mois sans jamais réécrire le passé.

    Une valeur déjà publiée ne change pas. Un niveau vide n'est rempli que si la décision de
    son jour livré (midi la veille) est encore à venir : un jour passé sans niveau reste sans
    prévision, jamais rattrapé après coup.
    """
    merged = dict(existing)
    for day, value in computed.items():
        if merged.get(day) is not None:
            continue
        if deadline(date.fromisoformat(day)) > pd.Timestamp(now):
            merged[day] = value
        else:
            merged.setdefault(day, None)
    return dict(sorted(merged.items()))
