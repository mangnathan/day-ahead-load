"""Garde du test (journal des choix, entrée 27).

Aucune erreur sur la période de test n'est calculée, affichée ou utilisée avant la v1.0. Les
fonctions qui comparent une prévision à la consommation, ou qui lisent des résidus, appellent
`refuse_test_days` avec les jours qu'elles traitent. Le test ne s'ouvre qu'une fois, en v1.0,
par un commit qui passe TEST_OPEN à True.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import pandas as pd

TEST_FIRST = date(2025, 9, 1)
TEST_LAST = date(2026, 8, 31)
TEST_OPEN = False


class TestPeriodClosedError(RuntimeError):
    """Une erreur sur la période de test a été demandée avant l'ouverture du test."""


def refuse_test_days(days: Iterable[object]) -> None:
    """Lève une erreur si un jour de la liste tombe dans la période de test, tant qu'elle est
    fermée."""
    if TEST_OPEN:
        return
    stamps = pd.to_datetime(pd.Series(list(days)), errors="coerce").dropna()
    if stamps.empty:
        return
    inside = (stamps >= pd.Timestamp(TEST_FIRST)) & (stamps <= pd.Timestamp(TEST_LAST))
    if bool(inside.any()):
        first = stamps[inside].min().date()
        raise TestPeriodClosedError(
            f"erreur demandée sur un jour du test ({first}) : le test reste fermé jusqu'à la v1.0"
        )
