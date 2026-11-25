"""Artefacts figés de la chaîne quotidienne (v0.4, journal des choix, entrée 27).

Tant que le test est fermé, la chaîne n'utilise que des artefacts qui ne lisent aucune
consommation de la période de test :

- un modèle de même configuration qu'A17, entraîné sur les jours livrés du 01/01/2017 au
  31/08/2025 (fin de la validation), avec la météo ERA5 ;
- les écarts de la fourchette : pour chaque demi-heure de la journée, les quantiles des résidus
  de la procédure mensuelle sur les jours livrés du 01/09/2024 au 31/08/2025 ;
- le quantile d'achat q = 0,4616 de la v0.3, étiqueté « règle de la v0.3, non validée ».

Les écarts sont écrits en JSON canonique, pour qu'un même calcul donne les mêmes octets.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

import numpy as np
import pandas as pd

from day_ahead_load import guard
from day_ahead_load import modelling as md
from day_ahead_load import table as tb
from day_ahead_load import uncertainty as unc

FROZEN_END = date(2025, 8, 31)
OFFSET_WINDOW = (date(2024, 9, 1), date(2025, 8, 31))
PURCHASE_Q = 0.4616
PURCHASE_LABEL = "règle de la v0.3, non validée"
OFFSET_LEVELS = (*unc.LEVELS, PURCHASE_Q)


def sha256(data: str | bytes) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


def training_rows(train_table: pd.DataFrame) -> pd.DataFrame:
    """Jours livrés du 01/01/2017 au 31/08/2025, cible connue : jamais une ligne du test."""
    day = pd.to_datetime(train_table["jour"])
    keep = (
        (day >= pd.Timestamp(md.TRAIN_FIRST))
        & (day <= pd.Timestamp(FROZEN_END))
        & train_table[tb.TARGET].notna()
    )
    return train_table[keep]


def fit_model(rows: pd.DataFrame) -> str:
    """Entraîne le modèle figé et le renvoie sous forme de texte (format de LightGBM)."""
    last = max(rows["jour"])
    if last > FROZEN_END:
        raise ValueError(f"ligne d'entraînement du {last}, après la fin de la validation")
    booster = md.fit(md.design(rows), rows[tb.TARGET])
    return str(booster.model_to_string())


def offsets(residuals: pd.Series, rows: pd.DataFrame) -> pd.DataFrame:
    """Quantiles des résidus par demi-heure de la journée, sur la fenêtre figée.

    `residuals` (consommation − prévision) et `rows` partagent leur index ; `rows` porte `jour`
    et `demi_heure`. Seuls les résidus de la fenêtre comptent, et le garde refuse ceux du test.
    """
    day = pd.to_datetime(rows["jour"])
    keep = np.asarray(
        (day >= pd.Timestamp(OFFSET_WINDOW[0]))
        & (day <= pd.Timestamp(OFFSET_WINDOW[1]))
        & residuals.notna()
    )
    guard.refuse_test_days(rows.loc[keep, "jour"])
    values = residuals.to_numpy(dtype=float)[keep]
    slots = rows["demi_heure"].to_numpy(dtype=int)[keep]
    table = {int(s): np.quantile(values[slots == s], OFFSET_LEVELS) for s in sorted(set(slots))}
    return pd.DataFrame.from_dict(
        table, orient="index", columns=[str(level) for level in OFFSET_LEVELS]
    )


def offsets_json(frame: pd.DataFrame) -> str:
    """JSON canonique : demi-heures et niveaux triés, valeurs arrondies au dixième de MW."""
    ordered = frame.sort_index()
    data = {
        str(int(slot)): {
            str(level): round(float(value), 1)
            for level, value in zip(ordered.columns, values, strict=True)
        }
        for slot, values in zip(ordered.index.to_numpy(dtype=int), ordered.to_numpy(), strict=True)
    }
    return json.dumps(data, sort_keys=True, ensure_ascii=False, indent=1) + "\n"
